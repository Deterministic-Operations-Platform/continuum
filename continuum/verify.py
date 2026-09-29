from __future__ import annotations

import json
import sys
from pathlib import Path

from continuum.signing import signature_verification_enabled, verify_bundle_signature


def cmd_verify(run_id: str, runs_dir: str) -> int:
    # Mirror publish_run's guard (continuum/publish.py) so a run id cannot
    # escape runs_dir via path traversal (e.g. "../../etc").
    if not run_id or any(sep in run_id for sep in ("..", "/", "\\")):
        raise ValueError(f"Invalid run id: {run_id!r}")

    run_dir = Path(runs_dir) / run_id
    summary_path = run_dir / "summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"summary.json not found: {summary_path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    policy = summary.get("policy") if isinstance(summary.get("policy"), dict) else {}
    policy_ok = bool(policy.get("ok"))

    try:
        verify_signature = signature_verification_enabled()
    except ValueError as err:
        print(f"Signature verification configuration error: {err}", file=sys.stderr)
        return 2

    sig_ok = True
    if verify_signature:
        sig_ok, _ = verify_bundle_signature(run_dir)
    return 0 if (policy_ok and sig_ok) else 2
