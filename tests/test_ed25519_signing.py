import json
import unittest
from unittest.mock import patch

from tests._tmpdir import make_temp_dir, remove_temp_dir
from continuum.signing import keygen_ed25519, write_bundle_signature, verify_bundle_signature


class Ed25519SigningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir("ed25519")
        self.addCleanup(lambda: remove_temp_dir(self.root))

    def test_ed25519_keyless_verify_succeeds_when_bundle_includes_public_key(self) -> None:
        run_dir = self.root / "runs" / "ed-001"
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text(json.dumps({"x": 1}), encoding="utf-8")

        priv_b64, _ = keygen_ed25519()
        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_MODE": "ed25519",
                "CONTINUUM_ED25519_PRIVATE_KEY_B64": priv_b64,
                "CONTINUUM_INCLUDE_PUBLIC_KEY_IN_BUNDLE": "1",
                "CONTINUUM_SIGNING_KEY_ID": "test-key",
            },
            clear=False,
        ):
            payload = write_bundle_signature(run_dir)
            self.assertIsNotNone(payload)
            self.assertEqual(payload["algorithm"], "ED25519(manifest_sha256)")

        with patch.dict("os.environ", {}, clear=True):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertTrue(ok, msg)

    def test_ed25519_verify_requires_public_key_if_not_embedded(self) -> None:
        run_dir = self.root / "runs" / "ed-002"
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text(json.dumps({"x": 2}), encoding="utf-8")

        priv_b64, pub_b64 = keygen_ed25519()
        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_MODE": "ed25519",
                "CONTINUUM_ED25519_PRIVATE_KEY_B64": priv_b64,
                "CONTINUUM_INCLUDE_PUBLIC_KEY_IN_BUNDLE": "0",
            },
            clear=False,
        ):
            write_bundle_signature(run_dir)

        with patch.dict("os.environ", {}, clear=True):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertIn("public key", msg.lower())

        with patch.dict("os.environ", {"CONTINUUM_ED25519_PUBLIC_KEY_B64": pub_b64}, clear=True):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertTrue(ok, msg)

    def test_ed25519_detects_manifest_tampering(self) -> None:
        run_dir = self.root / "runs" / "ed-003"
        run_dir.mkdir(parents=True)
        manifest = run_dir / "manifest.json"
        manifest.write_text(json.dumps({"x": 3}), encoding="utf-8")

        priv_b64, _ = keygen_ed25519()
        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_MODE": "ed25519",
                "CONTINUUM_ED25519_PRIVATE_KEY_B64": priv_b64,
                "CONTINUUM_INCLUDE_PUBLIC_KEY_IN_BUNDLE": "1",
            },
            clear=False,
        ):
            write_bundle_signature(run_dir)

        manifest.write_text(json.dumps({"x": 999}), encoding="utf-8")
        with patch.dict("os.environ", {}, clear=True):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertIn("mismatch", msg.lower())


if __name__ == "__main__":
    unittest.main()
