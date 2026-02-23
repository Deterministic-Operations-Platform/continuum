import json
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

    def test_runtime_retries_flaky_step_and_writes_attempt_dirs(self) -> None:
        run_id = "test-retry-smoke"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        scenario = Scenario(
            name="Retry Smoke",
            rail="test",
            steps=(
                ScenarioStep(
                    name="Flaky",
                    type="test.flaky",
                    with_={},
                    retry={
                        "on": ["failure"],
                        "maxAttempts": 3,
                        "backoff": "fixed",
                        "baseDelayMs": 0,
                        "maxDelayMs": 0,
                        "jitter": 0,
                    },
                ),
            ),
            vars={},
        )

        runtime = DeterministicRuntime(
            plugin_registry=PluginRegistry(plugins=[FlakyPlugin(fail_attempts=2)]),
            evidence_collector=EvidenceCollector(),
        )
        summary = runtime.execute(
            scenario=scenario,
            scenario_source=REPO_ROOT / "tests" / "test_runtime_smoke.py",
            scenario_text="name: Retry Smoke",
            run_id=run_id,
        )

        self.assertEqual(summary["status"], "succeeded")
        self.assertEqual(len(summary["steps"][0]["attempts"]), 3)

        step_root = run_dir / "evidence" / "01-Flaky"
        self.assertTrue((step_root / "attempt-01").exists())
        self.assertTrue((step_root / "attempt-02").exists())
        self.assertTrue((step_root / "attempt-03").exists())


if __name__ == "__main__":
    unittest.main()
