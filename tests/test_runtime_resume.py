import json
import shutil
import unittest
from pathlib import Path

from continuum import DeterministicRuntime, EvidenceCollector, PluginRegistry, Scenario, ScenarioStep, StepResult


REPO_ROOT = Path(__file__).resolve().parents[1]


class _ExportPlugin:
    type = "test.export"

    def run(self, *, step_name, step_with, ctx, step_index):
        value = step_with.get("value", "seed")
        return StepResult(ok=True, details={"value": value}, evidence_paths=[], exports={"token": value})


class _ConsumePlugin:
    type = "test.consume"

    def run(self, *, step_name, step_with, ctx, step_index):
        return StepResult(ok=True, details={"msg": step_with.get("msg")}, evidence_paths=[])


class _FailPlugin:
    type = "test.fail"

    def run(self, *, step_name, step_with, ctx, step_index):
        return StepResult(ok=False, details={"reason": "forced"}, evidence_paths=[])


class RuntimeResumeTests(unittest.TestCase):
    def test_resume_skips_succeeded_and_imports_vars(self) -> None:
        base_run = "test-resume-base-1"
        resumed_run = "test-resume-next-1"
        self.addCleanup(lambda: shutil.rmtree(REPO_ROOT / "runs" / base_run, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(REPO_ROOT / "runs" / resumed_run, ignore_errors=True))

        runtime = DeterministicRuntime(PluginRegistry([_ExportPlugin(), _ConsumePlugin()]), EvidenceCollector())
        scenario = Scenario(
            name="resume-base",
            rail="test",
            vars={},
            steps=(
                ScenarioStep(name="Export", type="test.export", key="run_postman", with_={"value": "alpha"}),
                ScenarioStep(name="Consume", type="test.consume", key="consume", with_={"msg": "${vars.token}"}),
            ),
            cleanup_steps=(),
        )

        base_summary = runtime.execute(
            scenario=scenario,
            scenario_source=Path("tests/fixture.yaml"),
            scenario_text="name: resume-base",
            run_id=base_run,
        )
        self.assertEqual(base_summary["status"], "succeeded")

        resumed_scenario = Scenario(
            name="resume-next",
            rail="test",
            vars={},
            steps=(
                ScenarioStep(name="Export", type="test.export", key="run_postman", with_={"value": "beta"}),
                ScenarioStep(name="Consume", type="test.consume", key="consume", with_={"msg": "${vars.token}"}),
            ),
            cleanup_steps=(),
        )
        resumed_summary = runtime.execute(
            scenario=resumed_scenario,
            scenario_source=Path("tests/fixture.yaml"),
            scenario_text="name: resume-next",
            run_id=resumed_run,
            resume_id=base_run,
        )

        self.assertEqual(resumed_summary["steps"][0]["status"], "skipped")
        self.assertEqual(resumed_summary["steps"][0]["skipReason"], "resume:succeeded")
        self.assertEqual(resumed_summary["steps"][1]["status"], "skipped")

        context = json.loads((REPO_ROOT / "runs" / resumed_run / "context.json").read_text(encoding="utf-8"))
        self.assertEqual(context["vars"]["token"], "alpha")

    def test_resume_with_rerun_reexecutes_selected_step(self) -> None:
        base_run = "test-resume-base-2"
        resumed_run = "test-resume-next-2"
        self.addCleanup(lambda: shutil.rmtree(REPO_ROOT / "runs" / base_run, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(REPO_ROOT / "runs" / resumed_run, ignore_errors=True))

        runtime = DeterministicRuntime(PluginRegistry([_ExportPlugin()]), EvidenceCollector())
        scenario = Scenario(
            name="resume-rerun",
            rail="test",
            vars={},
            steps=(ScenarioStep(name="Export", type="test.export", key="run_postman", with_={"value": "old"}),),
            cleanup_steps=(),
        )
        runtime.execute(scenario=scenario, scenario_source=Path("tests/fixture.yaml"), scenario_text="x", run_id=base_run)

        rerun_scenario = Scenario(
            name="resume-rerun",
            rail="test",
            vars={},
            steps=(ScenarioStep(name="Export", type="test.export", key="run_postman", with_={"value": "new"}),),
            cleanup_steps=(),
        )
        summary = runtime.execute(
            scenario=rerun_scenario,
            scenario_source=Path("tests/fixture.yaml"),
            scenario_text="x",
            run_id=resumed_run,
            resume_id=base_run,
            rerun_selectors=["run_postman"],
        )
        self.assertEqual(summary["steps"][0]["status"], "succeeded")
        self.assertEqual(summary["steps"][0]["exports"]["token"], "new")

    def test_from_failure_starts_at_first_failed_step(self) -> None:
        base_run = "test-resume-base-3"
        resumed_run = "test-resume-next-3"
        self.addCleanup(lambda: shutil.rmtree(REPO_ROOT / "runs" / base_run, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(REPO_ROOT / "runs" / resumed_run, ignore_errors=True))

        runtime = DeterministicRuntime(PluginRegistry([_ExportPlugin(), _FailPlugin()]), EvidenceCollector())
        scenario = Scenario(
            name="resume-from-failure",
            rail="test",
            vars={},
            steps=(
                ScenarioStep(name="ok", type="test.export", key="run_postman", with_={"value": "one"}),
                ScenarioStep(name="bad", type="test.fail", key="mongo.verify", with_={}),
            ),
            cleanup_steps=(),
        )
        base_summary = runtime.execute(scenario=scenario, scenario_source=Path("tests/fixture.yaml"), scenario_text="x", run_id=base_run)
        self.assertEqual(base_summary["status"], "failed")

        resumed_summary = runtime.execute(
            scenario=scenario,
            scenario_source=Path("tests/fixture.yaml"),
            scenario_text="x",
            run_id=resumed_run,
            resume_id=base_run,
            from_failure=True,
        )
        self.assertEqual(resumed_summary["steps"][0]["status"], "skipped")
        self.assertEqual(resumed_summary["steps"][0]["skipReason"], "control-flow")
        self.assertEqual(resumed_summary["steps"][1]["status"], "failed")
        self.assertEqual(resumed_summary["steps"][1]["index"], 1)


if __name__ == "__main__":
    unittest.main()
