import unittest
from pathlib import Path
import shutil

from continuum.publish import _write_run_indexes, PublishedRun
from continuum.schema import validate_scenario_schema


class CiAndViewerTests(unittest.TestCase):
    def test_schema_validator_reports_deterministic_errors(self) -> None:
        errors = validate_scenario_schema({"name": "x", "rail": "r", "steps": [{"type": 123}]})
        self.assertEqual(sorted(errors), errors)
        self.assertTrue(any("steps[0] missing required field 'name'" in item for item in errors))

    def test_evidence_viewer_contains_compare_columns(self) -> None:
        site_dir = Path("runs") / "test-site-index"
        site_dir.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(site_dir, ignore_errors=True))

        _write_run_indexes(
            site_dir,
            [
                PublishedRun(
                    run_id="r-1",
                    status="succeeded",
                    started_at="2024-01-01T00:00:00Z",
                    ended_at="2024-01-01T00:01:00Z",
                    trace_id="trace-1",
                    git_head="abc123",
                    report_path="runs/r-1/report.html",
                    signed=True,
                    policy_ok=True,
                    signature_key_id="",
                    manifest_sha256="",
                    signature_verified=True,
                    signature_verify_msg="ok",
                )
            ],
        )
        html = (site_dir / "index.html").read_text(encoding="utf-8")
        self.assertIn("Evidence Viewer", html)
        self.assertIn("Compare Data", html)
        self.assertIn("Policy", html)
        self.assertIn("Signed", html)
        self.assertIn("Verified", html)
        self.assertIn("trace-1", html)
        self.assertIn("Signed?", html)
        self.assertIn("Verified?", html)
        self.assertIn("Policy OK?", html)


if __name__ == "__main__":
    unittest.main()
