import unittest
from pathlib import Path
import shutil

from continuum.errors import ScenarioValidationError
from continuum.scenario import load_scenario


class ScenarioSchemaTests(unittest.TestCase):
    def _write_scenario(self, run_id: str, filename: str, payload: str) -> Path:
        root = Path("runs") / run_id
        root.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(root, ignore_errors=True))
        scenario_path = root / filename
        scenario_path.write_text(payload, encoding="utf-8")
        return scenario_path

    def test_canonical_schema_supports_key_and_id_alias(self) -> None:
        payload = """name: schema-check
rail: test
vars:
  hello: world
services:
  appl:
    type: applauncher
    command: python
    args: ["-m", "http.server", "8129"]
policy:
  requires:
    signature: true
    files:
      - summary.json
      - report.html
steps:
  - name: First
    key: first_key
    type: jira.fetch
  - name: Second
    id: second_id
    type: jira.comment
    dependsOn: [first_key]
    with:
      body: ok
cleanup_steps:
  - name: Cleanup
    type: jira.comment
"""
        scenario_path = self._write_scenario("schema-test-canonical", "scenario.yaml", payload)
        scenario = load_scenario(scenario_path)

        self.assertEqual(scenario.steps[0].key, "first_key")
        self.assertEqual(scenario.steps[1].key, "second_id")
        self.assertEqual(scenario.steps[1].depends_on, ("first_key",))
        self.assertIn("appl", scenario.services)
        self.assertTrue(scenario.policy.get("requires", {}).get("signature"))

    def test_legacy_short_action_schema_is_rejected(self) -> None:
        payload = """name: legacy
rail: test
steps:
  - send:
      via: transport-postman
      requestRef: cam29
"""
        scenario_path = self._write_scenario("schema-test-legacy", "legacy.yaml", payload)
        with self.assertRaises(ScenarioValidationError):
            load_scenario(scenario_path)


if __name__ == "__main__":
    unittest.main()
