"""Dependency and environment preflight helpers."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from typing import Any


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def try_cmd(cmd: list[str]) -> str | None:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return out.strip()
    except Exception:  # noqa: BLE001
        return None


def gather_versions() -> dict[str, Any]:
    return {
        "python": sys.version.replace("\n", " "),
        "platform": platform.platform(),
        "exes": {
            "node": which("node"),
            "newman": which("newman"),
            "git": which("git"),
        },
        "versions": {
            "node": try_cmd(["node", "--version"]),
            "newman": try_cmd(["newman", "--version"]),
            "git_head": try_cmd(["git", "rev-parse", "HEAD"]),
        },
    }


def env_presence(keys: list[str]) -> dict[str, bool]:
    return {key: bool(os.environ.get(key)) for key in keys}

