import json
import shutil
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from continuum import DeterministicRuntime, EvidenceCollector, PluginRegistry, Scenario, ScenarioStep, StepResult
from continuum.errors import StepExecutionError


class _FlakyPlugin:
    type = "test.flaky"

    def __init__(self) -> None:
        self.calls = 0

    def run(self, *, step_name, step_with, ctx, step_index):
        self.calls += 1
        if self.calls == 1:
            raise StepExecutionError("transient")
        return StepResult(ok=True, details={"token": "abc-123"}, evidence_paths=[])


class _ReadVarPlugin:
    type = "test.read_var"

    def run(self, *, step_name, step_with, ctx, step_index):
        return StepResult(ok=True, details={"seen": ctx["vars"].get("token")}, evidence_paths=[])


class _AlwaysFailPlugin:
    type = "test.fail"

    def run(self, *, step_name, step_with, ctx, step_index):
        raise StepExecutionError("boom")


class _CleanupPlugin:
    type = "test.cleanup"

    def run(self, *, step_name, step_with, ctx, step_index):
        ctx["vars"]["cleaned"] = True
        return StepResult(ok=True, details={"cleaned": True}, evidence_paths=[])


class RuntimeProductionFeaturesTests(unittest.TestCase):
    def test_retries_and_publish_to_vars(self) -> None:
        run_id = "test-runtime-features-1"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        flaky = _FlakyPlugin()
        runtime = DeterministicRuntime(
            plugin_registry=PluginRegistry([flaky, _ReadVarPlugin()]), evidence_collector=EvidenceCollector()
        )
        scenario = Scenario(
            name="feature-test",
            rail="fednow",
            vars={},
            steps=(
                ScenarioStep(
                    name="flaky",
                    type="test.flaky",
                    with_={"retries": 1, "backoffMs": 1},
                    publish={"token": "$.details.token"},
                ),
                ScenarioStep(name="consume", type="test.read_var", with_={"value": "${vars.token}"}, publish={}),
            ),
            cleanup_steps=(),
        )

        summary = runtime.execute(
            scenario=scenario,
            scenario_source=Path("tests/fixture.yaml"),
            scenario_text="name: feature-test",
            run_id=run_id,
        )

        self.assertEqual(summary["status"], "succeeded")
        self.assertEqual(len(summary["steps"][0]["attempts"]), 2)
        self.assertEqual(summary["steps"][0]["publish"]["token"], "abc-123")
        self.assertEqual(summary["steps"][1]["details"]["seen"], "abc-123")

    def test_cleanup_steps_run_after_failure(self) -> None:
        run_id = "test-runtime-features-2"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        runtime = DeterministicRuntime(
            plugin_registry=PluginRegistry([_AlwaysFailPlugin(), _CleanupPlugin()]), evidence_collector=EvidenceCollector()
        )
        scenario = Scenario(
            name="cleanup-test",
            rail="fednow",
            vars={},
            steps=(ScenarioStep(name="fail", type="test.fail", with_={}, publish={}),),
            cleanup_steps=(ScenarioStep(name="cleanup", type="test.cleanup", with_={}, publish={}),),
        )

        summary = runtime.execute(
            scenario=scenario,
            scenario_source=Path("tests/fixture.yaml"),
            scenario_text="name: cleanup-test",
            run_id=run_id,
        )

        self.assertEqual(summary["status"], "failed")
        self.assertEqual(len(summary["cleanup_steps"]), 1)
        self.assertTrue(summary["cleanup_steps"][0]["ok"])

        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.assertIn("tooling", manifest)
        self.assertIn("artifacts", manifest)
        self.assertTrue(any(item["path"].endswith("summary.json") for item in manifest["artifacts"]))


if __name__ == "__main__":
    unittest.main()
