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


class ExportStepPlugin:
    type = "test.export"

    def run(self, *, step_name, step_with, ctx, step_index):
        return StepResult(ok=True, details={"step": step_name}, evidence_paths=[], exports={"x": "hello"})


class ConsumeStepPlugin:
    type = "test.consume"

    def run(self, *, step_name, step_with, ctx, step_index):
        if step_with.get("msg") != "hello":
            raise AssertionError(f"Expected templated msg to be 'hello', got {step_with.get('msg')!r}")
        return StepResult(ok=True, details={"msg": step_with.get("msg")}, evidence_paths=[])


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


    def test_runtime_merges_exports_for_later_template_resolution(self) -> None:
        run_id = "test-export-runtime"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        scenario = Scenario(
            name="export-smoke",
            rail="test",
            vars={},
            steps=(
                ScenarioStep(name="Export value", type="test.export", key="01_export_value", with_={}),
                ScenarioStep(name="Consume value", type="test.consume", key="02_consume_value", with_={"msg": "${vars.x}"}),
            ),
        )

        runtime = DeterministicRuntime(
            plugin_registry=PluginRegistry(plugins=[ExportStepPlugin(), ConsumeStepPlugin()]),
            evidence_collector=EvidenceCollector(),
        )

        summary = runtime.execute(
            scenario=scenario,
            scenario_source=REPO_ROOT / "tests" / "test_runtime_smoke.py",
            scenario_text="name: export-smoke",
            run_id=run_id,
        )

        self.assertEqual(summary["status"], "succeeded")
        self.assertEqual(summary["steps"][0]["exports"]["x"], "hello")

        context = json.loads((run_dir / "context.json").read_text(encoding="utf-8"))
        self.assertEqual(context["vars"]["x"], "hello")
        self.assertEqual(context["vars"]["steps"]["01_export_value"]["x"], "hello")

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


if __name__ == "__main__":
    unittest.main()
