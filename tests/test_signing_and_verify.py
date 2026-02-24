import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from continuum.__main__ import cmd_verify
from continuum.signing import verify_bundle_signature, write_bundle_signature
from tests._tmpdir import make_temp_dir, remove_temp_dir


class SigningAndVerifyTests(unittest.TestCase):
    def test_sign_and_verify_roundtrip(self) -> None:
        root = make_temp_dir("signing-roundtrip")
        self.addCleanup(lambda: remove_temp_dir(root))
        run_dir = root / "runs" / "s-1"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "manifest.json").write_text(json.dumps({"run_id": "s-1"}, indent=2), encoding="utf-8")

        with patch.dict(
            os.environ,
            {"CONTINUUM_SIGNING_KEY": "unit-test-key", "CONTINUUM_SIGNING_KEY_ID": "unit-test"},
            clear=False,
        ):
            payload = write_bundle_signature(run_dir)
            self.assertIsNotNone(payload)
            self.assertTrue((run_dir / "bundle_signature.json").is_file())
            self.assertTrue((run_dir / "manifest.sha256").is_file())
            ok, msg = verify_bundle_signature(run_dir)
            self.assertTrue(ok)
            self.assertEqual(msg, "ok")

    def test_verify_detects_manifest_tamper(self) -> None:
        root = make_temp_dir("signing-tamper")
        self.addCleanup(lambda: remove_temp_dir(root))
        run_dir = root / "runs" / "s-2"
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "manifest.json").write_text(json.dumps({"run_id": "s-2"}, indent=2), encoding="utf-8")

        with patch.dict(os.environ, {"CONTINUUM_SIGNING_KEY": "unit-test-key"}, clear=False):
            write_bundle_signature(run_dir)
            (run_dir / "manifest.json").write_text(json.dumps({"run_id": "s-2", "tampered": True}, indent=2), encoding="utf-8")
            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertEqual(msg, "manifest sha mismatch")

    def test_cmd_verify_exit_code(self) -> None:
        root = make_temp_dir("verify-cmd")
        self.addCleanup(lambda: remove_temp_dir(root))
        runs_dir = root / "runs"
        run_id = "verify-1"
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "manifest.json").write_text(json.dumps({"run_id": run_id}, indent=2), encoding="utf-8")
        (run_dir / "summary.json").write_text(json.dumps({"policy": {"ok": True, "missing": []}}), encoding="utf-8")

        with patch.dict(os.environ, {"CONTINUUM_SIGNING_KEY": "unit-test-key"}, clear=False):
            write_bundle_signature(run_dir)
            self.assertEqual(cmd_verify(run_id=run_id, runs_dir=str(runs_dir)), 0)

            (run_dir / "summary.json").write_text(json.dumps({"policy": {"ok": False, "missing": ["x"]}}), encoding="utf-8")
            self.assertEqual(cmd_verify(run_id=run_id, runs_dir=str(runs_dir)), 2)


if __name__ == "__main__":
    unittest.main()
