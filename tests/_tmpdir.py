from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_TMP_ROOT = Path(
    os.environ.get("CONTINUUM_TEST_TMP_ROOT", str(_REPO_ROOT / "tests_tmp"))
).resolve()


def make_temp_dir(prefix: str) -> Path:
    _TMP_ROOT.mkdir(parents=True, exist_ok=True)
    path = _TMP_ROOT / f"{prefix}-{uuid.uuid4().hex[:10]}"
    path.mkdir(parents=True, exist_ok=False)
    return path


def remove_temp_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
