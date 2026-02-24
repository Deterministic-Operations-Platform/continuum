import json
import unittest
from pathlib import Path

from continuum.publish import publish_run
from tests._tmpdir import make_temp_dir, remove_temp_dir


class PublishCommandTests(unittest.TestCase):
    def test_publish_copies_run_and_generates_indexes(self) -> None:
        root = make_temp_dir("publish")
        self.addCleanup(lambda: remove_temp_dir(root))

        runs_dir = root / "runs"
        site_dir = root / "site"
        run_id = "pub-001"
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True)

        (run_dir / "report.html").write_text("<h1>report token=abc123</h1>", encoding="utf-8")
        (run_dir / "summary.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": "succeeded",
                    "startedAt": "2026-01-01T00:00:00Z",
                    "endedAt": "2026-01-01T00:01:00Z",
                    "policy": {"ok": True, "missing": []},
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "context.json").write_text(json.dumps({"vars": {"traceId": "trace-1"}}), encoding="utf-8")
        (run_dir / "manifest.json").write_text(json.dumps({"git_head": "abcde"}), encoding="utf-8")
        (run_dir / "bundle_signature.json").write_text(json.dumps({"keyId": "ci", "manifest_sha256": "deadbeef"}), encoding="utf-8")
        (run_dir / "debug.tmp").write_text("secret", encoding="utf-8")

        publish_run(run_id=run_id, runs_dir=runs_dir, site_dir=site_dir)

        published_run_dir = site_dir / "runs" / run_id
        self.assertTrue((published_run_dir / "report.html").exists())
        self.assertFalse((published_run_dir / "debug.tmp").exists())

        index_html = (site_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn(f"runs/{run_id}/report.html", index_html)

        index_json = json.loads((site_dir / "runs" / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(index_json[0]["runId"], run_id)
        self.assertEqual(index_json[0]["traceId"], "trace-1")
        self.assertEqual(index_json[0]["policyOk"], True)
        self.assertEqual(index_json[0]["signed"], True)

        published_report = (published_run_dir / "report.html").read_text(encoding="utf-8")
        self.assertIn("[REDACTED]", published_report)


if __name__ == "__main__":
    unittest.main()
