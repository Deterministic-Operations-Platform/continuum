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
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


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
    sig = hmac.new(key.encode("utf-8"), manifest_sha.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "algorithm": "HMAC-SHA256(manifest_sha256)",
        "manifest_sha256": manifest_sha,
        "signature": sig,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "keyId": _default_key_id(),
    }


def keygen_ed25519() -> tuple[str, str]:
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_bytes = priv.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub_bytes = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(priv_bytes).decode("ascii"), base64.b64encode(pub_bytes).decode("ascii")


def _load_private_key(private_key_pem: str) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(private_key_pem.encode("utf-8"), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("private key is not Ed25519")
    return key


def _load_public_key(public_key_pem: str) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("public key is not Ed25519")
    return key


def _load_ed25519_private_key() -> tuple[Ed25519PrivateKey | None, str]:
    b64 = os.environ.get("CONTINUUM_ED25519_PRIVATE_KEY_B64")
    if b64:
        raw = base64.b64decode(b64.encode("ascii"))
        return Ed25519PrivateKey.from_private_bytes(raw), "env:b64"

    path = os.environ.get("CONTINUUM_ED25519_PRIVATE_KEY_PATH")
    if path:
        raw = base64.b64decode(Path(path).read_text(encoding="utf-8").strip().encode("ascii"))
        return Ed25519PrivateKey.from_private_bytes(raw), f"file:{path}"

    if os.environ.get("CONTINUUM_SIGNING_PRIVATE_KEY"):
        return _load_private_key(os.environ["CONTINUUM_SIGNING_PRIVATE_KEY"]), "env:pem"

    if os.environ.get("CONTINUUM_SIGNING_PRIVATE_KEY_FILE"):
        file_path = os.environ["CONTINUUM_SIGNING_PRIVATE_KEY_FILE"]
        return _load_private_key(Path(file_path).read_text(encoding="utf-8")), f"file:{file_path}"

    return None, "missing"


def _load_ed25519_public_key(run_dir: Path) -> tuple[Ed25519PublicKey | None, str]:
    sig_path = run_dir / "bundle_signature.json"
    if sig_path.is_file():
        try:
            sig = json.loads(sig_path.read_text(encoding="utf-8"))
            pub_b64 = sig.get("publicKeyB64")
            if isinstance(pub_b64, str) and pub_b64:
                raw = base64.b64decode(pub_b64.encode("ascii"))
                return Ed25519PublicKey.from_public_bytes(raw), "bundle:publicKeyB64"
        except Exception:
            pass

    b64 = os.environ.get("CONTINUUM_ED25519_PUBLIC_KEY_B64")
    if b64:
        raw = base64.b64decode(b64.encode("ascii"))
        return Ed25519PublicKey.from_public_bytes(raw), "env:b64"

    path = os.environ.get("CONTINUUM_ED25519_PUBLIC_KEY_PATH")
    if path:
        raw = base64.b64decode(Path(path).read_text(encoding="utf-8").strip().encode("ascii"))
        return Ed25519PublicKey.from_public_bytes(raw), f"file:{path}"

    if os.environ.get("CONTINUUM_SIGNING_PUBLIC_KEY"):
        return _load_public_key(os.environ["CONTINUUM_SIGNING_PUBLIC_KEY"]), "env:pem"

    if os.environ.get("CONTINUUM_SIGNING_PUBLIC_KEY_FILE"):
        file_path = os.environ["CONTINUUM_SIGNING_PUBLIC_KEY_FILE"]
        return _load_public_key(Path(file_path).read_text(encoding="utf-8")), f"file:{file_path}"

    private_key, source = _load_ed25519_private_key()
    if private_key is not None:
        return private_key.public_key(), f"{source}:derived"
    return None, "missing"


def sign_manifest_ed25519(manifest_path: Path, *, include_public_key: bool = True) -> dict[str, Any]:
    private_key, private_source = _load_ed25519_private_key()
    if private_key is None:
        raise RuntimeError("Ed25519 signing requested but private key is not configured")

    manifest_sha = sha256_file(manifest_path)
    sig_raw = private_key.sign(manifest_sha.encode("utf-8"))
    payload: dict[str, Any] = {
        "algorithm": "ED25519(manifest_sha256)",
        "manifest_sha256": manifest_sha,
        "signatureB64": base64.b64encode(sig_raw).decode("ascii"),
        "signature": base64.b64encode(sig_raw).decode("ascii"),
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "keyId": _default_key_id(),
        "publicKeyId": _default_public_key_id(),
        "privateKeySource": private_source,
    }
    if include_public_key:
        pub_raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        payload["publicKeyB64"] = base64.b64encode(pub_raw).decode("ascii")
    return payload


def generate_ed25519_keypair(*, output_dir: Path, key_name: str = "continuum-ed25519") -> dict[str, str]:
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
    (output_dir / f"{key_name}.json").write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    return metadata


def write_bundle_signature(run_dir: Path, manifest_filename: str = "manifest.json") -> dict[str, Any] | None:
    manifest_path = run_dir / manifest_filename
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")

    mode = (os.environ.get("CONTINUUM_SIGNING_MODE") or "").strip().lower()
    if not mode:
        mode = "ed25519" if _load_ed25519_private_key()[0] is not None else "hmac"

    if mode == "hmac":
        key = os.environ.get("CONTINUUM_SIGNING_KEY") or os.environ.get("CONTINUUM_BUNDLE_HMAC_KEY")
        if not key:
            return None
        payload = sign_manifest_hmac(manifest_path, key=key)
    elif mode == "ed25519":
        include_pub = (os.environ.get("CONTINUUM_INCLUDE_PUBLIC_KEY_IN_BUNDLE") or "1").strip().lower() not in {"0", "false", "no"}
        payload = sign_manifest_ed25519(manifest_path, include_public_key=include_pub)
    else:
        raise ValueError(f"Unknown CONTINUUM_SIGNING_MODE: {mode}")

    (run_dir / "bundle_signature.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    (run_dir / "manifest.sha256").write_text(f"{payload['manifest_sha256']}  {manifest_filename}\n", encoding="utf-8")
    return payload


def _hmac_verify(run_dir: Path, sig: dict[str, Any], manifest_sha: str) -> tuple[bool, str]:
    key = os.environ.get("CONTINUUM_SIGNING_KEY") or os.environ.get("CONTINUUM_BUNDLE_HMAC_KEY")
    if not key:
        return False, "CONTINUUM_SIGNING_KEY not set"
    expected = hmac.new(key.encode("utf-8"), manifest_sha.encode("utf-8"), hashlib.sha256).hexdigest()
    if sig.get("signature") != expected:
        return False, "signature mismatch"
    return True, "ok"


def _ed25519_verify(run_dir: Path, sig: dict[str, Any], manifest_sha: str) -> tuple[bool, str]:
    pub, src = _load_ed25519_public_key(run_dir)
    if pub is None:
        return False, f"public key missing ({src})"

    sig_b64 = sig.get("signatureB64") or sig.get("signature")
    if not sig_b64:
        return False, "missing signatureB64"

    try:
        sig_raw = base64.b64decode(str(sig_b64).encode("ascii"), validate=True)
        pub.verify(sig_raw, manifest_sha.encode("utf-8"))
        return True, f"ok ({src})"
    except Exception:
        return False, "signature mismatch"


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

    manifest_sha = sha256_file(manifest_path)
    if sig.get("manifest_sha256") != manifest_sha:
        return False, "manifest sha mismatch"

    algorithm = str(sig.get("algorithm") or "")
    if algorithm.upper().startswith("ED25519"):
        return _ed25519_verify(run_dir, sig, manifest_sha)
    if algorithm.startswith("HMAC"):
        return _hmac_verify(run_dir, sig, manifest_sha)
    return False, f"unknown algorithm: {algorithm or 'unknown'}"
