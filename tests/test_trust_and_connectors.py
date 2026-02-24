import hashlib
import json
import os
import shutil
import sqlite3
import sys
from types import SimpleNamespace
import unittest
from pathlib import Path
from unittest.mock import patch

from continuum import DeterministicRuntime, EvidenceCollector, PluginRegistry, Scenario, ScenarioStep, StepResult
from continuum.errors import StepExecutionError
from continuum.plugins import (
    HttpRequestPlugin,
    JiraAttachPlugin,
    JiraCommentPlugin,
    JiraFetchPlugin,
    MongoDbVerifyPlugin,
    MongoVerifyPlugin,
    SqlVerifyPlugin,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class _NoopPlugin:
    type = "test.noop"

    def run(self, *, step_name, step_with, ctx, step_index):
        return StepResult(ok=True, details={"ok": True}, evidence_paths=[], exports={})


class _FakeHttpResponse:
    def __init__(self, *, status: int, payload: object):
        self.status = int(status)
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TrustAndConnectorTests(unittest.TestCase):
    def test_rbac_and_approval_file(self) -> None:
        denied_run = "test-governance-denied"
        allowed_run = "test-governance-allowed"
        approval_file = REPO_ROOT / "runs" / "test-approval.json"
        self.addCleanup(lambda: shutil.rmtree(REPO_ROOT / "runs" / denied_run, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(REPO_ROOT / "runs" / allowed_run, ignore_errors=True))
        self.addCleanup(lambda: approval_file.unlink(missing_ok=True))

        scenario = Scenario(
            name="gov-test",
            rail="test",
            vars={},
            governance={"allowedRoles": ["director"], "requireApproval": True, "approvalFile": str(approval_file)},
            steps=(ScenarioStep(name="noop", type="test.noop", key="01_noop", with_={}),),
            cleanup_steps=(),
        )
        runtime = DeterministicRuntime(plugin_registry=PluginRegistry([_NoopPlugin()]), evidence_collector=EvidenceCollector())

        denied_summary = runtime.execute(
            scenario=scenario,
            scenario_source=Path("tests/fixture.yaml"),
            scenario_text="name: gov-test",
            run_id=denied_run,
            actor="alice",
            actor_roles=("analyst",),
        )
        self.assertEqual(denied_summary["status"], "failed")
        self.assertIn("RBAC denied", denied_summary["failure"]["message"])
        self.assertTrue((REPO_ROOT / "runs" / denied_run / "manifest.json").exists())

        approval_file.parent.mkdir(parents=True, exist_ok=True)
        approval_file.write_text(
            json.dumps({"status": "approved", "scenario": "gov-test", "approvalId": "ap-1", "approvedBy": "director"}),
            encoding="utf-8",
        )
        scenario_allowed = Scenario(
            name="gov-test",
            rail="test",
            vars={},
            governance={"allowedRoles": ["director"], "requireApproval": True, "approvalFile": str(approval_file), "approvalId": "ap-1"},
            steps=(ScenarioStep(name="noop", type="test.noop", key="01_noop", with_={}),),
            cleanup_steps=(),
        )
        allowed_summary = runtime.execute(
            scenario=scenario_allowed,
            scenario_source=Path("tests/fixture.yaml"),
            scenario_text="name: gov-test",
            run_id=allowed_run,
            actor="bob",
            actor_roles=("director",),
        )
        self.assertEqual(allowed_summary["status"], "succeeded")
        self.assertTrue(allowed_summary["governance"]["approval"]["verified"])

    def test_audit_log_chain_and_manifest_integrity(self) -> None:
        run_id = "test-audit-chain"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        scenario = Scenario(
            name="audit-test",
            rail="test",
            vars={},
            steps=(ScenarioStep(name="noop", type="test.noop", key="01_noop", with_={}),),
            cleanup_steps=(),
        )
        runtime = DeterministicRuntime(plugin_registry=PluginRegistry([_NoopPlugin()]), evidence_collector=EvidenceCollector())
        with patch.dict(
            os.environ,
            {"CONTINUUM_SIGNING_KEY": "unit-test-signing-key", "CONTINUUM_SIGNING_KEY_ID": "unit-test"},
            clear=False,
        ):
            summary = runtime.execute(
                scenario=scenario,
                scenario_source=Path("tests/fixture.yaml"),
                scenario_text="name: audit-test",
                run_id=run_id,
            )
        self.assertEqual(summary["status"], "succeeded")

        events = [json.loads(line) for line in (run_dir / "events.log").read_text(encoding="utf-8").splitlines() if line.strip()]
        prev_hash = ""
        for event in events:
            self.assertEqual(event["prevHash"], prev_hash)
            body = dict(event)
            body.pop("hash", None)
            computed = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            self.assertEqual(event["hash"], computed)
            prev_hash = event["hash"]

        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("integrity", manifest)
        self.assertIn("artifactSetSha256", manifest["integrity"])
        signature = json.loads((run_dir / "bundle_signature.json").read_text(encoding="utf-8"))
        sha_line = (run_dir / "manifest.sha256").read_text(encoding="utf-8").strip()
        self.assertIn(signature["manifest_sha256"], sha_line)

    def test_sql_verify_plugin_and_jira_inference(self) -> None:
        db_path = REPO_ROOT / "runs" / "test-sql-verify.sqlite"
        self.addCleanup(lambda: db_path.unlink(missing_ok=True))
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("create table if not exists payments(id integer primary key, trace_id text)")
            conn.execute("insert into payments(trace_id) values (?)", ("trace-1",))
            conn.commit()
        finally:
            conn.close()

        step_dir = REPO_ROOT / "runs" / "test-sql-plugin"
        self.addCleanup(lambda: shutil.rmtree(step_dir, ignore_errors=True))

        def _ctx_step_dir(index: int, name: str) -> str:
            return str(step_dir / "evidence" / f"{index + 1:02d}-{name}")

        def _ctx_write_json(step_path: str, filename: str, payload: dict) -> str:
            output = Path(step_path) / filename
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            return str(output)

        ctx = {"step_dir": _ctx_step_dir, "write_json": _ctx_write_json, "vars": {"traceId": "trace-1"}, "run_id": "sql-test", "run_dir": str(step_dir)}
        sql_result = SqlVerifyPlugin().run(
            step_name="verify-sql",
            step_with={
                "database": str(db_path),
                "queries": [{"name": "rows", "sql": "select * from payments where trace_id = ?", "params": ["trace-1"]}],
                "assert": [{"query": "rows", "op": "gte", "value": 1}],
            },
            ctx=ctx,
            step_index=0,
        )
        self.assertTrue(sql_result.ok)
        jira_result = JiraFetchPlugin().run(
            step_name="jira-fetch",
            step_with={"issue": {"labels": ["postman", "mongo"]}},
            ctx=ctx,
            step_index=1,
        )
        required = set(jira_result.details["requiredSteps"])
        self.assertIn("run_postman", required)
        self.assertIn("verify_mongo", required)

    def test_mongo_live_mode_executes_queries_with_env_gate(self) -> None:
        step_dir = REPO_ROOT / "runs" / "test-mongo-live"
        self.addCleanup(lambda: shutil.rmtree(step_dir, ignore_errors=True))

        def _ctx_step_dir(index: int, name: str) -> str:
            return str(step_dir / "evidence" / f"{index + 1:02d}-{name}")

        def _ctx_write_json(step_path: str, filename: str, payload: dict) -> str:
            output = Path(step_path) / filename
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            return str(output)

        ctx = {
            "step_dir": _ctx_step_dir,
            "write_json": _ctx_write_json,
            "vars": {"traceId": "trace-live"},
            "run_id": "mongo-live",
            "run_dir": str(step_dir),
            "env": {"CONTINUUM_ENABLE_LIVE_CONNECTORS": "1"},
        }

        class _FakeCursor:
            def __init__(self, docs: list[dict]):
                self._docs = list(docs)

            def limit(self, count: int) -> "_FakeCursor":
                return _FakeCursor(self._docs[: max(0, int(count))])

            def __iter__(self):
                return iter(self._docs)

        class _FakeCollection:
            def __init__(self, docs: list[dict]):
                self._docs = list(docs)

            def count_documents(self, query: dict) -> int:
                return len([doc for doc in self._docs if doc.get("traceId") == query.get("traceId")])

            def find(self, query: dict, projection: dict | None = None) -> _FakeCursor:
                matched = [doc for doc in self._docs if doc.get("traceId") == query.get("traceId")]
                if isinstance(projection, dict):
                    projected: list[dict] = []
                    for doc in matched:
                        keep = {k: v for k, v in doc.items() if projection.get(k, 1)}
                        projected.append(keep)
                    return _FakeCursor(projected)
                return _FakeCursor(matched)

        class _FakeDb:
            def __getitem__(self, name: str) -> _FakeCollection:
                return _FakeCollection(
                    [
                        {"_id": "1", "traceId": "trace-live", "status": "ok"},
                        {"_id": "2", "traceId": "trace-live", "status": "ok"},
                    ]
                )

        class _FakeAdmin:
            def command(self, name: str) -> dict:
                return {"ok": 1, "name": name}

        class _FakeMongoClient:
            def __init__(self, uri: str, serverSelectionTimeoutMS: int):
                self.uri = uri
                self.timeout = serverSelectionTimeoutMS
                self.admin = _FakeAdmin()

            def __getitem__(self, name: str) -> _FakeDb:
                return _FakeDb()

            def close(self) -> None:
                return

        fake_pymongo = SimpleNamespace(MongoClient=_FakeMongoClient)
        with patch.dict(sys.modules, {"pymongo": fake_pymongo}):
            result = MongoVerifyPlugin().run(
                step_name="verify-mongo-live",
                step_with={
                    "live": True,
                    "uri": "mongodb://example.invalid:27017",
                    "db": "payments",
                    "autoFilterTraceId": True,
                    "queries": [{"name": "ledgerRows", "collection": "ledger", "filter": {}, "limit": 10}],
                    "assert": [{"query": "ledgerRows", "op": "gte", "value": 1}],
                },
                ctx=ctx,
                step_index=0,
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.details["mode"], "live")
        self.assertEqual(result.details["queryResults"]["ledgerRows"]["count"], 2)
        self.assertTrue(result.details["traceQueryApplied"])
        self.assertEqual(result.exports["mongoAssertionsOk"], True)

    def test_jira_live_fetch_comment_and_attach(self) -> None:
        step_dir = REPO_ROOT / "runs" / "test-jira-live"
        self.addCleanup(lambda: shutil.rmtree(step_dir, ignore_errors=True))
        attachment = step_dir / "evidence" / "sample.txt"
        attachment.parent.mkdir(parents=True, exist_ok=True)
        attachment.write_text("evidence", encoding="utf-8")

        def _ctx_step_dir(index: int, name: str) -> str:
            return str(step_dir / "evidence" / f"{index + 1:02d}-{name}")

        def _ctx_write_json(step_path: str, filename: str, payload: dict) -> str:
            output = Path(step_path) / filename
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            return str(output)

        ctx = {
            "step_dir": _ctx_step_dir,
            "write_json": _ctx_write_json,
            "vars": {"traceId": "trace-jira", "issueKey": "PAY-42"},
            "run_id": "jira-live",
            "run_dir": str(step_dir),
            "env": {
                "CONTINUUM_ENABLE_LIVE_CONNECTORS": "1",
                "JIRA_BASE_URL": "https://jira.example.test",
                "JIRA_EMAIL": "engineer@example.test",
                "JIRA_API_TOKEN": "top-secret-token",
            },
        }
        requests: list[dict[str, str]] = []

        def _fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
            method = request.get_method()
            url = request.full_url
            auth = request.headers.get("Authorization", "")
            requests.append({"method": method, "url": url, "auth": auth})
            if method == "GET" and "/rest/api/2/issue/" in url:
                return _FakeHttpResponse(
                    status=200,
                    payload={
                        "fields": {
                            "labels": ["postman", "mongo"],
                            "components": [{"name": "payments"}],
                            "summary": "Investigate payment issue",
                            "status": {"name": "Open"},
                        }
                    },
                )
            if method == "POST" and url.endswith("/comment"):
                return _FakeHttpResponse(status=201, payload={"id": "c-1"})
            if method == "POST" and url.endswith("/attachments"):
                return _FakeHttpResponse(status=200, payload=[{"id": "a-1"}])
            raise AssertionError(f"Unexpected Jira request: {method} {url}")

        with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            fetch_result = JiraFetchPlugin().run(
                step_name="jira-fetch-live",
                step_with={"live": True, "issueKey": "PAY-42"},
                ctx=ctx,
                step_index=0,
            )
            comment_result = JiraCommentPlugin().run(
                step_name="jira-comment-live",
                step_with={"live": True, "body": "Run jira-live completed."},
                ctx=ctx,
                step_index=1,
            )
            attach_result = JiraAttachPlugin().run(
                step_name="jira-attach-live",
                step_with={"live": True, "files": [str(attachment)]},
                ctx=ctx,
                step_index=2,
            )

        required = set(fetch_result.details["requiredSteps"])
        self.assertIn("run_postman", required)
        self.assertIn("verify_mongo", required)
        self.assertTrue(comment_result.ok)
        self.assertEqual(comment_result.details["commentId"], "c-1")
        self.assertTrue(attach_result.ok)
        self.assertEqual(attach_result.details["uploaded"][0]["attachmentId"], "a-1")
        self.assertTrue(all(item["auth"].startswith("Basic ") for item in requests))
        self.assertNotIn("top-secret-token", json.dumps(comment_result.details))

    def test_live_connectors_require_runtime_gate(self) -> None:
        step_dir = REPO_ROOT / "runs" / "test-live-gate-required"
        self.addCleanup(lambda: shutil.rmtree(step_dir, ignore_errors=True))

        def _ctx_step_dir(index: int, name: str) -> str:
            return str(step_dir / "evidence" / f"{index + 1:02d}-{name}")

        def _ctx_write_json(step_path: str, filename: str, payload: dict) -> str:
            output = Path(step_path) / filename
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            return str(output)

        ctx = {
            "step_dir": _ctx_step_dir,
            "write_json": _ctx_write_json,
            "vars": {"traceId": "trace-gate", "issueKey": "PAY-1"},
            "run_id": "gate-required",
            "run_dir": str(step_dir),
            "env": {
                "JIRA_BASE_URL": "https://jira.example.test",
                "JIRA_EMAIL": "engineer@example.test",
                "JIRA_API_TOKEN": "token",
            },
        }

        with self.assertRaises(StepExecutionError):
            JiraCommentPlugin().run(
                step_name="jira-comment-live",
                step_with={"live": True, "body": "blocked"},
                ctx=ctx,
                step_index=0,
            )

        with self.assertRaises(StepExecutionError):
            MongoVerifyPlugin().run(
                step_name="mongo-live",
                step_with={"live": True, "uri": "mongodb://example.invalid", "db": "payments", "queries": []},
                ctx=ctx,
                step_index=1,
            )


    def test_http_request_and_mongodb_verify_plugins(self) -> None:
        step_dir = REPO_ROOT / "runs" / "test-http-mongodb-plugin"
        self.addCleanup(lambda: shutil.rmtree(step_dir, ignore_errors=True))

        def _ctx_step_dir(index: int, name: str) -> str:
            return str(step_dir / "evidence" / f"{index + 1:02d}-{name}")

        def _ctx_write_json(step_path: str, filename: str, payload: dict) -> str:
            output = Path(step_path) / filename
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            return str(output)

        ctx = {"step_dir": _ctx_step_dir, "write_json": _ctx_write_json, "vars": {"traceId": "trace-1"}, "run_id": "plugin-test", "run_dir": str(step_dir)}
        http_result = HttpRequestPlugin().run(
            step_name="http-check",
            step_with={"url": "https://example.com", "expectStatus": 200, "timeoutSec": 10},
            ctx=ctx,
            step_index=0,
        )
        self.assertTrue(http_result.ok)
        mongo_result = MongoDbVerifyPlugin().run(
            step_name="mongo-check",
            step_with={"autoFilterTraceId": True, "queries": [{"filter": {"status": "ok"}}]},
            ctx=ctx,
            step_index=1,
        )
        self.assertTrue(mongo_result.ok)
        self.assertTrue(mongo_result.details["traceQueryApplied"])


if __name__ == "__main__":
    unittest.main()
