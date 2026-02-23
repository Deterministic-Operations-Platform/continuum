import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from continuum.evidence import EvidenceCollector
from continuum.plugins import PluginRegistry, StepResult
from continuum.runtime import DeterministicRuntime
from continuum.scenario import Scenario, ScenarioStep


REPO_ROOT = Path(__file__).resolve().parents[1]


class FlakyPlugin:
    type = "test.flaky"

    def __init__(self, fail_attempts: int):
        self._fail_attempts = fail_attempts
        self._calls = 0

    def run(self, *, step_name: str, step_with: dict, ctx: dict, step_index: int) -> StepResult:
        self._calls += 1
        step_dir = ctx["step_dir"](step_index, step_name)
        marker = ctx["write_json"](step_dir, "attempt.json", {"attempt": self._calls})
        return StepResult(ok=self._calls > self._fail_attempts, details={"attempt": self._calls}, evidence_paths=[marker])


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

    def test_run_executes_always_steps_after_failure(self) -> None:
        run_id = "test-always-run"
        run_dir = REPO_ROOT / "runs" / run_id
        scenario_path = REPO_ROOT / "runs" / "test-always-scenario.yaml"

        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))
        self.addCleanup(lambda: scenario_path.unlink(missing_ok=True))

        scenario_path.write_text(
            """name: always-step-smoke
rail: test
steps:
  - name: Start AppLauncher
    type: applauncher.start
    with:
      command: python
      args: ["-m", "http.server", "8091"]
      cwd: .
  - name: Force health failure
    type: http.health
    with:
      url: http://localhost:1
      timeoutSec: 1
  - name: Stop AppLauncher
    type: applauncher.stop
    always: true
""",
            encoding="utf-8",
        )

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "continuum",
                "run",
                str(scenario_path.relative_to(REPO_ROOT)),
                "--run-id",
                run_id,
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0, "Run should fail due to health check")

        summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(len(summary["steps"]), 3)
        self.assertEqual(summary["steps"][2]["name"], "Stop AppLauncher")
        self.assertTrue(summary["steps"][2]["ok"])
        self.assertTrue((run_dir / "evidence" / "03-Stop_AppLauncher").exists())


if __name__ == "__main__":
    unittest.main()
