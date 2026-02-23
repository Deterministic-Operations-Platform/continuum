import hashlib
import json
import shutil
import sqlite3
import unittest
from pathlib import Path

from continuum import DeterministicRuntime, EvidenceCollector, PluginRegistry, Scenario, ScenarioStep, StepResult
from continuum.plugins import JiraFetchPlugin, SqlVerifyPlugin


REPO_ROOT = Path(__file__).resolve().parents[1]


class _NoopPlugin:
    type = "test.noop"

    def run(self, *, step_name, step_with, ctx, step_index):
        return StepResult(ok=True, details={"ok": True}, evidence_paths=[], exports={})


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


if __name__ == "__main__":
    unittest.main()
