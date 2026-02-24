import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from continuum.plugins import PluginRegistry
from continuum.runtime import build_plan, validate_scenario
from continuum.scenario import load_scenario


class ValidateAndPlanTests(unittest.TestCase):
    def test_validate_fails_on_unknown_template_var(self) -> None:
        scenario = load_scenario("scenarios/fednow-return-of-funds.yaml")
        scenario = scenario.__class__(
            name=scenario.name,
            rail=scenario.rail,
            vars=scenario.vars,
            steps=scenario.steps[:1]
            + (
                scenario.steps[1].__class__(
                    name="bad template",
                    type="http.health",
                    key="x",
                    with_={"url": "${vars.missingValue}"},
                    publish={},
                ),
            ),
            cleanup_steps=(),
        )
        errors, _ = validate_scenario(scenario, plugin_registry=PluginRegistry(), env={})
        self.assertTrue(any("unknown template keys" in err for err in errors))

    def test_validate_fails_when_newman_missing_for_postman_step(self) -> None:
        scenario = load_scenario("scenarios/fednow-return-of-funds.yaml")
        with patch("continuum.runtime.resolve_newman_executable", return_value=None):
            errors, _ = validate_scenario(scenario, plugin_registry=PluginRegistry(), env={})
        self.assertTrue(any("missing dependency 'newman'" in err for err in errors))

    def test_plan_resolves_jira_attach_globs_deterministically(self) -> None:
        scenario = load_scenario("scenarios/fednow-return-of-funds.yaml")
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            f1 = run_dir / "evidence" / "03-run_postman" / "newman-report.html"
            f2 = run_dir / "evidence" / "04-verify_mongo" / "assertions.json"
            f1.parent.mkdir(parents=True)
            f2.parent.mkdir(parents=True)
            f1.write_text("x", encoding="utf-8")
            f2.write_text("{}", encoding="utf-8")
            plan = build_plan(scenario, run_id="demo", run_dir=run_dir, env={}, vars=scenario.vars)
            attach_step = [s for s in plan["steps"] if s["type"] == "jira.attach"][0]
            self.assertEqual(attach_step["attach_files"], sorted(attach_step["attach_files"]))
            self.assertIn(str(f1), attach_step["attach_files"])
            self.assertIn(str(f2), attach_step["attach_files"])


if __name__ == "__main__":
    unittest.main()
