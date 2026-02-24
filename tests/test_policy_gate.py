import json
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch

from continuum import DeterministicRuntime, EvidenceCollector, PluginRegistry, Scenario, ScenarioStep, StepResult


REPO_ROOT = Path(__file__).resolve().parents[1]


class _NoopPostmanPlugin:
    type = "postman.run"

    def run(self, *, step_name, step_with, ctx, step_index):
        return StepResult(ok=True, details={"ok": True}, evidence_paths=[])


class _NoopPlugin:
    type = "test.noop"

    def run(self, *, step_name, step_with, ctx, step_index):
        marker = ctx["write_json"](ctx["step_dir"](step_index, step_name), "noop.json", {"ok": True})
        return StepResult(ok=True, details={"ok": True}, evidence_paths=[marker])


class PolicyGateTests(unittest.TestCase):
    def test_policy_gate_fails_when_required_postman_evidence_missing(self) -> None:
        run_id = "test-policy-postman-missing"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        scenario = Scenario(
            name="policy-postman",
            rail="test",
            vars={},
            steps=(ScenarioStep(name="postman", key="run_postman", type="postman.run", with_={"collection": "missing.json"}),),
            cleanup_steps=(),
        )
        runtime = DeterministicRuntime(plugin_registry=PluginRegistry([_NoopPostmanPlugin()]), evidence_collector=EvidenceCollector())
        summary = runtime.execute(
            scenario=scenario,
            scenario_source=Path("tests/fixture.yaml"),
            scenario_text="name: policy-postman",
            run_id=run_id,
        )

        self.assertEqual(summary["status"], "failed")
        self.assertIn("Policy gate (after execution) failed", summary["failure"]["message"])
        self.assertTrue(any("postman-report" in str(item) for item in summary["policy"]["post"]["violations"]))
        self.assertTrue((run_dir / "report.html").exists())

    def test_policy_gate_fails_before_execution_when_policy_invalid(self) -> None:
        run_id = "test-policy-pre-invalid"
        run_dir = REPO_ROOT / "runs" / run_id
        bad_policy_path = REPO_ROOT / "runs" / "test-bad-policy.yaml"
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))
        self.addCleanup(lambda: bad_policy_path.unlink(missing_ok=True))

        bad_policy_path.parent.mkdir(parents=True, exist_ok=True)
        bad_policy_path.write_text(
            "name: bad-policy\nrequired_evidence: invalid\n",
            encoding="utf-8",
        )

        scenario = Scenario(
            name="policy-pre",
            rail="test",
            vars={"policyFile": str(bad_policy_path)},
            steps=(ScenarioStep(name="noop", key="01_noop", type="test.noop", with_={}),),
            cleanup_steps=(),
        )
        runtime = DeterministicRuntime(plugin_registry=PluginRegistry([_NoopPlugin()]), evidence_collector=EvidenceCollector())
        summary = runtime.execute(
            scenario=scenario,
            scenario_source=Path("tests/fixture.yaml"),
            scenario_text="name: policy-pre",
            run_id=run_id,
        )

        self.assertEqual(summary["status"], "failed")
        self.assertIn("Policy gate (before execution) failed", summary["failure"]["message"])
        self.assertEqual(summary["steps"], [])

        persisted = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(persisted["status"], "failed")
        self.assertIn("policy.required_evidence", persisted["failure"]["message"])

    def test_scenario_policy_requires_files_and_marks_run_failed(self) -> None:
        run_id = "test-scenario-policy-missing"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        scenario = Scenario(
            name="policy-scenario",
            rail="test",
            vars={},
            policy={
                "requires": {
                    "files": [
                        "summary.json",
                        "manifest.json",
                        "report.html",
                        "evidence/**/missing-required.json",
                    ]
                }
            },
            steps=(ScenarioStep(name="noop", key="01_noop", type="test.noop", with_={}),),
            cleanup_steps=(),
        )
        runtime = DeterministicRuntime(plugin_registry=PluginRegistry([_NoopPlugin()]), evidence_collector=EvidenceCollector())
        summary = runtime.execute(
            scenario=scenario,
            scenario_source=Path("tests/fixture.yaml"),
            scenario_text="name: policy-scenario",
            run_id=run_id,
        )

        self.assertEqual(summary["status"], "failed")
        self.assertFalse(summary["policy"]["ok"])
        self.assertIn("evidence/**/missing-required.json", summary["policy"]["missing"])
        self.assertIn("Policy gate failed", summary["failure"]["message"])

    def test_scenario_policy_can_require_signature(self) -> None:
        run_id = "test-scenario-policy-signature"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        scenario = Scenario(
            name="policy-signature",
            rail="test",
            vars={},
            policy={"requires": {"signature": True, "files": ["summary.json", "manifest.json", "report.html"]}},
            steps=(ScenarioStep(name="noop", key="01_noop", type="test.noop", with_={}),),
            cleanup_steps=(),
        )
        runtime = DeterministicRuntime(plugin_registry=PluginRegistry([_NoopPlugin()]), evidence_collector=EvidenceCollector())
        with patch.dict(os.environ, {"CONTINUUM_SIGNING_KEY": "", "CONTINUUM_BUNDLE_HMAC_KEY": ""}, clear=False):
            summary = runtime.execute(
                scenario=scenario,
                scenario_source=Path("tests/fixture.yaml"),
                scenario_text="name: policy-signature",
                run_id=run_id,
            )

        self.assertEqual(summary["status"], "failed")
        self.assertIn("bundle_signature.json", summary["policy"]["missing"])


if __name__ == "__main__":
    unittest.main()
