from __future__ import annotations

import json
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from continuum import signing
from continuum.signing import (
    keygen_ed25519,
    verify_bundle_signature,
    write_bundle_signature,
)
from tests._tmpdir import make_temp_dir, remove_temp_dir


def _key_record(key_id: str, public_key_b64: str, **windows: str) -> dict[str, str]:
    return {
        "keyId": key_id,
        "algorithm": "Ed25519",
        "publicKeyB64": public_key_b64,
        **windows,
    }


def _keyring(*records: dict[str, str]) -> str:
    return json.dumps({"version": 1, "keys": list(records)}, sort_keys=True)


class Ed25519SigningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = make_temp_dir("ed25519")
        self.addCleanup(lambda: remove_temp_dir(self.root))

    def _run_dir(self, name: str) -> Path:
        run_dir = self.root / "runs" / name
        run_dir.mkdir(parents=True)
        (run_dir / "manifest.json").write_text(
            json.dumps({"run": name}), encoding="utf-8"
        )
        return run_dir

    def test_ed25519_verifies_with_external_public_keyring(self) -> None:
        run_dir = self._run_dir("ed-001")
        private_b64, public_b64 = keygen_ed25519()
        ring = _keyring(_key_record("test-key", public_b64))

        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_MODE": "ed25519",
                "CONTINUUM_ED25519_PRIVATE_KEY_B64": private_b64,
                "CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": ring,
                "CONTINUUM_SIGNING_KEY_ID": "test-key",
                "CONTINUUM_INCLUDE_PUBLIC_KEY_IN_BUNDLE": "1",
            },
            clear=True,
        ):
            payload = write_bundle_signature(run_dir)
            self.assertIsNotNone(payload)
            self.assertEqual(payload["algorithm"], "ED25519(manifest_sha256)")
            self.assertEqual(payload["signatureVersion"], 2)

        with patch.dict(
            "os.environ", {"CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": ring}, clear=True
        ):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertTrue(ok, msg)

    def test_embedded_public_key_is_not_a_trust_anchor(self) -> None:
        run_dir = self._run_dir("ed-002")
        private_b64, public_b64 = keygen_ed25519()
        ring = _keyring(_key_record("test-key", public_b64))
        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_MODE": "ed25519",
                "CONTINUUM_ED25519_PRIVATE_KEY_B64": private_b64,
                "CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": ring,
                "CONTINUUM_SIGNING_KEY_ID": "test-key",
                "CONTINUUM_INCLUDE_PUBLIC_KEY_IN_BUNDLE": "1",
            },
            clear=True,
        ):
            write_bundle_signature(run_dir)

        with patch.dict("os.environ", {}, clear=True):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertIn("configuration is missing", msg)

    def test_signature_binds_key_id_and_creation_time(self) -> None:
        run_dir = self._run_dir("ed-003")
        private_b64, public_b64 = keygen_ed25519()
        ring = _keyring(_key_record("test-key", public_b64))
        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_MODE": "ed25519",
                "CONTINUUM_ED25519_PRIVATE_KEY_B64": private_b64,
                "CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": ring,
                "CONTINUUM_SIGNING_KEY_ID": "test-key",
            },
            clear=True,
        ):
            write_bundle_signature(run_dir)

        sig_path = run_dir / "bundle_signature.json"
        payload = json.loads(sig_path.read_text(encoding="utf-8"))
        payload["createdAt"] = "2000-01-01T00:00:00Z"
        sig_path.write_text(json.dumps(payload), encoding="utf-8")
        with patch.dict(
            "os.environ", {"CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": ring}, clear=True
        ):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertIn("mismatch", msg.lower())

    def test_malformed_ring_and_signature_fail_closed(self) -> None:
        run_dir = self._run_dir("ed-004")
        private_b64, public_b64 = keygen_ed25519()
        ring = _keyring(_key_record("test-key", public_b64))
        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_MODE": "ed25519",
                "CONTINUUM_ED25519_PRIVATE_KEY_B64": private_b64,
                "CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": ring,
                "CONTINUUM_SIGNING_KEY_ID": "test-key",
            },
            clear=True,
        ):
            write_bundle_signature(run_dir)

        with patch.dict(
            "os.environ", {"CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": "not-json"}, clear=True
        ):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertIn("not valid JSON", msg)

        now = signing._now_utc()
        invalid_window = _keyring(
            _key_record(
                "test-key",
                public_b64,
                signUntil=(now + timedelta(days=2)).isoformat().replace("+00:00", "Z"),
                verifyUntil=(now + timedelta(days=1))
                .isoformat()
                .replace("+00:00", "Z"),
            )
        )
        with patch.dict(
            "os.environ",
            {"CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": invalid_window},
            clear=True,
        ):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertIn("verifyUntil must not precede signUntil", msg)

        payload = json.loads(
            (run_dir / "bundle_signature.json").read_text(encoding="utf-8")
        )
        payload["signatureVersion"] = 2.0
        (run_dir / "bundle_signature.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        with patch.dict(
            "os.environ", {"CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": ring}, clear=True
        ):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertIn("unsupported", msg.lower())

        payload["signatureVersion"] = 2
        payload["signatureB64"] = "not base64"
        (run_dir / "bundle_signature.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        with patch.dict(
            "os.environ", {"CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": ring}, clear=True
        ):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertIn("base64", msg.lower())

    def test_wrong_or_unknown_trusted_key_fails_closed(self) -> None:
        run_dir = self._run_dir("ed-wrong-key")
        private_b64, public_b64 = keygen_ed25519()
        _, wrong_public_b64 = keygen_ed25519()
        ring = _keyring(_key_record("key-a", public_b64))
        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_MODE": "ed25519",
                "CONTINUUM_ED25519_PRIVATE_KEY_B64": private_b64,
                "CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": ring,
                "CONTINUUM_SIGNING_KEY_ID": "key-a",
            },
            clear=True,
        ):
            write_bundle_signature(run_dir)

        wrong_ring = _keyring(_key_record("key-a", wrong_public_b64))
        with patch.dict(
            "os.environ", {"CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": wrong_ring}, clear=True
        ):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertIn("signature mismatch", msg)

        sig_path = run_dir / "bundle_signature.json"
        payload = json.loads(sig_path.read_text(encoding="utf-8"))
        payload["keyId"] = "unknown"
        sig_path.write_text(json.dumps(payload), encoding="utf-8")
        with patch.dict(
            "os.environ", {"CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": ring}, clear=True
        ):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertIn("unknown Ed25519 keyId", msg)

    def test_expired_key_cannot_sign_or_verify(self) -> None:
        run_dir = self._run_dir("ed-005")
        private_b64, public_b64 = keygen_ed25519()
        now = signing._now_utc()
        expired = _keyring(
            _key_record(
                "expired-key",
                public_b64,
                notBefore=(now - timedelta(days=3)).isoformat().replace("+00:00", "Z"),
                signUntil=(now - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
                verifyUntil=(now - timedelta(days=1))
                .isoformat()
                .replace("+00:00", "Z"),
            )
        )
        env = {
            "CONTINUUM_SIGNING_MODE": "ed25519",
            "CONTINUUM_ED25519_PRIVATE_KEY_B64": private_b64,
            "CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": expired,
            "CONTINUUM_SIGNING_KEY_ID": "expired-key",
        }
        with (
            patch.dict("os.environ", env, clear=True),
            self.assertRaisesRegex(ValueError, "signing window expired"),
        ):
            write_bundle_signature(run_dir)

        # A correctly signed, pre-expiration record must stop verifying after
        # the trusted verification window closes.
        signing_time = now - timedelta(days=3)
        valid_for_signing = _keyring(
            _key_record(
                "expired-key",
                public_b64,
                notBefore=(now - timedelta(days=4)).isoformat().replace("+00:00", "Z"),
                signUntil=(now - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
                verifyUntil=(now + timedelta(days=2))
                .isoformat()
                .replace("+00:00", "Z"),
            )
        )
        with (
            patch.dict(
                "os.environ",
                {**env, "CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": valid_for_signing},
                clear=True,
            ),
            patch("continuum.signing._now_utc", return_value=signing_time),
        ):
            write_bundle_signature(run_dir)

        expired_for_verification = _keyring(
            _key_record(
                "expired-key",
                public_b64,
                notBefore=(now - timedelta(days=4)).isoformat().replace("+00:00", "Z"),
                signUntil=(now - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
                verifyUntil=(now - timedelta(seconds=1))
                .isoformat()
                .replace("+00:00", "Z"),
            )
        )
        with patch.dict(
            "os.environ",
            {"CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": expired_for_verification},
            clear=True,
        ):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertIn("verification window expired", msg)

    def test_rotation_verifies_old_and_new_key_until_old_verify_window_expires(
        self,
    ) -> None:
        old_run_dir = self._run_dir("rotation-old")
        new_run_dir = self._run_dir("rotation-new")
        old_private, old_public = keygen_ed25519()
        new_private, new_public = keygen_ed25519()
        now = signing._now_utc()
        old_signing_time = now - timedelta(days=2)
        old_record = _key_record(
            "key-old",
            old_public,
            notBefore=(now - timedelta(days=3)).isoformat().replace("+00:00", "Z"),
            signUntil=(now - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            verifyUntil=(now + timedelta(days=10)).isoformat().replace("+00:00", "Z"),
        )
        with (
            patch.dict(
                "os.environ",
                {
                    "CONTINUUM_SIGNING_MODE": "ed25519",
                    "CONTINUUM_ED25519_PRIVATE_KEY_B64": old_private,
                    "CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": _keyring(old_record),
                    "CONTINUUM_SIGNING_KEY_ID": "key-old",
                },
                clear=True,
            ),
            patch("continuum.signing._now_utc", return_value=old_signing_time),
        ):
            write_bundle_signature(old_run_dir)

        rotated_ring = _keyring(old_record, _key_record("key-new", new_public))
        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_MODE": "ed25519",
                "CONTINUUM_ED25519_PRIVATE_KEY_B64": new_private,
                "CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": rotated_ring,
                "CONTINUUM_SIGNING_KEY_ID": "key-new",
            },
            clear=True,
        ):
            write_bundle_signature(new_run_dir)

        with patch.dict(
            "os.environ",
            {"CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": rotated_ring},
            clear=True,
        ):
            self.assertTrue(verify_bundle_signature(old_run_dir)[0])
            self.assertTrue(verify_bundle_signature(new_run_dir)[0])

        old_expired_ring = _keyring(
            {
                **old_record,
                "verifyUntil": (now - timedelta(seconds=1))
                .isoformat()
                .replace("+00:00", "Z"),
            },
            _key_record("key-new", new_public),
        )
        with patch.dict(
            "os.environ",
            {"CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": old_expired_ring},
            clear=True,
        ):
            ok, msg = verify_bundle_signature(old_run_dir)
            self.assertFalse(ok)
            self.assertIn("verification window expired", msg)
            self.assertTrue(verify_bundle_signature(new_run_dir)[0])

    def test_manifest_tampering_is_detected(self) -> None:
        run_dir = self._run_dir("ed-006")
        private_b64, public_b64 = keygen_ed25519()
        ring = _keyring(_key_record("test-key", public_b64))
        with patch.dict(
            "os.environ",
            {
                "CONTINUUM_SIGNING_MODE": "ed25519",
                "CONTINUUM_ED25519_PRIVATE_KEY_B64": private_b64,
                "CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": ring,
                "CONTINUUM_SIGNING_KEY_ID": "test-key",
            },
            clear=True,
        ):
            write_bundle_signature(run_dir)

        (run_dir / "manifest.json").write_text(
            json.dumps({"tampered": True}), encoding="utf-8"
        )
        with patch.dict(
            "os.environ", {"CONTINUUM_SIGNING_PUBLIC_KEYS_JSON": ring}, clear=True
        ):
            ok, msg = verify_bundle_signature(run_dir)
            self.assertFalse(ok)
            self.assertIn("manifest sha mismatch", msg)


if __name__ == "__main__":
    unittest.main()
