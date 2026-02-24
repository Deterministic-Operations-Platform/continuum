import json
import shutil
import unittest
from pathlib import Path

from continuum.evidence import EvidenceCollector
from continuum.plugins import PluginRegistry
from continuum.runtime import DeterministicRuntime
from continuum.scenario import Scenario, ScenarioStep


REPO_ROOT = Path(__file__).resolve().parents[1]


class GatewayDependencyPreflightTests(unittest.TestCase):
    def test_required_gateway_dependency_fails_fast(self) -> None:
        run_id = "test-gateway-preflight-fail"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        scenario = Scenario(
            name="gateway-required",
            rail="test",
            vars={},
            dependencies={
                "gateway": {
                    "endpoint": "http://127.0.0.1:9/health",
                    "required": True,
                    "timeoutSec": 1,
                    "retries": 1,
                }
            },
            steps=(ScenarioStep(name="noop", type="preflight.checklist", key="01_noop", with_={}),),
        )
        runtime = DeterministicRuntime(plugin_registry=PluginRegistry(), evidence_collector=EvidenceCollector())
        summary = runtime.execute(
            scenario=scenario,
            scenario_source=Path(__file__),
            scenario_text="name: gateway-required",
            run_id=run_id,
            cli_vars={"policyFile": "runs/missing-policy.yaml"},
        )

        self.assertEqual(summary["status"], "failed")
        self.assertIn("DEPENDENCY_DOWN: gateway", str(summary.get("failure", {}).get("message", "")))

        gateway_check = json.loads((run_dir / "gateway_check.json").read_text(encoding="utf-8"))
        self.assertEqual(gateway_check["status"], "failed")
        self.assertTrue(gateway_check["checks"])

    def test_optional_gateway_dependency_switches_to_stub_mode(self) -> None:
        run_id = "test-gateway-preflight-stub"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        scenario = Scenario(
            name="gateway-optional",
            rail="test",
            vars={},
            dependencies={
                "gateway": {
                    "endpoint": "http://127.0.0.1:9/health",
                    "required": False,
                    "fallback": "stub",
                    "allowed_modes": ["live", "stub"],
                    "timeoutSec": 1,
                    "retries": 1,
                }
            },
            steps=(ScenarioStep(name="noop", type="preflight.checklist", key="01_noop", with_={}),),
        )
        runtime = DeterministicRuntime(plugin_registry=PluginRegistry(), evidence_collector=EvidenceCollector())
        summary = runtime.execute(
            scenario=scenario,
            scenario_source=Path(__file__),
            scenario_text="name: gateway-optional",
            run_id=run_id,
            cli_vars={"policyFile": "runs/missing-policy.yaml"},
        )

        self.assertEqual(summary["status"], "succeeded")
        self.assertEqual(summary["dependency_preflight"]["status"], "degraded")
        self.assertEqual(summary["dependency_preflight"]["checks"][0]["mode"], "stub")

        context = json.loads((run_dir / "context.json").read_text(encoding="utf-8"))
        self.assertEqual(context["vars"]["dependencies"]["gateway"]["mode"], "stub")


if __name__ == "__main__":
    unittest.main()
