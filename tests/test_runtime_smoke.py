import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

from continuum.evidence import EvidenceCollector
from continuum.plugins import PluginRegistry, StepResult, resolve_attach_files
from continuum.runtime import DeterministicRuntime
from continuum.scenario import Scenario, ScenarioStep


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



    def test_services_resume_reuse_and_restart_when_pid_missing(self) -> None:
        first_run = "test-services-run-1"
        second_run = "test-services-run-2"
        third_run = "test-services-run-3"
        session_registry = REPO_ROOT / "runs" / ".service-sessions.json"

        for run_id in (first_run, second_run, third_run):
            self.addCleanup(lambda rid=run_id: shutil.rmtree(REPO_ROOT / "runs" / rid, ignore_errors=True))
        self.addCleanup(lambda: session_registry.unlink(missing_ok=True))

        scenario = Scenario(
            name="services-smoke",
            rail="test",
            vars={},
            services={
                "appl": {
                    "type": "applauncher",
                    "session": "smoke-svc",
                    "command": sys.executable,
                    "args": ["-m", "http.server", "8123"],
                    "cwd": ".",
                    "healthUrl": "http://127.0.0.1:8123",
                    "verifyTimeoutSec": 5,
                    "reuse": True,
                }
            },
            steps=(
                ScenarioStep(name="noop", type="jira.comment", key="01_noop", with_={}),
            ),
        )

        runtime = DeterministicRuntime(plugin_registry=PluginRegistry(), evidence_collector=EvidenceCollector())

        summary1 = runtime.execute(
            scenario=scenario,
            scenario_source=REPO_ROOT / "tests" / "test_runtime_smoke.py",
            scenario_text="name: services-smoke",
            run_id=first_run,
        )
        first_state = summary1["services"]["appl"]
        self.assertFalse(first_state["reused"])
        first_pid = int(first_state["pid"])

        summary2 = runtime.execute(
            scenario=scenario,
            scenario_source=REPO_ROOT / "tests" / "test_runtime_smoke.py",
            scenario_text="name: services-smoke",
            run_id=second_run,
            resume_run_id=first_run,
        )
        second_state = summary2["services"]["appl"]
        self.assertTrue(second_state["reused"])
        self.assertEqual(int(second_state["pid"]), first_pid)

        os.kill(first_pid, 9)
        time.sleep(0.2)

        summary3 = runtime.execute(
            scenario=scenario,
            scenario_source=REPO_ROOT / "tests" / "test_runtime_smoke.py",
            scenario_text="name: services-smoke",
            run_id=third_run,
            resume_run_id=second_run,
        )
        third_state = summary3["services"]["appl"]
        self.assertFalse(third_state["reused"])
        self.assertNotEqual(int(third_state["pid"]), first_pid)

        third_pid = int(third_state["pid"])
        os.kill(third_pid, 9)

        verify_path = REPO_ROOT / "runs" / second_run / "evidence" / "00-services" / "appl" / "verify.json"
        self.assertTrue(verify_path.exists())

    def test_resolve_attach_files_supports_globs_step_dirs_and_bundle(self) -> None:
        run_dir = REPO_ROOT / "runs" / "test-resolve-attach-files"
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        postman_dir = run_dir / "evidence" / "03-run_postman"
        mongo_dir = run_dir / "evidence" / "04-verify_mongo"
        postman_dir.mkdir(parents=True, exist_ok=True)
        mongo_dir.mkdir(parents=True, exist_ok=True)

        (postman_dir / "newman-report.html").write_text("report", encoding="utf-8")
        (mongo_dir / "assertions.json").write_text("{}", encoding="utf-8")

        for bundle_file in ("scenario.yaml", "context.json", "summary.json", "manifest.json"):
            (run_dir / bundle_file).write_text("{}", encoding="utf-8")

        files = resolve_attach_files(
            {
                "globs": [
                    str(run_dir / "evidence" / "**" / "newman-report.html"),
                    str(run_dir / "evidence" / "**" / "assertions.json"),
                ],
                "fromSteps": ["Run Postman", "verify mongo"],
                "includeRunBundle": True,
                "recursive": True,
                "maxFiles": 10,
            },
            str(run_dir),
        )

        expected = sorted(
            {
                str(postman_dir / "newman-report.html"),
                str(mongo_dir / "assertions.json"),
                str(run_dir / "scenario.yaml"),
                str(run_dir / "context.json"),
                str(run_dir / "summary.json"),
                str(run_dir / "manifest.json"),
            }
        )
        self.assertEqual(files, expected)

        capped_files = resolve_attach_files(
            {
                "globs": [str(run_dir / "evidence" / "**" / "*.json")],
                "includeRunBundle": True,
                "maxFiles": 2,
            },
            str(run_dir),
        )
        self.assertEqual(len(capped_files), 2)
        self.assertEqual(capped_files, sorted(capped_files))


if __name__ == "__main__":
    unittest.main()
