import shutil
import time
import unittest
from pathlib import Path

from continuum import DeterministicRuntime, EvidenceCollector, PluginRegistry, Scenario, ScenarioStep, StepResult
from continuum.errors import ScenarioValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]


class _SleepPlugin:
    type = "test.sleep"

    def run(self, *, step_name, step_with, ctx, step_index):
        time.sleep(float(step_with.get("seconds", 0.1)))
        marker = ctx["write_json"](ctx["step_dir"](step_index, step_name), "done.json", {"ok": True})
        return StepResult(ok=True, details={"name": step_name}, evidence_paths=[marker])


class RuntimeParallelTests(unittest.TestCase):
    def test_parallel_steps_run_concurrently_with_stable_output_order(self) -> None:
        run_id = "test-parallel-smoke"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        scenario = Scenario(
            name="parallel",
            rail="test",
            vars={},
            steps=(
                ScenarioStep(name="a", key="a", type="test.sleep", with_={"seconds": 0.5}, depends_on=()),
                ScenarioStep(name="b", key="b", type="test.sleep", with_={"seconds": 0.5}, depends_on=()),
            ),
        )

        runtime = DeterministicRuntime(PluginRegistry([_SleepPlugin()]), EvidenceCollector())
        started = time.perf_counter()
        summary = runtime.execute(
            scenario=scenario,
            scenario_source=Path("tests/fixture.yaml"),
            scenario_text="name: parallel",
            run_id=run_id,
            max_parallel=4,
        )
        elapsed = time.perf_counter() - started

        self.assertLess(elapsed, 1.0)
        self.assertEqual([s["key"] for s in summary["steps"]], ["a", "b"])
        self.assertTrue((run_dir / "evidence" / "01-a").exists())
        self.assertTrue((run_dir / "evidence" / "02-b").exists())

    def test_cycle_detection_fails(self) -> None:
        scenario = Scenario(
            name="cycle",
            rail="test",
            vars={},
            steps=(
                ScenarioStep(name="A", key="A", type="test.sleep", with_={}, depends_on=("B",)),
                ScenarioStep(name="B", key="B", type="test.sleep", with_={}, depends_on=("A",)),
            ),
        )
        runtime = DeterministicRuntime(PluginRegistry([_SleepPlugin()]), EvidenceCollector())
        with self.assertRaises(ScenarioValidationError):
            runtime.execute(
                scenario=scenario,
                scenario_source=Path("tests/fixture.yaml"),
                scenario_text="name: cycle",
                run_id="test-cycle",
            )


if __name__ == "__main__":
    unittest.main()
