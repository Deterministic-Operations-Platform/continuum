import json
import shutil
import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class ContinuumSmokeTests(unittest.TestCase):
    def test_status_command_reports_ready(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "continuum", "status"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("deterministic runtime ready", result.stdout)

    def test_run_command_writes_expected_evidence_bundle(self) -> None:
        run_id = "test-smoke-run"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "continuum",
                "run",
                "examples/fednow-cam29-success.yaml",
                "--run-id",
                run_id,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(run_dir.exists(), "Run directory was not created")

        summary_path = run_dir / "summary.json"
        manifest_path = run_dir / "manifest.json"
        scenario_path = run_dir / "scenario.yaml"
        events_path = run_dir / "events.log"

        for artifact in (summary_path, manifest_path, scenario_path, events_path):
            self.assertTrue(artifact.exists(), f"Missing artifact: {artifact}")

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(summary["run_id"], run_id)
        self.assertEqual(summary["status"], "succeeded")



if __name__ == "__main__":
    unittest.main()
