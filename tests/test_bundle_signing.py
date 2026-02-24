import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._tmpdir import make_temp_dir, remove_temp_dir
from continuum.signing import write_bundle_signature, verify_bundle_signature


class BundleSigningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir("signing")
        self.addCleanup(lambda: remove_temp_dir(self.root))

    def test_write_and_verify_signature_ok(self) -> None:
        run_dir = self.root / "runs" / "sig-001"
        run_dir.mkdir(parents=True)

        (run_dir / "manifest.json").write_text(json.dumps({"a": 1}), encoding="utf-8")

        with patch.dict("os.environ", {"CONTINUUM_SIGNING_KEY": "dev-secret", "CONTINUUM_SIGNING_KEY_ID": "dev"}):
            payload = write_bundle_signature(run_dir)
            self.assertIsNotNone(payload)

            sig_path = run_dir / "bundle_signature.json"
            self.assertTrue(sig_path.is_file())

            ok, msg = verify_bundle_signature(run_dir)
            self.assertTrue(ok, msg)
            self.assertEqual(msg, "ok")

    def test_signature_fails_if_manifest_changes(self) -> None:
        run_dir = self.root / "runs" / "sig-002"
        run_dir.mkdir(parents=True)

        manifest = run_dir / "manifest.json"
        manifest.write_text(json.dumps({"a": 1}), encoding="utf-8")

        with patch.dict("os.environ", {"CONTINUUM_SIGNING_KEY": "dev-secret"}):
            write_bundle_signature(run_dir)

            # mutate manifest after signing
            manifest.write_text(json.dumps({"a": 2}), encoding="utf-8")

            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertIn("mismatch", msg.lower())

    def test_verify_fails_if_key_missing(self) -> None:
        run_dir = self.root / "runs" / "sig-003"
        run_dir.mkdir(parents=True)

        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
        (run_dir / "bundle_signature.json").write_text("{}", encoding="utf-8")

        with patch.dict("os.environ", {}, clear=True):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertIn("signing key", msg.lower())


if __name__ == "__main__":
    unittest.main()
