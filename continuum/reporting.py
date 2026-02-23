"""Run report rendering for shareable evidence bundles."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
from typing import Any


def ensure_report(run_dir: Path) -> Path:
    summary = _read_json(run_dir / "summary.json")
    manifest = _read_json(run_dir / "manifest.json")
    signature = _read_json(run_dir / "bundle_signature.json")
    html = render_report_html(summary=summary, manifest=manifest, signature=signature)
    report_path = run_dir / "report.html"
    report_path.write_text(html, encoding="utf-8")
    return report_path


def render_report_html(*, summary: dict[str, Any], manifest: dict[str, Any], signature: dict[str, Any] | None = None) -> str:
    run_id = str(summary.get("run_id") or manifest.get("run_id") or "unknown")
    status = str(summary.get("status") or "unknown")
    trace_id = str(summary.get("traceId") or "")
    scenario = summary.get("scenario") if isinstance(summary.get("scenario"), dict) else {}
    failure = summary.get("failure") if isinstance(summary.get("failure"), dict) else {}
    policy = summary.get("policy") if isinstance(summary.get("policy"), dict) else {}
    policy_post = policy.get("post") if isinstance(policy.get("post"), dict) else {}

    steps = summary.get("steps") if isinstance(summary.get("steps"), list) else []
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), list) else []
    generated_at = datetime.now(timezone.utc).isoformat()

    step_rows = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        attempts = step.get("attempts")
        attempts_count = len(attempts) if isinstance(attempts, list) else 0
        step_rows.append(
            "<tr>"
            f"<td>{escape(str(step.get('index', '')))}</td>"
            f"<td>{escape(str(step.get('key', '')))}</td>"
            f"<td>{escape(str(step.get('name', '')))}</td>"
            f"<td>{escape(str(step.get('type', '')))}</td>"
            f"<td>{escape(str(step.get('status', '')))}</td>"
            f"<td>{escape(str(attempts_count))}</td>"
            "</tr>"
        )

    artifact_rows = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_rows.append(
            "<tr>"
            f"<td>{escape(str(artifact.get('path', '')))}</td>"
            f"<td>{escape(str(artifact.get('size', '')))}</td>"
            f"<td><code>{escape(str(artifact.get('sha256', '')))}</code></td>"
            "</tr>"
        )

    post_violations = policy_post.get("violations") if isinstance(policy_post.get("violations"), list) else []
    policy_notes = "<br/>".join(escape(str(v)) for v in post_violations)
    if not policy_notes:
        policy_notes = "none"

    signature_manifest_hash = ""
    signature_hex = ""
    if isinstance(signature, dict):
        signature_manifest_hash = str(signature.get("manifest_sha256") or "")
        signature_hex = str(signature.get("signature") or "")

    html = """<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width,initial-scale=1'/>
  <title>Continuum Report {run_id}</title>
  <style>
    :root {{
      --bg: #f2f4f8;
      --panel: #ffffff;
      --ink: #14213d;
      --ok: #0f7b0f;
      --bad: #9b1c1c;
      --line: #d5dce7;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: linear-gradient(135deg, #f8fbff 0%, var(--bg) 100%); color: var(--ink); font-family: 'Segoe UI', 'Trebuchet MS', sans-serif; }}
    .wrap {{ max-width: 1100px; margin: 0 auto; padding: 24px; }}
    .hero {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 20px; box-shadow: 0 8px 24px rgba(20,33,61,0.06); }}
    .status {{ font-weight: 700; color: {status_color}; }}
    h1 {{ margin: 0 0 8px 0; font-size: 28px; }}
    .grid {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); margin-top: 14px; }}
    .tile {{ background: #f9fbff; border: 1px solid var(--line); border-radius: 10px; padding: 12px; }}
    .label {{ font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; opacity: 0.75; }}
    .value {{ font-size: 14px; margin-top: 4px; overflow-wrap: anywhere; }}
    section {{ background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 16px; margin-top: 16px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border: 1px solid var(--line); padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #eef4ff; }}
    code {{ font-family: Consolas, 'Courier New', monospace; font-size: 12px; }}
  </style>
</head>
<body>
  <div class='wrap'>
    <div class='hero'>
      <h1>Continuum Provable Run</h1>
      <div>Run <strong>{run_id}</strong> finished with <span class='status'>{status}</span>.</div>
      <div class='grid'>
        <div class='tile'><div class='label'>Scenario</div><div class='value'>{scenario_name}</div></div>
        <div class='tile'><div class='label'>Rail</div><div class='value'>{scenario_rail}</div></div>
        <div class='tile'><div class='label'>Trace ID</div><div class='value'>{trace_id}</div></div>
        <div class='tile'><div class='label'>Generated</div><div class='value'>{generated_at}</div></div>
      </div>
      <div class='grid'>
        <div class='tile'><div class='label'>Policy Violations</div><div class='value'>{policy_notes}</div></div>
        <div class='tile'><div class='label'>Failure</div><div class='value'>{failure_message}</div></div>
      </div>
    </div>

    <section>
      <h2>Execution Steps</h2>
      <table>
        <thead><tr><th>Index</th><th>Key</th><th>Name</th><th>Type</th><th>Status</th><th>Attempts</th></tr></thead>
        <tbody>{step_rows}</tbody>
      </table>
    </section>

    <section>
      <h2>Tamper Evidence</h2>
      <div><strong>Manifest Hash:</strong> <code>{manifest_hash}</code></div>
      <div><strong>Bundle Signature:</strong> <code>{bundle_signature}</code></div>
    </section>

    <section>
      <h2>Artifact Manifest</h2>
      <table>
        <thead><tr><th>Path</th><th>Size</th><th>SHA-256</th></tr></thead>
        <tbody>{artifact_rows}</tbody>
      </table>
    </section>
  </div>
</body>
</html>
""".format(
        run_id=escape(run_id),
        status=escape(status),
        status_color="var(--ok)" if status == "succeeded" else "var(--bad)",
        scenario_name=escape(str(scenario.get("name") or "")),
        scenario_rail=escape(str(scenario.get("rail") or "")),
        trace_id=escape(trace_id),
        generated_at=escape(generated_at),
        policy_notes=policy_notes,
        failure_message=escape(str(failure.get("message") or "none")),
        step_rows="\n".join(step_rows) or "<tr><td colspan='6'>No steps recorded.</td></tr>",
        manifest_hash=escape(signature_manifest_hash or "n/a"),
        bundle_signature=escape(signature_hex or "n/a"),
        artifact_rows="\n".join(artifact_rows) or "<tr><td colspan='3'>No artifacts listed.</td></tr>",
    )
    return html


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}
