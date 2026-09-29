import json
import unittest
from pathlib import Path
from unittest.mock import patch

from continuum.signing import write_bundle_signature
from continuum.verify import cmd_verify
from tests._tmpdir import make_temp_dir, remove_temp_dir


class VerifyCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir("verify")
        self.addCleanup(lambda: remove_temp_dir(self.root))

    def _make_run(self, run_id: str, policy_ok: bool) -> Path:
        run_dir = self.root / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text(json.dumps({"x": 1}), encoding="utf-8")
        (run_dir / "summary.json").write_text(
            json.dumps({"run_id": run_id, "policy": {"ok": policy_ok, "missing": []}}),
            encoding="utf-8",
        )
        return run_dir

    def test_verify_returns_0_when_policy_and_signature_ok(self) -> None:
        run_id = "v-001"
        run_dir = self._make_run(run_id, policy_ok=True)

        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_MODE": "hmac",
                "CONTINUUM_SIGNING_KEY": "dev-secret-0123456789abcdef-0123456789",
                "CONTINUUM_VERIFY_SIGNATURES": "true",
            },
            clear=True,
        ):
            write_bundle_signature(run_dir)
            code = cmd_verify(run_id=run_id, runs_dir=str(self.root / "runs"))
            self.assertEqual(code, 0)

    def test_verify_returns_2_when_policy_fails(self) -> None:
        run_id = "v-002"
        run_dir = self._make_run(run_id, policy_ok=False)

        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_MODE": "hmac",
                "CONTINUUM_SIGNING_KEY": "dev-secret-0123456789abcdef-0123456789",
            },
        ):
            write_bundle_signature(run_dir)
            code = cmd_verify(run_id=run_id, runs_dir=str(self.root / "runs"))
            self.assertEqual(code, 2)

    def test_verify_returns_2_when_signature_fails(self) -> None:
        run_id = "v-003"
        run_dir = self._make_run(run_id, policy_ok=True)

        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_MODE": "hmac",
                "CONTINUUM_SIGNING_KEY": "dev-secret-0123456789abcdef-0123456789",
            },
        ):
            write_bundle_signature(run_dir)

            # Break signature by changing manifest
            (run_dir / "manifest.json").write_text(json.dumps({"x": 999}), encoding="utf-8")

            code = cmd_verify(run_id=run_id, runs_dir=str(self.root / "runs"))
            self.assertEqual(code, 2)

    def test_signature_verification_can_be_explicitly_disabled_for_unsigned_runs(self) -> None:
        run_id = "v-unsigned"
        self._make_run(run_id, policy_ok=True)

        with patch.dict(
            "os.environ", {"CONTINUUM_VERIFY_SIGNATURES": "false"}, clear=True
        ):
            code = cmd_verify(run_id=run_id, runs_dir=str(self.root / "runs"))
        self.assertEqual(code, 0)

    def test_signature_verification_is_enabled_by_default_for_unsigned_runs(self) -> None:
        run_id = "v-unsigned-required"
        self._make_run(run_id, policy_ok=True)

        with patch.dict(
            "os.environ", {"CONTINUUM_SIGNING_MODE": "unsigned"}, clear=True
        ):
            code = cmd_verify(run_id=run_id, runs_dir=str(self.root / "runs"))
        self.assertEqual(code, 2)

    def test_required_signing_cannot_disable_signature_verification(self) -> None:
        run_id = "v-required"
        self._make_run(run_id, policy_ok=True)

        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_VERIFY_SIGNATURES": "false",
                "CONTINUUM_SIGNING_REQUIRED": "true",
            },
            clear=True,
        ):
            code = cmd_verify(run_id=run_id, runs_dir=str(self.root / "runs"))
        self.assertEqual(code, 2)

    def test_invalid_signature_verification_setting_fails_closed(self) -> None:
        run_id = "v-invalid-setting"
        self._make_run(run_id, policy_ok=True)

        with patch.dict(
            "os.environ", {"CONTINUUM_VERIFY_SIGNATURES": "sometimes"}, clear=True
        ):
            code = cmd_verify(run_id=run_id, runs_dir=str(self.root / "runs"))
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
