import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

from continuum.signing import (
    generate_ed25519_keypair,
    verify_bundle_signature,
    write_bundle_signature,
)
from tests._tmpdir import make_temp_dir, remove_temp_dir


class BundleSigningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir("signing")
        self.addCleanup(lambda: remove_temp_dir(self.root))

    def test_write_and_verify_signature_ok(self) -> None:
        run_dir = self.root / "runs" / "sig-001"
        run_dir.mkdir(parents=True)

        (run_dir / "manifest.json").write_text(json.dumps({"a": 1}), encoding="utf-8")

        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_MODE": "hmac",
                "CONTINUUM_SIGNING_KEY": "dev-secret-0123456789abcdef-0123456789",
                "CONTINUUM_SIGNING_KEY_ID": "dev",
            },
            clear=True,
        ):
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

        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_MODE": "hmac",
                "CONTINUUM_SIGNING_KEY": "dev-secret-0123456789abcdef-0123456789",
            },
            clear=True,
        ):
            write_bundle_signature(run_dir)

            # mutate manifest after signing
            manifest.write_text(json.dumps({"a": 2}), encoding="utf-8")

            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertIn("mismatch", msg.lower())

    def test_hmac_signature_binds_key_id_and_created_at(self) -> None:
        run_dir = self.root / "runs" / "sig-bound-fields"
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")

        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_MODE": "hmac",
                "CONTINUUM_SIGNING_KEY": "dev-secret-0123456789abcdef-0123456789",
                "CONTINUUM_SIGNING_KEY_ID": "key-a",
            },
            clear=True,
        ):
            write_bundle_signature(run_dir)

        sig_path = run_dir / "bundle_signature.json"
        original = json.loads(sig_path.read_text(encoding="utf-8"))
        with patch.dict(
            "os.environ",
            {"CONTINUUM_SIGNING_KEY": "dev-secret-0123456789abcdef-0123456789"},
            clear=True,
        ):
            for field, value in (
                ("keyId", "key-b"),
                ("createdAt", "2000-01-01T00:00:00Z"),
            ):
                tampered = {**original, field: value}
                sig_path.write_text(json.dumps(tampered), encoding="utf-8")
                ok, message = verify_bundle_signature(run_dir)
                self.assertFalse(ok)
                self.assertIn("mismatch", message)

    def test_legacy_hmac_signature_remains_verifiable(self) -> None:
        run_dir = self.root / "runs" / "sig-legacy-hmac"
        run_dir.mkdir(parents=True)
        manifest = run_dir / "manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        manifest_sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
        signature = hmac.new(
            b"legacy-secret", manifest_sha.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        (run_dir / "bundle_signature.json").write_text(
            json.dumps(
                {
                    "algorithm": "HMAC-SHA256(manifest_sha256)",
                    "manifest_sha256": manifest_sha,
                    "signature": signature,
                    "createdAt": "2026-01-01T00:00:00Z",
                    "keyId": "legacy",
                }
            ),
            encoding="utf-8",
        )

        with patch.dict(
            "os.environ", {"CONTINUUM_SIGNING_KEY": "legacy-secret"}, clear=True
        ):
            ok, message = verify_bundle_signature(run_dir)
            self.assertTrue(ok, message)

    def test_verify_fails_if_key_missing(self) -> None:
        run_dir = self.root / "runs" / "sig-003"
        run_dir.mkdir(parents=True)

        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")
        (run_dir / "bundle_signature.json").write_text("{}", encoding="utf-8")

        with patch.dict("os.environ", {}, clear=True):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertTrue("signing key" in msg.lower() or "mismatch" in msg.lower())

    def test_write_and_verify_signature_ok_with_ed25519_public_key(self) -> None:
        run_dir = self.root / "runs" / "sig-004"
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text(json.dumps({"a": 1}), encoding="utf-8")

        keys_dir = self.root / "keys"
        meta = generate_ed25519_keypair(output_dir=keys_dir, key_name="test")

        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_PRIVATE_KEY_FILE": meta["privateKeyPath"],
                "CONTINUUM_SIGNING_PUBLIC_KEY_FILE": meta["publicKeyPath"],
                "CONTINUUM_SIGNING_KEY_ID": meta["keyId"],
                "CONTINUUM_SIGNING_PUBLIC_KEY_ID": meta["publicKeyId"],
                "CONTINUUM_SIGNING_MODE": "ed25519",
            },
            clear=True,
        ):
            payload = write_bundle_signature(run_dir)
            self.assertEqual(payload.get("algorithm"), "ED25519(manifest_sha256)")
            self.assertEqual(payload.get("publicKeyId"), meta["publicKeyId"])

        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_PUBLIC_KEY_FILE": meta["publicKeyPath"],
                "CONTINUUM_SIGNING_PUBLIC_KEY_ID": meta["publicKeyId"],
            },
            clear=True,
        ):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertTrue(ok, msg)

    def test_unsigned_mode_writes_no_stale_signature_and_does_not_verify(self) -> None:
        run_dir = self.root / "runs" / "unsigned"
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
        (run_dir / "bundle_signature.json").write_text("stale", encoding="utf-8")
        (run_dir / "manifest.sha256").write_text("stale", encoding="utf-8")

        with patch.dict(
            "os.environ", {"CONTINUUM_SIGNING_MODE": "unsigned"}, clear=True
        ):
            payload = write_bundle_signature(run_dir)
            self.assertIsNone(payload)
            self.assertFalse((run_dir / "bundle_signature.json").exists())
            self.assertFalse((run_dir / "manifest.sha256").exists())
            ok, message = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertIn("missing bundle_signature", message)

    def test_development_default_does_not_infer_signing_from_available_secret(
        self,
    ) -> None:
        run_dir = self.root / "runs" / "development-default"
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")

        with patch.dict(
            "os.environ",
            {"CONTINUUM_SIGNING_KEY": "test-only-secret"},
            clear=True,
        ):
            payload = write_bundle_signature(run_dir)
            self.assertIsNone(payload)
            self.assertFalse((run_dir / "bundle_signature.json").exists())

    def test_required_signing_needs_explicit_mode_before_signing(self) -> None:
        run_dir = self.root / "runs" / "required-mode"
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")

        with (
            patch.dict(
                "os.environ",
                {
                    "CONTINUUM_SIGNING_REQUIRED": "true",
                    "CONTINUUM_SIGNING_KEY": "test-only-secret",
                },
                clear=True,
            ),
            self.assertRaisesRegex(RuntimeError, "CONTINUUM_SIGNING_MODE is not set"),
        ):
            write_bundle_signature(run_dir)

    def test_explicit_signing_mode_never_downgrades_without_secret(self) -> None:
        run_dir = self.root / "runs" / "missing-secret"
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")

        with (
            patch.dict("os.environ", {"CONTINUUM_SIGNING_MODE": "hmac"}, clear=True),
            self.assertRaisesRegex(RuntimeError, "CONTINUUM_SIGNING_KEY is not set"),
        ):
            write_bundle_signature(run_dir)

    def test_hmac_signing_rejects_short_keys_and_invalid_key_ids(self) -> None:
        run_dir = self.root / "runs" / "weak-secret"
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text("{}", encoding="utf-8")

        with (
            patch.dict(
                "os.environ",
                {
                    "CONTINUUM_SIGNING_MODE": "hmac",
                    "CONTINUUM_SIGNING_KEY": "too-short",
                },
                clear=True,
            ),
            self.assertRaisesRegex(RuntimeError, "at least 32 UTF-8 bytes"),
        ):
            write_bundle_signature(run_dir)

        with (
            patch.dict(
                "os.environ",
                {
                    "CONTINUUM_SIGNING_MODE": "hmac",
                    "CONTINUUM_SIGNING_KEY": "valid-test-key-material-0123456789abcdef",
                    "CONTINUUM_SIGNING_KEY_ID": "invalid key id",
                },
                clear=True,
            ),
            self.assertRaisesRegex(ValueError, "keyId is missing or malformed"),
        ):
            write_bundle_signature(run_dir)

    def test_keygen_writes_expected_files(self) -> None:
        keys_dir = self.root / "keys-output"
        meta = generate_ed25519_keypair(output_dir=keys_dir, key_name="bank")
        self.assertTrue((keys_dir / "bank.private.pem").is_file())
        self.assertTrue((keys_dir / "bank.public.pem").is_file())
        self.assertTrue((keys_dir / "bank.json").is_file())
        self.assertEqual(meta["algorithm"], "Ed25519")


if __name__ == "__main__":
    unittest.main()
