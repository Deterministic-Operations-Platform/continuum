from __future__ import annotations

from pathlib import Path
from typing import Any
import base64
import hashlib
import hmac
import json
import os
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _default_key_id() -> str:
    return os.environ.get("CONTINUUM_SIGNING_KEY_ID", os.environ.get("CONTINUUM_BUNDLE_KEY_ID", "default"))


def _default_public_key_id() -> str:
    return os.environ.get("CONTINUUM_SIGNING_PUBLIC_KEY_ID", _default_key_id())


def sign_manifest_hmac(manifest_path: Path, key: str) -> dict[str, Any]:
    manifest_sha = sha256_file(manifest_path)
    signature = hmac.new(key.encode("utf-8"), manifest_sha.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "algorithm": "HMAC-SHA256(manifest_sha256)",
        "manifest_sha256": manifest_sha,
        "signature": signature,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "keyId": _default_key_id(),
    }


def _load_private_key(private_key_pem: str) -> ed25519.Ed25519PrivateKey:
    return serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)


def _load_public_key(public_key_pem: str) -> ed25519.Ed25519PublicKey:
    return serialization.load_pem_public_key(public_key_pem.encode("utf-8"))


def sign_manifest_ed25519(manifest_path: Path, private_key_pem: str) -> dict[str, Any]:
    manifest_sha = sha256_file(manifest_path)
    private_key = _load_private_key(private_key_pem)
    signature = private_key.sign(manifest_sha.encode("utf-8"))
    return {
        "algorithm": "Ed25519(manifest_sha256)",
        "manifest_sha256": manifest_sha,
        "signature": base64.b64encode(signature).decode("utf-8"),
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "keyId": _default_key_id(),
        "publicKeyId": _default_public_key_id(),
    }


def generate_ed25519_keypair(*, output_dir: Path, key_name: str = "continuum-ed25519") -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    private_key = ed25519.Ed25519PrivateKey.generate()
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
    (output_dir / f"{key_name}.json").write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return metadata


def _env_private_key() -> str | None:
    if os.environ.get("CONTINUUM_SIGNING_PRIVATE_KEY"):
        return os.environ["CONTINUUM_SIGNING_PRIVATE_KEY"]
    if os.environ.get("CONTINUUM_SIGNING_PRIVATE_KEY_FILE"):
        return Path(os.environ["CONTINUUM_SIGNING_PRIVATE_KEY_FILE"]).read_text(encoding="utf-8")
    return None


def _env_public_key() -> str | None:
    if os.environ.get("CONTINUUM_SIGNING_PUBLIC_KEY"):
        return os.environ["CONTINUUM_SIGNING_PUBLIC_KEY"]
    if os.environ.get("CONTINUUM_SIGNING_PUBLIC_KEY_FILE"):
        return Path(os.environ["CONTINUUM_SIGNING_PUBLIC_KEY_FILE"]).read_text(encoding="utf-8")
    return None


def write_bundle_signature(run_dir: Path, manifest_filename: str = "manifest.json") -> dict[str, Any] | None:
    private_key = _env_private_key()
    key = os.environ.get("CONTINUUM_SIGNING_KEY") or os.environ.get("CONTINUUM_BUNDLE_HMAC_KEY")
    if not private_key and not key:
        return None

    manifest_path = run_dir / manifest_filename
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")

    payload = sign_manifest_ed25519(manifest_path, private_key_pem=private_key) if private_key else sign_manifest_hmac(manifest_path, key=key)
    (run_dir / "bundle_signature.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (run_dir / "manifest.sha256").write_text(f"{payload['manifest_sha256']}  {manifest_filename}\n", encoding="utf-8")
    return payload


def verify_bundle_signature(run_dir: Path) -> tuple[bool, str]:
    sig_path = run_dir / "bundle_signature.json"
    manifest_path = run_dir / "manifest.json"
    if not sig_path.is_file():
        return False, "missing bundle_signature.json"
    if not manifest_path.is_file():
        return False, "missing manifest.json"

    try:
        sig = json.loads(sig_path.read_text(encoding="utf-8"))
    except Exception:
        return False, "invalid bundle_signature.json"

    algorithm = str(sig.get("algorithm") or "")
    manifest_sha = sha256_file(manifest_path)
    if sig.get("manifest_sha256") != manifest_sha:
        return False, "manifest sha mismatch"

    if algorithm.startswith("HMAC-SHA256"):
        key = os.environ.get("CONTINUUM_SIGNING_KEY") or os.environ.get("CONTINUUM_BUNDLE_HMAC_KEY")
        if not key:
            return False, "CONTINUUM_SIGNING_KEY not set (signing key missing)"
        expected = hmac.new(key.encode("utf-8"), manifest_sha.encode("utf-8"), hashlib.sha256).hexdigest()
        if sig.get("signature") != expected:
            return False, "signature mismatch"
        return True, "ok"

    if algorithm.startswith("Ed25519"):
        public_key_pem = _env_public_key()
        if not public_key_pem:
            private_key_pem = _env_private_key()
            if not private_key_pem:
                return False, "CONTINUUM_SIGNING_PUBLIC_KEY(_FILE) not set (public key missing)"
            private_key = _load_private_key(private_key_pem)
            public_key = private_key.public_key()
        else:
            public_key = _load_public_key(public_key_pem)
        try:
            signature = base64.b64decode(str(sig.get("signature") or ""), validate=True)
            public_key.verify(signature, manifest_sha.encode("utf-8"))
        except Exception:
            return False, "signature mismatch"
        return True, "ok"

    return False, f"unsupported signature algorithm: {algorithm or 'unknown'}"
