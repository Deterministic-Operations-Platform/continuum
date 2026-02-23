"""Shared session registry utilities."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import os
import signal
import subprocess

SESS_DIR = Path(".continuum")
SESS_FILE = SESS_DIR / "sessions.json"
LOCK_FILE = SESS_DIR / "sessions.lock"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@contextmanager
def file_lock() -> Any:
    """Acquire a lightweight cross-platform lock for registry writes."""
    SESS_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = LOCK_FILE.open("w", encoding="utf-8")
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            lock_file.close()


def load_sessions() -> dict[str, Any]:
    if not SESS_FILE.exists():
        return {}
    try:
        raw = json.loads(SESS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return raw if isinstance(raw, dict) else {}


def save_sessions(sessions: dict[str, Any]) -> None:
    SESS_DIR.mkdir(parents=True, exist_ok=True)
    SESS_FILE.write_text(json.dumps(sessions, indent=2), encoding="utf-8")


def fingerprint(cmd: str | None, args: list[str] | None, cwd: str | None, env_keys: list[str] | None) -> str:
    h = hashlib.sha256()
    h.update((cmd or "").encode())
    h.update(b"\n")
    h.update("\n".join(args or []).encode())
    h.update(b"\n")
    h.update((cwd or "").encode())
    for key in sorted(env_keys or []):
        h.update(b"\n")
        h.update(key.encode())
        h.update(b"=")
        h.update((os.environ.get(key) or "").encode())
    return "sha256:" + h.hexdigest()


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def kill_tree(pid: int) -> None:
    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False)
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            return
