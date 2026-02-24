import unittest

from tests._tmpdir import make_temp_dir, remove_temp_dir
from continuum.policy import evaluate_policy


class PolicyGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir("policy")
        self.addCleanup(lambda: remove_temp_dir(self.root))

    def test_policy_passes_when_required_files_exist(self) -> None:
        run_dir = self.root / "runs" / "r1"
        run_dir.mkdir(parents=True)

        # Minimal bundle
        (run_dir / "summary.json").write_text("{}", encoding="utf-8")
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
        (run_dir / "report.html").write_text("<h1>ok</h1>", encoding="utf-8")
        (run_dir / "evidence" / "01-verify" / "assertions.json").parent.mkdir(parents=True, exist_ok=True)
        (run_dir / "evidence" / "01-verify" / "assertions.json").write_text("{}", encoding="utf-8")

        summary: dict = {"run_id": "r1", "status": "succeeded"}
        policy = {
            "requires": {
                "files": [
                    "summary.json",
                    "manifest.json",
                    "report.html",
                    "evidence/**/assertions.json",
                ]
            }
        }

        result = evaluate_policy(run_dir=run_dir, summary=summary, policy=policy)
        self.assertTrue(result.ok)
        self.assertEqual(result.missing, [])
        self.assertTrue(summary["policy"]["ok"])
        self.assertEqual(summary["policy"]["missing"], [])

    def test_policy_fails_when_required_files_missing(self) -> None:
        run_dir = self.root / "runs" / "r2"
        run_dir.mkdir(parents=True)

        (run_dir / "summary.json").write_text("{}", encoding="utf-8")
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")

        summary: dict = {"run_id": "r2", "status": "succeeded"}
        policy = {
            "requires": {
                "files": [
                    "report.html",  # missing
                    "evidence/**/newman-report.html",  # missing
                ]
            }
        }

        result = evaluate_policy(run_dir=run_dir, summary=summary, policy=policy)

        self.assertFalse(result.ok)
        self.assertIn("report.html", result.missing)
        self.assertIn("evidence/**/newman-report.html", result.missing)

        self.assertIn("policy", summary)
        self.assertFalse(summary["policy"]["ok"])
        self.assertGreaterEqual(len(summary["policy"]["missing"]), 1)

    def test_policy_can_require_signature_file(self) -> None:
        run_dir = self.root / "runs" / "r3"
        run_dir.mkdir(parents=True)

        (run_dir / "summary.json").write_text("{}", encoding="utf-8")
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")

        summary: dict = {"run_id": "r3", "status": "succeeded"}
        policy = {"requires": {"signature": True, "files": ["summary.json", "manifest.json"]}}

        result = evaluate_policy(run_dir=run_dir, summary=summary, policy=policy)
        self.assertFalse(result.ok)
        self.assertIn("bundle_signature.json", result.missing)


if __name__ == "__main__":
    unittest.main()
