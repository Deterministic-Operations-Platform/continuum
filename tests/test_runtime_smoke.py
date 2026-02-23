import json
import os
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
        context_path = run_dir / "context.json"

        for artifact in (summary_path, manifest_path, scenario_path, context_path):
            self.assertTrue(artifact.exists(), f"Missing artifact: {artifact}")

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(summary["run_id"], run_id)
        self.assertEqual(summary["status"], "succeeded")

    def test_postman_step_writes_preflight_when_newman_is_missing(self) -> None:
        run_id = "test-preflight-newman"
        run_dir = REPO_ROOT / "runs" / run_id
        scenario_path = REPO_ROOT / "runs" / f"{run_id}-scenario.yaml"
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))
        self.addCleanup(lambda: scenario_path.unlink(missing_ok=True))

        scenario_path.write_text(
            """
name: Preflight Missing Newman
rail: fednow
steps:
  - name: run postman collection
    type: postman.run
    with:
      collection: fake-collection.json
""".strip(),
            encoding="utf-8",
        )

        env = os.environ.copy()
        env["PATH"] = ""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "continuum",
                "run",
                str(scenario_path),
                "--run-id",
                run_id,
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertTrue(run_dir.exists(), "Run directory was not created")

        summary_path = run_dir / "summary.json"
        preflight_path = run_dir / "evidence" / "01-run_postman_collection" / "preflight.json"
        self.assertTrue(summary_path.exists(), "Missing summary.json")
        self.assertTrue(preflight_path.exists(), "Missing preflight evidence")

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["steps"][0]["details"]["error"], "Missing dependency: newman")
        self.assertEqual(summary["failure"]["message"], "Missing dependency: newman")


if __name__ == "__main__":
    unittest.main()
