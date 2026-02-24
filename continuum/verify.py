from __future__ import annotations

import json
from pathlib import Path

from continuum.signing import verify_bundle_signature


def cmd_verify(run_id: str, runs_dir: str) -> int:
    run_dir = Path(runs_dir) / run_id
    summary_path = run_dir / "summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"summary.json not found: {summary_path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    policy = summary.get("policy") if isinstance(summary.get("policy"), dict) else {}
    policy_ok = bool(policy.get("ok"))

    sig_ok, _ = verify_bundle_signature(run_dir)
    return 0 if (policy_ok and sig_ok) else 2
