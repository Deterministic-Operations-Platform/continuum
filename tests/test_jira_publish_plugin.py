import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from continuum.plugins import JiraPublishPlugin
from tests._tmpdir import make_temp_dir, remove_temp_dir


class _JiraHandler(BaseHTTPRequestHandler):
    received = {"comment": None, "attach": None}

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        body = self.rfile.read(length) if length else b""

        if self.path.endswith("/comment"):
            _JiraHandler.received["comment"] = {
                "path": self.path,
                "auth": self.headers.get("Authorization"),
                "body": body.decode("utf-8", errors="replace"),
            }
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"id":"10000"}')
            return

        if self.path.endswith("/attachments"):
            _JiraHandler.received["attach"] = {
                "path": self.path,
                "token": self.headers.get("X-Atlassian-Token"),
                "ctype": self.headers.get("Content-Type"),
                "auth": self.headers.get("Authorization"),
                "raw": body[:2000],
            }
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'[{"id":"att-1"}]')
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, *_args, **_kwargs):
        return


class JiraPublishPluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir("jira")
        self.addCleanup(lambda: remove_temp_dir(self.root))

        self.run_dir = self.root / "runs" / "r1"
        self.run_dir.mkdir(parents=True)

        (self.run_dir / "summary.json").write_text(json.dumps({"status": "succeeded", "policy": {"ok": True}}), encoding="utf-8")
        (self.run_dir / "manifest.json").write_text("{}", encoding="utf-8")
        (self.run_dir / "bundle_signature.json").write_text(json.dumps({"keyId": "ci", "manifest_sha256": "abc"}), encoding="utf-8")
        (self.run_dir / "report.html").write_text("<h1>report</h1>", encoding="utf-8")

        self.step_root = self.run_dir / "evidence"
        self.step_root.mkdir(parents=True, exist_ok=True)

    def _ctx(self, env: dict) -> dict:
        def step_dir(i: int, name: str) -> str:
            return str(self.run_dir / "evidence" / f"{i+1:02d}-{name.replace(' ', '_')}")

        def write_json(step_path: str, filename: str, payload: dict) -> str:
            p = Path(step_path) / filename
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            return str(p)

        return {
            "run_id": "r1",
            "run_dir": str(self.run_dir),
            "vars": {"traceId": "trace-1", "issueKey": "PROJ-1"},
            "env": env,
            "step_dir": step_dir,
            "write_json": write_json,
        }

    def test_dry_run_when_env_missing(self) -> None:
        result = JiraPublishPlugin().run(
            step_name="jira publish",
            step_with={"attach": ["report.html"]},
            ctx=self._ctx(env={}),
            step_index=0,
        )
        self.assertTrue(result.ok)
        evidence = json.loads(Path(result.evidence_paths[0]).read_text(encoding="utf-8"))
        self.assertTrue(evidence["dryRun"])
        self.assertIn("JIRA_BASE_URL", evidence["missing"])

    def test_posts_comment_and_attachments(self) -> None:
        _JiraHandler.received = {"comment": None, "attach": None}
        server = HTTPServer(("127.0.0.1", 0), _JiraHandler)
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)

        env = {
            "JIRA_BASE_URL": f"http://127.0.0.1:{port}",
            "JIRA_EMAIL": "a@b.com",
            "JIRA_API_TOKEN": "token",
            "CONTINUUM_SITE_URL": "http://site.local",
        }

        result = JiraPublishPlugin().run(
            step_name="jira publish",
            step_with={"issueKey": "PROJ-1", "attach": ["report.html"], "apiVersion": 2},
            ctx=self._ctx(env=env),
            step_index=0,
        )
        self.assertTrue(result.ok)

        self.assertIsNotNone(_JiraHandler.received["comment"])
        self.assertTrue(str(_JiraHandler.received["comment"]["auth"]).startswith("Basic "))
        self.assertIn("Continuum Run: r1", _JiraHandler.received["comment"]["body"])

        self.assertIsNotNone(_JiraHandler.received["attach"])
        self.assertEqual(_JiraHandler.received["attach"]["token"], "no-check")
        self.assertIn("multipart/form-data", str(_JiraHandler.received["attach"]["ctype"]))


if __name__ == "__main__":
    unittest.main()
