import json
import shutil
import unittest
from pathlib import Path

from continuum import DeterministicRuntime, EvidenceCollector, PluginRegistry, Scenario, ScenarioStep, StepResult
from continuum.errors import StepExecutionError

REPO_ROOT = Path(__file__).resolve().parents[1]


class _RecorderPlugin:
    def __init__(self, plugin_type: str, calls: list[str]) -> None:
        self.type = plugin_type
        self.calls = calls

    def run(self, *, step_name, step_with, ctx, step_index):
        self.calls.append(step_name)
        marker = ctx["write_json"](ctx["step_dir"](step_index, step_name), "ran.json", {"name": step_name})
        return StepResult(ok=True, details={"name": step_name}, evidence_paths=[marker])


class _FailPlugin:
    type = "test.fail"

    def run(self, *, step_name, step_with, ctx, step_index):
        raise StepExecutionError("boom")


class _CleanupPlugin:
    type = "test.cleanup"

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    def run(self, *, step_name, step_with, ctx, step_index):
        self.calls.append(step_name)
        marker = ctx["write_json"](ctx["step_dir"](step_index, step_name), "cleanup.json", {"ok": True})
        return StepResult(ok=True, details={"ok": True}, evidence_paths=[marker])


class RuntimeSelectiveExecutionTests(unittest.TestCase):
    def test_from_to_only_runs_middle_steps(self) -> None:
        run_id = "test-select-range"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        calls: list[str] = []
        runtime = DeterministicRuntime(PluginRegistry([_RecorderPlugin("test.recorder", calls)]), EvidenceCollector())
        scenario = Scenario(
            name="range",
            rail="test",
            vars={},
            steps=(
                ScenarioStep(name="one", key="01_one", type="test.recorder"),
                ScenarioStep(name="two", key="run_postman", type="test.recorder"),
                ScenarioStep(name="three", key="verify_mongo", type="test.recorder"),
                ScenarioStep(name="four", key="04_four", type="test.recorder"),
            ),
        )

        summary = runtime.execute(
            scenario=scenario,
            scenario_source=Path("tests/fixture.yaml"),
            scenario_text="name: range",
            run_id=run_id,
            from_selector="run_postman",
            to_selector="verify_mongo",
        )

        self.assertEqual(summary["status"], "succeeded")
        self.assertEqual(calls, ["two", "three"])
        self.assertEqual([step["status"] for step in summary["steps"]], ["skipped", "succeeded", "succeeded", "skipped"])

    def test_only_types_runs_matching_steps(self) -> None:
        run_id = "test-select-only"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        calls: list[str] = []
        runtime = DeterministicRuntime(
            PluginRegistry(
                [
                    _RecorderPlugin("postman.run", calls),
                    _RecorderPlugin("jira.fetch", calls),
                    _RecorderPlugin("mongo.verify", calls),
                ]
            ),
            EvidenceCollector(),
        )
        scenario = Scenario(
            name="types",
            rail="test",
            vars={},
            steps=(
                ScenarioStep(name="pm", key="01_pm", type="postman.run"),
                ScenarioStep(name="jira", key="02_jira", type="jira.fetch"),
                ScenarioStep(name="mongo", key="03_mongo", type="mongo.verify"),
            ),
        )

        summary = runtime.execute(
            scenario=scenario,
            scenario_source=Path("tests/fixture.yaml"),
            scenario_text="name: types",
            run_id=run_id,
            only_selectors=("postman.run", "mongo.verify"),
        )

        self.assertEqual(calls, ["pm", "mongo"])
        self.assertEqual([step["status"] for step in summary["steps"]], ["succeeded", "skipped", "succeeded"])

    def test_skip_and_cleanup_still_runs_after_failure(self) -> None:
        run_id = "test-select-skip-cleanup"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        cleanup_calls: list[str] = []
        runtime = DeterministicRuntime(
            PluginRegistry([_FailPlugin(), _RecorderPlugin("test.recorder", []), _CleanupPlugin(cleanup_calls)]),
            EvidenceCollector(),
        )
        scenario = Scenario(
            name="skip-cleanup",
            rail="test",
            vars={},
            steps=(
                ScenarioStep(name="fails", key="01_fails", type="test.fail"),
                ScenarioStep(name="skipped", key="02_skip", type="test.recorder"),
            ),
            cleanup_steps=(ScenarioStep(name="cleanup", key="03_cleanup", type="test.cleanup"),),
        )

        summary = runtime.execute(
            scenario=scenario,
            scenario_source=Path("tests/fixture.yaml"),
            scenario_text="name: skip-cleanup",
            run_id=run_id,
            skip_selectors=("02",),
        )

        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["steps"][0]["status"], "failed")
        self.assertEqual(summary["steps"][1]["status"], "skipped")
        self.assertEqual(cleanup_calls, ["cleanup"])

        skipped_payload = json.loads((run_dir / "evidence" / "02-skipped" / "skipped.json").read_text(encoding="utf-8"))
        self.assertEqual(skipped_payload["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
