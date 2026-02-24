from __future__ import annotations

from pathlib import Path

from continuum.signing import keygen_ed25519


def write_keypair_ed25519(out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    priv_b64, pub_b64 = keygen_ed25519()

    priv_path = out_dir / "continuum_private.key"
    pub_path = out_dir / "continuum_public.key"

    priv_path.write_text(priv_b64 + "\n", encoding="utf-8")
    pub_path.write_text(pub_b64 + "\n", encoding="utf-8")

    try:
        priv_path.chmod(0o600)
    except Exception:
        pass

    return priv_path, pub_path
