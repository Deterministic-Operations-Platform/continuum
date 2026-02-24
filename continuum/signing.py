from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import hmac
import json
import os
import time


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sign_manifest_hmac(manifest_path: Path, key: str) -> dict[str, Any]:
    manifest_sha = sha256_file(manifest_path)
    signature = hmac.new(key.encode("utf-8"), manifest_sha.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "algorithm": "HMAC-SHA256(manifest_sha256)",
        "manifest_sha256": manifest_sha,
        "signature": signature,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "keyId": os.environ.get("CONTINUUM_SIGNING_KEY_ID", os.environ.get("CONTINUUM_BUNDLE_KEY_ID", "default")),
    }


def write_bundle_signature(run_dir: Path, manifest_filename: str = "manifest.json") -> dict[str, Any] | None:
    key = os.environ.get("CONTINUUM_SIGNING_KEY") or os.environ.get("CONTINUUM_BUNDLE_HMAC_KEY")
    if not key:
        return None

    manifest_path = run_dir / manifest_filename
    if not manifest_path.is_file():
        raise FileNotFoundError(f"manifest not found: {manifest_path}")

    payload = sign_manifest_hmac(manifest_path, key=key)
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

    key = os.environ.get("CONTINUUM_SIGNING_KEY") or os.environ.get("CONTINUUM_BUNDLE_HMAC_KEY")
    if not key:
        return False, "CONTINUUM_SIGNING_KEY not set (signing key missing)"

    try:
        sig = json.loads(sig_path.read_text(encoding="utf-8"))
    except Exception:
        return False, "invalid bundle_signature.json"

    manifest_sha = sha256_file(manifest_path)
    expected = hmac.new(key.encode("utf-8"), manifest_sha.encode("utf-8"), hashlib.sha256).hexdigest()
    if sig.get("manifest_sha256") != manifest_sha:
        return False, "manifest sha mismatch"
    if sig.get("signature") != expected:
        return False, "signature mismatch"
    return True, "ok"
