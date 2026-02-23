import json
import shutil
import unittest
from pathlib import Path

from continuum.evidence import EvidenceCollector
from continuum.plugins import MongoVerifyPlugin, PluginRegistry, PostmanRunPlugin
from continuum.runtime import DeterministicRuntime
from continuum.scenario import Scenario, ScenarioStep


REPO_ROOT = Path(__file__).resolve().parents[1]


class TraceCorrelationTests(unittest.TestCase):
    def test_runtime_generates_trace_id_and_writes_trace_artifact(self) -> None:
        run_id = "test-trace-generated"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        scenario = Scenario(
            name="trace-smoke",
            rail="test",
            vars={},
            steps=(ScenarioStep(name="noop", type="mongo.verify", key="01_noop", with_={}),),
        )
        runtime = DeterministicRuntime(plugin_registry=PluginRegistry(), evidence_collector=EvidenceCollector())
        summary = runtime.execute(
            scenario=scenario,
            scenario_source=REPO_ROOT / "tests" / "test_trace_correlation.py",
            scenario_text="name: trace-smoke",
            run_id=run_id,
        )

        self.assertTrue(summary["traceId"].startswith(f"{run_id}-"))
        trace_payload = json.loads((run_dir / "trace.json").read_text(encoding="utf-8"))
        self.assertEqual(trace_payload["traceId"], summary["traceId"])
        mongo_assertions = json.loads(
            (run_dir / "evidence" / "01-noop" / "assertions.json").read_text(encoding="utf-8")
        )
        self.assertIn("traceId", mongo_assertions)

    def test_explicit_trace_id_is_preserved_and_plugins_receive_it(self) -> None:
        run_id = "test-trace-explicit"
        run_dir = REPO_ROOT / "runs" / run_id
        self.addCleanup(lambda: shutil.rmtree(run_dir, ignore_errors=True))

        scenario = Scenario(
            name="trace-explicit",
            rail="test",
            vars={"traceId": "trace-from-scenario"},
            steps=(
                ScenarioStep(name="postman", type="postman.run", key="01_postman", with_={}),
            ),
        )
        runtime = DeterministicRuntime(
            plugin_registry=PluginRegistry(plugins=[PostmanRunPlugin(), MongoVerifyPlugin()]),
            evidence_collector=EvidenceCollector(),
        )
        summary = runtime.execute(
            scenario=scenario,
            scenario_source=REPO_ROOT / "tests" / "test_trace_correlation.py",
            scenario_text="name: trace-explicit",
            run_id=run_id,
        )

        self.assertEqual(summary["traceId"], "trace-from-scenario")
        postman_missing = json.loads(
            (run_dir / "evidence" / "01-postman" / "missing-dependency.json").read_text(encoding="utf-8")
        )
        self.assertEqual(postman_missing["envVar"]["traceId"], "trace-from-scenario")


if __name__ == "__main__":
    unittest.main()
