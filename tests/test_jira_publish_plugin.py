import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from continuum.plugins import JiraPublishPlugin
from tests._tmpdir import make_temp_dir, remove_temp_dir


class JiraPublishPluginTests(unittest.TestCase):
    def test_publish_posts_comment_and_attachments(self) -> None:
        root = make_temp_dir("jira-publish")
        self.addCleanup(lambda: remove_temp_dir(root))
        run_dir = root / "runs" / "run-1"
        run_dir.mkdir(parents=True)
        (run_dir / "report.html").write_text("<h1>report</h1>", encoding="utf-8")
        (run_dir / "summary.json").write_text("{}", encoding="utf-8")

        requests: list[dict[str, str]] = []

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8", errors="replace")
                requests.append({"path": self.path, "body": body})
                if self.path.endswith("/comment"):
                    payload = json.dumps({"id": "comment-1"}).encode("utf-8")
                    self.send_response(201)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                payload = json.dumps([{"id": "attachment-1"}]).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, format, *args):  # type: ignore[override]
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)

        evidence_root = root / "evidence"

        def _ctx_step_dir(index: int, name: str) -> str:
            return str(evidence_root / f"{index + 1:02d}-{name}")

        def _ctx_write_json(step_path: str, filename: str, payload: dict) -> str:
            output = Path(step_path) / filename
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            return str(output)

        ctx = {
            "step_dir": _ctx_step_dir,
            "write_json": _ctx_write_json,
            "vars": {},
            "run_id": "run-1",
            "run_dir": str(run_dir),
            "env": {
                "CONTINUUM_ENABLE_LIVE_CONNECTORS": "1",
                "JIRA_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                "JIRA_EMAIL": "ops@example.test",
                "JIRA_API_TOKEN": "secret",
                "JIRA_ISSUE_KEY": "PAY-101",
                "CONTINUUM_SITE_URL": "https://site.example.test",
            },
        }

        result = JiraPublishPlugin().run(
            step_name="publish",
            step_with={"attach": ["report.html", "summary.json"], "apiVersion": 2, "softFail": False},
            ctx=ctx,
            step_index=0,
        )

        self.assertTrue(result.ok)
        self.assertFalse(result.details["dryRun"])
        self.assertEqual(result.details["commentId"], "comment-1")
        self.assertEqual(len(result.details["uploaded"]), 2)
        self.assertEqual(len(requests), 3)
        self.assertIn("/rest/api/2/issue/PAY-101/comment", requests[0]["path"])

    def test_publish_dry_runs_when_jira_env_missing(self) -> None:
        root = make_temp_dir("jira-publish-dry")
        self.addCleanup(lambda: remove_temp_dir(root))
        run_dir = root / "runs" / "run-2"
        run_dir.mkdir(parents=True)
        (run_dir / "report.html").write_text("<h1>report</h1>", encoding="utf-8")

        def _ctx_step_dir(index: int, name: str) -> str:
            return str(root / "evidence" / f"{index + 1:02d}-{name}")

        def _ctx_write_json(step_path: str, filename: str, payload: dict) -> str:
            output = Path(step_path) / filename
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            return str(output)

        ctx = {
            "step_dir": _ctx_step_dir,
            "write_json": _ctx_write_json,
            "vars": {},
            "run_id": "run-2",
            "run_dir": str(run_dir),
            "env": {},
        }

        result = JiraPublishPlugin().run(
            step_name="publish",
            step_with={"attach": ["report.html"]},
            ctx=ctx,
            step_index=0,
        )

        self.assertTrue(result.ok)
        self.assertTrue(result.details["dryRun"])
        self.assertIn("JIRA_BASE_URL", result.details["missing"])


if __name__ == "__main__":
    unittest.main()
