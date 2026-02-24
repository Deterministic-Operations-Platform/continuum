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

    step_rows: list[str] = []
    timeline_items: list[str] = []
    succeeded_steps = 0
    failed_steps = 0
    skipped_steps = 0
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_status = str(step.get("status") or "unknown")
        step_tone = _status_tone(step_status)
        if step_tone == "success":
            succeeded_steps += 1
        elif step_tone == "danger":
            failed_steps += 1
        elif step_status.strip().lower() in {"skipped", "skip"}:
            skipped_steps += 1

        attempts = step.get("attempts")
        attempts_count = len(attempts) if isinstance(attempts, list) else 0
        step_rows.append(
            "<tr>"
            f"<td>{escape(str(step.get('index', '')))}</td>"
            f"<td>{escape(str(step.get('key', '')))}</td>"
            f"<td>{escape(str(step.get('name', '')))}</td>"
            f"<td>{escape(str(step.get('type', '')))}</td>"
            f"<td><span class='step-badge step-{escape(step_tone)}'>{escape(step_status)}</span></td>"
            f"<td>{escape(str(attempts_count))}</td>"
            "</tr>"
        )
        timeline_items.append(
            "<li class='timeline-item'>"
            f"<span class='timeline-dot timeline-{escape(step_tone)}'></span>"
            "<div>"
            f"<div class='timeline-title'>{escape(str(step.get('name', '')))}</div>"
            f"<div class='timeline-meta'>{escape(str(step.get('type', '')))} | status: {escape(step_status)} | attempts: {escape(str(attempts_count))}</div>"
            "</div>"
            "</li>"
        )

    artifact_rows: list[str] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_rows.append(
            "<tr>"
            f"<td class='mono'>{escape(str(artifact.get('path', '')))}</td>"
            f"<td>{escape(str(artifact.get('size', '')))}</td>"
            f"<td><code>{escape(str(artifact.get('sha256', '')))}</code></td>"
            "</tr>"
        )

    post_violations = policy_post.get("violations") if isinstance(policy_post.get("violations"), list) else []
    gate_missing = policy.get("missing") if isinstance(policy.get("missing"), list) else []
    policy_lines = [*post_violations, *[f"missing required file pattern: {item}" for item in gate_missing]]
    policy_notes = "<br/>".join(escape(str(v)) for v in policy_lines)
    if not policy_notes:
        policy_notes = "none"

    signature_manifest_hash = ""
    signature_hex = ""
    if isinstance(signature, dict):
        signature_manifest_hash = str(signature.get("manifest_sha256") or "")
        signature_hex = str(signature.get("signature") or "")

    status_tone = _status_tone(status)

    html = """<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width,initial-scale=1'/>
  <title>Continuum Report __RUN_ID__</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700;800&family=Manrope:wght@400;600;700&family=JetBrains+Mono:wght@500&display=swap');
    :root {
      --ink: #13243b;
      --ink-soft: #455e77;
      --line: #d2e1ef;
      --panel: rgba(255, 255, 255, 0.88);
      --hero-a: #061629;
      --hero-b: #13446f;
      --hero-c: #098280;
      --success: #0f7d55;
      --danger: #b53b2f;
      --active: #1268ab;
      --muted: #677483;
      --radius: 22px;
      --shadow: 0 34px 70px rgba(9, 33, 62, 0.16);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Manrope", "Aptos", "Segoe UI Variable", "Trebuchet MS", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 10% -5%, rgba(20, 101, 174, 0.26), transparent 34%),
        radial-gradient(circle at 94% 0%, rgba(4, 162, 144, 0.18), transparent 34%),
        linear-gradient(165deg, #eff5ff 0%, #f8fbff 48%, #eef5ff 100%);
      min-height: 100vh;
    }
    .wrap {
      max-width: 1180px;
      margin: 0 auto;
      padding: 26px 20px 40px;
    }
    .hero {
      border-radius: calc(var(--radius) + 8px);
      padding: 24px;
      color: #ecf6ff;
      background: linear-gradient(120deg, var(--hero-a) 0%, var(--hero-b) 60%, var(--hero-c) 100%);
      box-shadow: var(--shadow);
      position: relative;
      overflow: hidden;
      animation: riseIn 560ms cubic-bezier(.2,.8,.25,1);
    }
    .hero::after {
      content: "";
      position: absolute;
      right: -80px;
      top: -96px;
      width: 320px;
      height: 320px;
      background: radial-gradient(circle, rgba(255,255,255,0.34) 0%, transparent 65%);
    }
    h1 {
      margin: 0;
      font-family: "Space Grotesk", "Bahnschrift SemiCondensed", "Aptos Display", "Segoe UI", sans-serif;
      font-size: clamp(1.5rem, 1.25rem + 1.2vw, 2.4rem);
      letter-spacing: 0.01em;
    }
    .hero-sub {
      margin-top: 10px;
      color: rgba(236, 246, 255, 0.94);
      max-width: 820px;
    }
    .hero-grid {
      margin-top: 16px;
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }
    .hero-tile {
      border-radius: 12px;
      border: 1px solid rgba(255, 255, 255, 0.25);
      background: rgba(6, 29, 58, 0.24);
      padding: 10px 12px;
      backdrop-filter: blur(4px);
    }
    .tile-label {
      font-size: 0.72rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      opacity: 0.86;
    }
    .tile-value {
      margin-top: 4px;
      font-size: 0.96rem;
      overflow-wrap: anywhere;
    }
    .status-chip {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 5px 12px;
      border-radius: 999px;
      border: 1px solid rgba(255,255,255,0.3);
      margin-top: 10px;
      font-size: 0.76rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      font-weight: 700;
      background: rgba(6, 29, 58, 0.34);
    }
    .dashboard {
      margin-top: 16px;
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }
    .metric {
      border-radius: 14px;
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 14px 14px 12px;
      box-shadow: 0 14px 28px rgba(9, 33, 62, 0.08);
      animation: riseIn 620ms cubic-bezier(.2,.8,.25,1) both;
      animation-delay: calc(var(--i, 0) * 70ms);
    }
    .metric-label {
      font-size: 0.73rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: var(--ink-soft);
    }
    .metric-value {
      margin-top: 6px;
      font-family: "Space Grotesk", sans-serif;
      font-size: clamp(1.05rem, 0.9rem + 0.7vw, 1.5rem);
      font-weight: 700;
      color: var(--ink);
      overflow-wrap: anywhere;
    }
    section {
      margin-top: 14px;
      border-radius: var(--radius);
      border: 1px solid var(--line);
      background: var(--panel);
      box-shadow: 0 16px 32px rgba(9, 33, 62, 0.09);
      padding: 16px;
      animation: riseIn 700ms cubic-bezier(.2,.8,.25,1);
    }
    h2 {
      margin: 0 0 10px;
      font-size: 1.05rem;
      font-family: "Bahnschrift", "Aptos", sans-serif;
      letter-spacing: 0.01em;
    }
    .split {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .mini-panel {
      border-radius: 12px;
      border: 1px solid #d8e7f4;
      background: #f8fbff;
      padding: 12px;
    }
    .mini-panel .title {
      font-size: 0.74rem;
      color: var(--ink-soft);
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 6px;
    }
    .mono {
      font-family: "JetBrains Mono", "IBM Plex Mono", "Consolas", monospace;
      font-size: 0.84rem;
    }
    table {
      border-collapse: collapse;
      width: 100%;
      min-width: 760px;
    }
    .table-wrap {
      overflow-x: auto;
      border-radius: 12px;
      border: 1px solid #d8e7f4;
      background: #ffffff;
    }
    th, td {
      border-bottom: 1px solid #e5eef7;
      padding: 10px;
      text-align: left;
      vertical-align: top;
      font-size: 0.88rem;
      white-space: nowrap;
    }
    thead th {
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-size: 0.72rem;
      background: linear-gradient(180deg, #eef5fc 0%, #e8f0f9 100%);
      color: #20405f;
    }
    .step-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.07em;
      font-weight: 700;
      border: 1px solid transparent;
    }
    .step-success {
      color: #0e6f4a;
      background: #e3f8ef;
      border-color: #b7ebd3;
    }
    .step-danger {
      color: #993124;
      background: #ffe8e4;
      border-color: #f3c2bb;
    }
    .step-active {
      color: #145189;
      background: #e4f2ff;
      border-color: #bddcff;
    }
    .step-muted {
      color: #4f5b6c;
      background: #f0f3f6;
      border-color: #d8dee7;
    }
    .tone-success { color: var(--success); }
    .tone-danger { color: var(--danger); }
    .tone-active { color: var(--active); }
    .tone-muted { color: var(--muted); }
    code {
      font-family: "JetBrains Mono", "IBM Plex Mono", "Consolas", monospace;
      font-size: 0.78rem;
      background: #eff6fc;
      border: 1px solid #d7e5f3;
      border-radius: 7px;
      padding: 2px 6px;
      color: #173757;
      display: inline-block;
      max-width: 420px;
      overflow: hidden;
      text-overflow: ellipsis;
      vertical-align: middle;
    }
    .inline-block {
      display: block;
      margin-top: 8px;
      overflow-wrap: anywhere;
    }
    .timeline {
      list-style: none;
      margin: 0;
      padding: 0;
      display: grid;
      gap: 10px;
    }
    .timeline-item {
      display: grid;
      grid-template-columns: 20px 1fr;
      gap: 10px;
      align-items: start;
      border: 1px solid #dbe7f2;
      border-radius: 11px;
      background: #f8fbff;
      padding: 10px;
    }
    .timeline-dot {
      width: 12px;
      height: 12px;
      border-radius: 50%;
      margin-top: 3px;
      box-shadow: 0 0 0 3px rgba(23, 76, 128, 0.08);
    }
    .timeline-success { background: var(--success); }
    .timeline-danger { background: var(--danger); }
    .timeline-active { background: var(--active); }
    .timeline-muted { background: var(--muted); }
    .timeline-title {
      font-family: "Space Grotesk", sans-serif;
      font-size: 0.93rem;
      font-weight: 700;
      color: #1b3957;
    }
    .timeline-meta {
      margin-top: 4px;
      font-size: 0.8rem;
      color: var(--ink-soft);
      overflow-wrap: anywhere;
    }
    @media (max-width: 1060px) {
      .hero-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .dashboard { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 760px) {
      .wrap { padding: 18px 12px 28px; }
      .hero { padding: 18px 14px; }
      .hero-grid { grid-template-columns: 1fr; }
      .dashboard { grid-template-columns: 1fr; }
      .split { grid-template-columns: 1fr; }
      section { padding: 12px; }
    }
    @keyframes riseIn {
      0% {
        opacity: 0;
        transform: translateY(16px);
      }
      100% {
        opacity: 1;
        transform: translateY(0);
      }
    }
  </style>
</head>
<body>
  <div class='wrap'>
    <header class='hero'>
      <h1>Continuum Provable Run</h1>
      <div class='hero-sub'>Run <strong>__RUN_ID__</strong> completed with status <strong class='tone-__STATUS_TONE__'>__STATUS__</strong>. The report captures deterministic execution evidence and tamper checks for audit review.</div>
      <div class='status-chip'>Run Status: __STATUS__</div>
      <div class='hero-grid'>
        <div class='hero-tile'><div class='tile-label'>Scenario</div><div class='tile-value'>__SCENARIO_NAME__</div></div>
        <div class='hero-tile'><div class='tile-label'>Rail</div><div class='tile-value'>__SCENARIO_RAIL__</div></div>
        <div class='hero-tile'><div class='tile-label'>Trace ID</div><div class='tile-value mono'>__TRACE_ID__</div></div>
        <div class='hero-tile'><div class='tile-label'>Generated</div><div class='tile-value mono'>__GENERATED_AT__</div></div>
      </div>
    </header>

    <section class='dashboard'>
      <article class='metric' style='--i: 0'><div class='metric-label'>Total Steps</div><div class='metric-value'>__STEP_COUNT__</div></article>
      <article class='metric' style='--i: 1'><div class='metric-label'>Succeeded Steps</div><div class='metric-value tone-success'>__STEP_SUCCEEDED__</div></article>
      <article class='metric' style='--i: 2'><div class='metric-label'>Failed Steps</div><div class='metric-value tone-danger'>__STEP_FAILED__</div></article>
      <article class='metric' style='--i: 3'><div class='metric-label'>Skipped Steps</div><div class='metric-value tone-muted'>__STEP_SKIPPED__</div></article>
    </section>

    <section>
      <h2>Execution Timeline</h2>
      <ul class='timeline'>__TIMELINE_ITEMS__</ul>
    </section>

    <section>
      <h2>Execution Steps</h2>
      <div class='table-wrap'>
        <table>
          <thead><tr><th>Index</th><th>Key</th><th>Name</th><th>Type</th><th>Status</th><th>Attempts</th></tr></thead>
          <tbody>__STEP_ROWS__</tbody>
        </table>
      </div>
    </section>

    <section>
      <h2>Policy And Failure Signals</h2>
      <div class='split'>
        <div class='mini-panel'>
          <div class='title'>Policy Violations</div>
          <div>__POLICY_NOTES__</div>
        </div>
        <div class='mini-panel'>
          <div class='title'>Failure Message</div>
          <div>__FAILURE_MESSAGE__</div>
        </div>
      </div>
    </section>

    <section>
      <h2>Tamper Evidence</h2>
      <div class='mini-panel'>
        <div class='title'>Manifest Hash</div>
        <code class='inline-block'>__MANIFEST_HASH__</code>
      </div>
      <div class='mini-panel' style='margin-top: 10px;'>
        <div class='title'>Bundle Signature</div>
        <code class='inline-block'>__BUNDLE_SIGNATURE__</code>
      </div>
    </section>

    <section>
      <h2>Artifact Manifest</h2>
      <div class='table-wrap'>
        <table>
          <thead><tr><th>Path</th><th>Size</th><th>SHA-256</th></tr></thead>
          <tbody>__ARTIFACT_ROWS__</tbody>
        </table>
      </div>
    </section>
  </div>
</body>
</html>
"""

    html = html.replace("__RUN_ID__", escape(run_id))
    html = html.replace("__STATUS__", escape(status))
    html = html.replace("__STATUS_TONE__", escape(status_tone))
    html = html.replace("__SCENARIO_NAME__", escape(str(scenario.get("name") or "n/a")))
    html = html.replace("__SCENARIO_RAIL__", escape(str(scenario.get("rail") or "n/a")))
    html = html.replace("__TRACE_ID__", escape(trace_id or "n/a"))
    html = html.replace("__GENERATED_AT__", escape(generated_at))
    html = html.replace("__STEP_COUNT__", str(len([step for step in steps if isinstance(step, dict)])))
    html = html.replace("__STEP_SUCCEEDED__", str(succeeded_steps))
    html = html.replace("__STEP_FAILED__", str(failed_steps))
    html = html.replace("__STEP_SKIPPED__", str(skipped_steps))
    html = html.replace("__TIMELINE_ITEMS__", "\n            ".join(timeline_items) or "<li class='timeline-item'><span class='timeline-dot timeline-muted'></span><div><div class='timeline-title'>No steps recorded</div><div class='timeline-meta'>Run summary did not include step telemetry.</div></div></li>")
    html = html.replace("__STEP_ROWS__", "\n            ".join(step_rows) or "<tr><td colspan='6'>No steps recorded.</td></tr>")
    html = html.replace("__POLICY_NOTES__", policy_notes)
    html = html.replace("__FAILURE_MESSAGE__", escape(str(failure.get("message") or "none")))
    html = html.replace("__MANIFEST_HASH__", escape(signature_manifest_hash or "n/a"))
    html = html.replace("__BUNDLE_SIGNATURE__", escape(signature_hex or "n/a"))
    html = html.replace("__ARTIFACT_ROWS__", "\n            ".join(artifact_rows) or "<tr><td colspan='3'>No artifacts listed.</td></tr>")
    return html


def _status_tone(status: str) -> str:
    normalized = status.strip().lower()
    if normalized in {"succeeded", "success", "ok", "passed", "completed"}:
        return "success"
    if normalized in {"failed", "failure", "error", "exception", "infra_failed", "business_failed"}:
        return "danger"
    if normalized in {"running", "queued", "in_progress", "pending", "started"}:
        return "active"
    return "muted"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}
