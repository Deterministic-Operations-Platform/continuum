from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature, UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

_SIGNATURE_VERSION = 2
_SIGNATURE_DOMAIN = "continuum.bundle.signature"
_MAX_FUTURE_SKEW = timedelta(minutes=5)
_KEY_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


@dataclass(frozen=True)
class _TrustedEd25519Key:
    public_key: Ed25519PublicKey
    public_bytes: bytes
    not_before: datetime | None = None
    sign_until: datetime | None = None
    verify_until: datetime | None = None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _default_key_id() -> str:
    return os.environ.get(
        "CONTINUUM_SIGNING_KEY_ID", os.environ.get("CONTINUUM_BUNDLE_KEY_ID", "default")
    )


def _default_public_key_id() -> str:
    return os.environ.get("CONTINUUM_SIGNING_PUBLIC_KEY_ID", _default_key_id())


def _now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _format_timestamp(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _parse_timestamp(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as err:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from err
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _validate_key_id(value: Any) -> str:
    if not isinstance(value, str) or not _KEY_ID_PATTERN.fullmatch(value):
        raise ValueError("keyId is missing or malformed")
    return value


def _signature_input(
    *, algorithm: str, manifest_sha256: str, key_id: str, created_at: str
) -> bytes:
    payload = {
        "algorithm": algorithm,
        "createdAt": created_at,
        "domain": _SIGNATURE_DOMAIN,
        "keyId": key_id,
        "manifestSha256": manifest_sha256,
        "version": _SIGNATURE_VERSION,
    }
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _hmac_secret() -> str | None:
    current = os.environ.get("CONTINUUM_SIGNING_KEY")
    legacy = os.environ.get("CONTINUUM_BUNDLE_HMAC_KEY")
    if (
        current
        and legacy
        and not hmac.compare_digest(current.encode("utf-8"), legacy.encode("utf-8"))
    ):
        raise ValueError("CONTINUUM_SIGNING_KEY and CONTINUUM_BUNDLE_HMAC_KEY disagree")
    return current or legacy


def _hmac_signing_secret() -> str:
    secret = _hmac_secret()
    if not secret:
        raise RuntimeError(
            "HMAC signing is configured but CONTINUUM_SIGNING_KEY is not set"
        )
    if len(secret.encode("utf-8")) < 32:
        raise RuntimeError("HMAC signing key must contain at least 32 UTF-8 bytes")
    _validate_key_id(_default_key_id())
    return secret


def sign_manifest_hmac(manifest_path: Path, key: str) -> dict[str, Any]:
    if len(key.encode("utf-8")) < 32:
        raise ValueError("HMAC signing key must contain at least 32 UTF-8 bytes")
    manifest_sha = sha256_file(manifest_path)
    key_id = _validate_key_id(_default_key_id())
    created_at = _format_timestamp(_now_utc())
    algorithm = "HMAC-SHA256(manifest_sha256)"
    message = _signature_input(
        algorithm=algorithm,
        manifest_sha256=manifest_sha,
        key_id=key_id,
        created_at=created_at,
    )
    sig = hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return {
        "algorithm": algorithm,
        "signatureVersion": _SIGNATURE_VERSION,
        "manifest_sha256": manifest_sha,
        "signature": sig,
        "createdAt": created_at,
        "keyId": key_id,
    }


def keygen_ed25519() -> tuple[str, str]:
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_bytes = priv.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    pub_bytes = pub.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(priv_bytes).decode("ascii"), base64.b64encode(
        pub_bytes
    ).decode("ascii")


def _load_private_key(private_key_pem: str) -> Ed25519PrivateKey:
    try:
        key = serialization.load_pem_private_key(
            private_key_pem.encode("utf-8"), password=None
        )
    except UnsupportedAlgorithm as err:
        raise ValueError("private key algorithm is unsupported") from err
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("private key is not Ed25519")
    return key


def _load_public_key(public_key_pem: str) -> Ed25519PublicKey:
    try:
        key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    except UnsupportedAlgorithm as err:
        raise ValueError("public key algorithm is unsupported") from err
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("public key is not Ed25519")
    return key


def _decode_key_b64(value: Any, *, expected_length: int, field_name: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be base64 text")
    try:
        decoded = base64.b64decode(value.encode("ascii"), validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as err:
        raise ValueError(f"{field_name} is malformed base64") from err
    if (
        len(decoded) != expected_length
        or base64.b64encode(decoded).decode("ascii") != value
    ):
        raise ValueError(f"{field_name} has an invalid length or encoding")
    return decoded


def _load_ed25519_private_key() -> tuple[Ed25519PrivateKey | None, str]:
    sources = [
        (
            "CONTINUUM_ED25519_PRIVATE_KEY_B64",
            os.environ.get("CONTINUUM_ED25519_PRIVATE_KEY_B64"),
        ),
        (
            "CONTINUUM_ED25519_PRIVATE_KEY_PATH",
            os.environ.get("CONTINUUM_ED25519_PRIVATE_KEY_PATH"),
        ),
        (
            "CONTINUUM_SIGNING_PRIVATE_KEY",
            os.environ.get("CONTINUUM_SIGNING_PRIVATE_KEY"),
        ),
        (
            "CONTINUUM_SIGNING_PRIVATE_KEY_FILE",
            os.environ.get("CONTINUUM_SIGNING_PRIVATE_KEY_FILE"),
        ),
    ]
    configured = [(name, value) for name, value in sources if value]
    if len(configured) > 1:
        raise ValueError("configure exactly one Ed25519 private-key source")
    if not configured:
        return None, "missing"

    name, value = configured[0]
    if name == "CONTINUUM_ED25519_PRIVATE_KEY_B64":
        raw = _decode_key_b64(value, expected_length=32, field_name=name)
        return Ed25519PrivateKey.from_private_bytes(raw), "env:b64"
    if name == "CONTINUUM_ED25519_PRIVATE_KEY_PATH":
        raw_text = Path(value).read_text(encoding="utf-8").strip()
        raw = _decode_key_b64(raw_text, expected_length=32, field_name=name)
        return Ed25519PrivateKey.from_private_bytes(raw), "file:b64"
    if name == "CONTINUUM_SIGNING_PRIVATE_KEY":
        return _load_private_key(value), "env:pem"
    return _load_private_key(Path(value).read_text(encoding="utf-8")), "file:pem"


def _parse_trusted_key_record(item: Any) -> tuple[str, _TrustedEd25519Key]:
    if not isinstance(item, dict):
        raise TypeError("each trusted key must be an object")
    key_id = _validate_key_id(item.get("keyId"))
    algorithm = item.get("algorithm")
    if not isinstance(algorithm, str) or algorithm.lower() != "ed25519":
        raise ValueError(f"trusted key {key_id} has an unsupported algorithm")
    public_bytes = _decode_key_b64(
        item.get("publicKeyB64"),
        expected_length=32,
        field_name=f"{key_id}.publicKeyB64",
    )
    not_before = (
        _parse_timestamp(item["notBefore"], f"{key_id}.notBefore")
        if "notBefore" in item
        else None
    )
    sign_until = (
        _parse_timestamp(item["signUntil"], f"{key_id}.signUntil")
        if "signUntil" in item
        else None
    )
    verify_until = (
        _parse_timestamp(item["verifyUntil"], f"{key_id}.verifyUntil")
        if "verifyUntil" in item
        else None
    )
    if sign_until and not verify_until:
        raise ValueError(
            f"trusted key {key_id} with a signUntil cutoff must include verifyUntil"
        )
    if sign_until and verify_until and verify_until < sign_until:
        raise ValueError(f"trusted key {key_id} verifyUntil must not precede signUntil")
    if not_before and verify_until and verify_until < not_before:
        raise ValueError(f"trusted key {key_id} expires before it becomes valid")
    if not_before and sign_until and sign_until < not_before:
        raise ValueError(f"trusted key {key_id} expires before it becomes valid")
    return key_id, _TrustedEd25519Key(
        public_key=Ed25519PublicKey.from_public_bytes(public_bytes),
        public_bytes=public_bytes,
        not_before=not_before,
        sign_until=sign_until,
        verify_until=verify_until,
    )


def _load_trusted_ed25519_keys() -> dict[str, _TrustedEd25519Key]:
    ring_json = os.environ.get("CONTINUUM_SIGNING_PUBLIC_KEYS_JSON")
    ring_file = os.environ.get("CONTINUUM_SIGNING_PUBLIC_KEYS_FILE")
    if ring_json and ring_file:
        raise ValueError(
            "configure only one of CONTINUUM_SIGNING_PUBLIC_KEYS_JSON and CONTINUUM_SIGNING_PUBLIC_KEYS_FILE"
        )

    legacy_sources = [
        (
            "CONTINUUM_ED25519_PUBLIC_KEY_B64",
            os.environ.get("CONTINUUM_ED25519_PUBLIC_KEY_B64"),
        ),
        (
            "CONTINUUM_ED25519_PUBLIC_KEY_PATH",
            os.environ.get("CONTINUUM_ED25519_PUBLIC_KEY_PATH"),
        ),
        (
            "CONTINUUM_SIGNING_PUBLIC_KEY",
            os.environ.get("CONTINUUM_SIGNING_PUBLIC_KEY"),
        ),
        (
            "CONTINUUM_SIGNING_PUBLIC_KEY_FILE",
            os.environ.get("CONTINUUM_SIGNING_PUBLIC_KEY_FILE"),
        ),
    ]
    configured_legacy = [(name, value) for name, value in legacy_sources if value]
    if (ring_json or ring_file) and configured_legacy:
        raise ValueError(
            "configure a public-key ring or one legacy public-key source, not both"
        )

    if ring_json or ring_file:
        raw_json = (
            ring_json
            if ring_json
            else Path(ring_file or "").read_text(encoding="utf-8")
        )
        try:
            document = json.loads(raw_json)
        except (TypeError, json.JSONDecodeError) as err:
            raise ValueError("trusted public-key ring is not valid JSON") from err
        if (
            not isinstance(document, dict)
            or type(document.get("version", 1)) is not int
            or document.get("version", 1) != 1
        ):
            raise ValueError("trusted public-key ring must be a version 1 object")
        items = document.get("keys")
        if not isinstance(items, list) or not items:
            raise ValueError(
                "trusted public-key ring must contain a non-empty keys list"
            )
        keys: dict[str, _TrustedEd25519Key] = {}
        for item in items:
            key_id, trusted_key = _parse_trusted_key_record(item)
            if key_id in keys:
                raise ValueError(
                    f"trusted public-key ring has duplicate keyId {key_id}"
                )
            keys[key_id] = trusted_key
        return keys

    if not configured_legacy:
        return {}
    if len(configured_legacy) > 1:
        raise ValueError("configure exactly one Ed25519 public-key source")

    name, value = configured_legacy[0]
    if name == "CONTINUUM_ED25519_PUBLIC_KEY_B64":
        public_bytes = _decode_key_b64(value, expected_length=32, field_name=name)
        public_key = Ed25519PublicKey.from_public_bytes(public_bytes)
    elif name == "CONTINUUM_ED25519_PUBLIC_KEY_PATH":
        raw_text = Path(value).read_text(encoding="utf-8").strip()
        public_bytes = _decode_key_b64(raw_text, expected_length=32, field_name=name)
        public_key = Ed25519PublicKey.from_public_bytes(public_bytes)
    elif name == "CONTINUUM_SIGNING_PUBLIC_KEY":
        public_key = _load_public_key(value)
        public_bytes = public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    else:
        public_key = _load_public_key(Path(value).read_text(encoding="utf-8"))
        public_bytes = public_key.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
    return {
        _validate_key_id(_default_public_key_id()): _TrustedEd25519Key(
            public_key=public_key,
            public_bytes=public_bytes,
        )
    }


def _validate_key_window(
    trusted_key: _TrustedEd25519Key,
    *,
    signed_at: datetime,
    verified_at: datetime,
) -> None:
    if trusted_key.not_before and signed_at < trusted_key.not_before:
        raise ValueError("signature predates the trusted key validity window")
    if trusted_key.sign_until and signed_at > trusted_key.sign_until:
        raise ValueError("signature was created after the key signing window expired")
    if trusted_key.verify_until and verified_at > trusted_key.verify_until:
        raise ValueError("trusted key verification window expired")


def _ed25519_signing_material() -> tuple[
    Ed25519PrivateKey, str, _TrustedEd25519Key, datetime
]:
    private_key, _private_source = _load_ed25519_private_key()
    if private_key is None:
        raise RuntimeError(
            "Ed25519 signing requires CONTINUUM_ED25519_PRIVATE_KEY_B64, "
            "CONTINUUM_ED25519_PRIVATE_KEY_PATH, CONTINUUM_SIGNING_PRIVATE_KEY, "
            "or CONTINUUM_SIGNING_PRIVATE_KEY_FILE"
        )

    key_id = _validate_key_id(_default_key_id())
    trusted_key = _load_trusted_ed25519_keys().get(key_id)
    if trusted_key is None:
        raise RuntimeError(
            f"signing key {key_id} is not present in the trusted public-key configuration"
        )
    private_public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    if not hmac.compare_digest(private_public_bytes, trusted_key.public_bytes):
        raise RuntimeError(f"private key does not match trusted public key {key_id}")
    now = _now_utc()
    _validate_key_window(trusted_key, signed_at=now, verified_at=now)
    return private_key, key_id, trusted_key, now


def _signing_mode_and_required() -> tuple[str, bool]:
    required_value = (
        (os.environ.get("CONTINUUM_SIGNING_REQUIRED") or "false").strip().lower()
    )
    if required_value in {"1", "true", "yes", "on"}:
        required = True
    elif required_value in {"", "0", "false", "no", "off"}:
        required = False
    else:
        raise ValueError("CONTINUUM_SIGNING_REQUIRED must be true or false")

    configured_mode = (os.environ.get("CONTINUUM_SIGNING_MODE") or "").strip().lower()
    if not configured_mode:
        if required:
            raise RuntimeError(
                "signing is required, but CONTINUUM_SIGNING_MODE is not set; "
                "explicitly configure hmac or ed25519"
            )
        return "unsigned", required

    if configured_mode in {"none", "off", "unsigned"}:
        if required:
            raise RuntimeError(
                "CONTINUUM_SIGNING_REQUIRED is true but CONTINUUM_SIGNING_MODE selects unsigned output"
            )
        return "unsigned", required
    if configured_mode not in {"hmac", "ed25519"}:
        raise ValueError(f"Unknown CONTINUUM_SIGNING_MODE: {configured_mode}")
    return configured_mode, required


def validate_signing_configuration() -> str:
    """Validate configured signing policy before any workflow side effects."""
    mode, _required = _signing_mode_and_required()
    if mode == "unsigned":
        return mode
    if mode == "hmac":
        _hmac_signing_secret()
        return mode
    _ed25519_signing_material()
    return mode


def sign_manifest_ed25519(
    manifest_path: Path, *, include_public_key: bool = False
) -> dict[str, Any]:
    private_key, key_id, _trusted_key, now = _ed25519_signing_material()
    created_at = _format_timestamp(now)
    private_public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )

    manifest_sha = sha256_file(manifest_path)
    algorithm = "ED25519(manifest_sha256)"
    message = _signature_input(
        algorithm=algorithm,
        manifest_sha256=manifest_sha,
        key_id=key_id,
        created_at=created_at,
    )
    signature = private_key.sign(message)
    payload: dict[str, Any] = {
        "algorithm": algorithm,
        "signatureVersion": _SIGNATURE_VERSION,
        "manifest_sha256": manifest_sha,
        "signatureB64": base64.b64encode(signature).decode("ascii"),
        "signature": base64.b64encode(signature).decode("ascii"),
        "createdAt": created_at,
        "keyId": key_id,
        "publicKeyId": key_id,
    }
    if include_public_key:
        payload["publicKeyB64"] = base64.b64encode(private_public_bytes).decode("ascii")
    return payload


def generate_ed25519_keypair(
    *, output_dir: Path, key_name: str = "continuum-ed25519"
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    private_path = output_dir / f"{key_name}.private.pem"
    public_path = output_dir / f"{key_name}.public.pem"
    private_path.write_bytes(private_bytes)
    public_path.write_bytes(public_bytes)

    key_id = hashlib.sha256(public_bytes).hexdigest()[:16]
    metadata = {
        "algorithm": "Ed25519",
        "keyId": key_id,
        "publicKeyId": key_id,
        "privateKeyPath": str(private_path),
        "publicKeyPath": str(public_path),
    }
    (output_dir / f"{key_name}.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
    )
    return metadata


def _clear_signature_files(run_dir: Path) -> None:
    for name in ("bundle_signature.json", "manifest.sha256"):
        path = run_dir / name
        if path.exists():
            path.unlink()


def write_bundle_signature(
    run_dir: Path, manifest_filename: str = "manifest.json"
) -> dict[str, Any] | None:
    manifest_path = run_dir / manifest_filename
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")

    mode = validate_signing_configuration()

    if mode in {"none", "off", "unsigned"}:
        _clear_signature_files(run_dir)
        return None
    if mode == "hmac":
        key = _hmac_signing_secret()
        payload = sign_manifest_hmac(manifest_path, key=key)
    elif mode == "ed25519":
        include_pub = (
            os.environ.get("CONTINUUM_INCLUDE_PUBLIC_KEY_IN_BUNDLE") or "0"
        ).strip().lower() in {"1", "true", "yes"}
        payload = sign_manifest_ed25519(manifest_path, include_public_key=include_pub)
    else:
        raise ValueError(f"Unknown CONTINUUM_SIGNING_MODE: {mode}")

    (run_dir / "bundle_signature.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    (run_dir / "manifest.sha256").write_text(
        f"{payload['manifest_sha256']}  {manifest_filename}\n", encoding="utf-8"
    )
    return payload


def _hmac_verify(sig: dict[str, Any], manifest_sha: str) -> tuple[bool, str]:
    try:
        key = _hmac_secret()
    except ValueError as err:
        return False, str(err)
    if not key:
        return False, "CONTINUUM_SIGNING_KEY not set"
    signature = sig.get("signature")
    if not isinstance(signature, str) or not re.fullmatch(r"[0-9a-f]{64}", signature):
        return False, "malformed HMAC signature"

    version = sig.get("signatureVersion", 1)
    if type(version) is not int:
        return False, "unsupported HMAC signature version"
    if version == 1:
        # Read-only support for existing HMAC bundles. New signatures use v2,
        # which binds the key ID and creation time into the authenticated data.
        message = manifest_sha.encode("utf-8")
    elif version == _SIGNATURE_VERSION:
        try:
            key_id = _validate_key_id(sig.get("keyId"))
            created_at = _parse_timestamp(sig.get("createdAt"), "createdAt")
            if created_at > _now_utc() + _MAX_FUTURE_SKEW:
                return False, "signature creation time is in the future"
            message = _signature_input(
                algorithm=str(sig.get("algorithm") or ""),
                manifest_sha256=manifest_sha,
                key_id=key_id,
                created_at=_format_timestamp(created_at),
            )
        except (TypeError, ValueError) as err:
            return False, str(err)
    else:
        return False, "unsupported HMAC signature version"

    expected = hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return False, "signature mismatch"
    return True, "ok"


def _ed25519_verify(sig: dict[str, Any], manifest_sha: str) -> tuple[bool, str]:
    try:
        version = sig.get("signatureVersion", 1)
        if type(version) is not int or version != _SIGNATURE_VERSION:
            return False, "unsupported or unbound Ed25519 signature format"
        key_id = _validate_key_id(sig.get("keyId"))
        created_at = _parse_timestamp(sig.get("createdAt"), "createdAt")
        now = _now_utc()
        if created_at > now + _MAX_FUTURE_SKEW:
            return False, "signature creation time is in the future"
        trusted_keys = _load_trusted_ed25519_keys()
        if not trusted_keys:
            return False, "trusted Ed25519 public key configuration is missing"
        trusted_key = trusted_keys.get(key_id)
        if trusted_key is None:
            return False, f"unknown Ed25519 keyId: {key_id}"
        _validate_key_window(trusted_key, signed_at=created_at, verified_at=now)

        embedded = sig.get("publicKeyB64")
        if embedded is not None:
            embedded_bytes = _decode_key_b64(
                embedded, expected_length=32, field_name="publicKeyB64"
            )
            if not hmac.compare_digest(embedded_bytes, trusted_key.public_bytes):
                return False, "embedded public key does not match trusted key"

        signature_text = sig.get("signatureB64") or sig.get("signature")
        signature = _decode_key_b64(
            signature_text, expected_length=64, field_name="signatureB64"
        )
        algorithm = str(sig.get("algorithm") or "")
        message = _signature_input(
            algorithm=algorithm,
            manifest_sha256=manifest_sha,
            key_id=key_id,
            created_at=_format_timestamp(created_at),
        )
        trusted_key.public_key.verify(signature, message)
        return True, f"ok ({key_id})"
    except InvalidSignature:
        return False, "signature mismatch"
    except (OSError, TypeError, ValueError) as err:
        # Invalid, expired, malformed, and unknown trust material must fail
        # closed without breaking publication or verification callers.
        return False, str(err) or "invalid Ed25519 signature"


def verify_bundle_signature(run_dir: Path) -> tuple[bool, str]:
    sig_path = run_dir / "bundle_signature.json"
    manifest_path = run_dir / "manifest.json"
    if not sig_path.is_file():
        return False, "missing bundle_signature.json"
    if not manifest_path.is_file():
        return False, "missing manifest.json"

    try:
        sig = json.loads(sig_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False, "invalid bundle_signature.json"
    if not isinstance(sig, dict):
        return False, "invalid bundle_signature.json"

    try:
        manifest_sha = sha256_file(manifest_path)
    except OSError:
        return False, "manifest could not be read"
    signed_manifest_sha = sig.get("manifest_sha256")
    if not isinstance(signed_manifest_sha, str) or signed_manifest_sha != manifest_sha:
        return False, "manifest sha mismatch"

    algorithm = sig.get("algorithm")
    if not isinstance(algorithm, str):
        return False, "unknown algorithm: malformed"
    if algorithm.upper().startswith("ED25519"):
        return _ed25519_verify(sig, manifest_sha)
    if algorithm.upper().startswith("HMAC"):
        return _hmac_verify(sig, manifest_sha)
    return False, f"unknown algorithm: {algorithm or 'unknown'}"
