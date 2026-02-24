from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import shutil
from typing import Any
import re

from continuum.reporting import ensure_report


_REDACTION_PATTERNS = [
    (r"(?i)(token\s*[=:]\s*)([^\s,;]+)", r"\1[REDACTED]"),
    (r"(?i)(password\s*[=:]\s*)([^\s,;]+)", r"\1[REDACTED]"),
    (r"(?i)(cookie\s*[=:]\s*)([^\s,;]+)", r"\1[REDACTED]"),
    (r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;]+)", r"\1[REDACTED]"),
]


@dataclass
class PublishedRun:
    run_id: str
    status: str
    started_at: str
    ended_at: str
    trace_id: str
    git_head: str
    report_path: str
    signed: bool
    policy_ok: bool


def publish_run(*, run_id: str, runs_dir: Path = Path("runs"), site_dir: Path = Path("site"), keep_runs: int = 25) -> Path:
    if not run_id or any(sep in run_id for sep in ("..", "/", "\\")):
        raise ValueError(f"Invalid run id: {run_id!r}")

    source_dir = runs_dir / run_id
    if not source_dir.exists() or not source_dir.is_dir():
        raise FileNotFoundError(f"Run bundle not found: {source_dir}")

    target_dir = site_dir / "runs" / run_id
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)
    report_path = target_dir / "report.html"
    if not report_path.is_file() or _looks_generated_report(report_path):
        ensure_report(target_dir)
    _redact_tree(target_dir)

    _prune_runs(site_dir / "runs", keep_runs)
    published_runs = _collect_published_runs(site_dir)
    _write_run_indexes(site_dir, published_runs)
    return target_dir


def _read_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    data = json.loads(text)
    if isinstance(data, dict):
        return data
    return {}


def _looks_generated_report(path: Path) -> bool:
    try:
        sample = path.read_text(encoding="utf-8", errors="replace")[:8000]
    except Exception:
        return False
    lowered = sample.lower()
    return "continuum provable run" in lowered or "<title>continuum report" in lowered


def _collect_published_runs(site_dir: Path) -> list[PublishedRun]:
    results: list[PublishedRun] = []
    runs_root = site_dir / "runs"
    for summary_path in sorted(runs_root.glob("*/summary.json"), reverse=True):
        run_id = summary_path.parent.name
        summary = _read_json(summary_path)
        context_path = summary_path.parent / "context.json"
        context = _read_json(context_path) if context_path.exists() else {}
        manifest_path = summary_path.parent / "manifest.json"
        manifest = _read_json(manifest_path) if manifest_path.exists() else {}
        signature_path = summary_path.parent / "bundle_signature.json"
        signature = _read_json(signature_path) if signature_path.exists() else {}
        if not (summary_path.parent / "report.html").is_file():
            ensure_report(summary_path.parent)

        status = str(summary.get("status") or "unknown")
        started = str(summary.get("startedAt") or summary.get("started_at") or "")
        ended = str(summary.get("endedAt") or summary.get("ended_at") or "")
        trace_id = str(summary.get("traceId") or context.get("vars", {}).get("traceId") or "")
        git_head = str(manifest.get("git_head") or manifest.get("gitHead") or "")
        policy = summary.get("policy") if isinstance(summary.get("policy"), dict) else {}
        policy_post = policy.get("post") if isinstance(policy.get("post"), dict) else {}
        signed = bool(signature.get("signature"))
        policy_ok = bool(policy_post.get("ok", policy.get("ok", False)))

        results.append(
            PublishedRun(
                run_id=run_id,
                status=status,
                started_at=started,
                ended_at=ended,
                trace_id=trace_id,
                git_head=git_head,
                report_path=f"runs/{run_id}/report.html",
                signed=signed,
                policy_ok=policy_ok,
            )
        )
    return results


def _write_run_indexes(site_dir: Path, runs: list[PublishedRun]) -> None:
    site_dir.mkdir(parents=True, exist_ok=True)
    runs_root = site_dir / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)

    runs_json = [
        {
            "runId": item.run_id,
            "status": item.status,
            "startedAt": item.started_at,
            "endedAt": item.ended_at,
            "traceId": item.trace_id,
            "gitHead": item.git_head,
            "report": item.report_path,
            "signed": item.signed,
            "policyOk": item.policy_ok,
            "summary": f"runs/{item.run_id}/summary.json",
            "context": f"runs/{item.run_id}/context.json",
        }
        for item in runs
    ]
    (runs_root / "index.json").write_text(json.dumps(runs_json, indent=2, sort_keys=True), encoding="utf-8")

    succeeded_count = 0
    failed_count = 0
    active_count = 0
    other_count = 0
    rows: list[str] = []
    for item in runs:
        status_tone = _status_tone(item.status)
        if status_tone == "success":
            succeeded_count += 1
        elif status_tone == "danger":
            failed_count += 1
        elif status_tone == "active":
            active_count += 1
        else:
            other_count += 1

        search_blob = " ".join(
            [
                item.run_id,
                item.status,
                item.trace_id,
                item.git_head,
                item.started_at,
                item.ended_at,
                "signed" if item.signed else "unsigned",
                "policy ok" if item.policy_ok else "policy fail",
            ]
        ).lower()
        rows.append(
            f"<tr data-row='run' data-status='{escape(status_tone)}' data-status-value='{escape(item.status.lower())}' "
            f"data-run-id='{escape(item.run_id)}' data-status-label='{escape(item.status)}' "
            f"data-trace-id='{escape(item.trace_id)}' data-git-head='{escape(item.git_head)}' "
            f"data-started='{escape(item.started_at)}' data-ended='{escape(item.ended_at)}' "
            f"data-signed='{str(item.signed).lower()}' data-policy-ok='{str(item.policy_ok).lower()}' data-search='{escape(search_blob)}'>"
            f"<td class='select-cell'><input type='checkbox' class='compare-check' aria-label='Select {escape(item.run_id)} for compare'/></td>"
            f"<td><a class='run-link' href='runs/{escape(item.run_id)}/report.html'>{escape(item.run_id)}</a></td>"
            f"<td><span class='status-badge status-{escape(status_tone)}'>{escape(item.status)}</span></td>"
            f"<td class='mono'>{escape(item.trace_id) or 'n/a'}</td>"
            f"<td><code>{escape(item.git_head) or 'n/a'}</code></td>"
            f"<td>{'Yes' if item.signed else 'No'}</td>"
            f"<td>{'Yes' if item.policy_ok else 'No'}</td>"
            f"<td class='mono'>{escape(item.started_at) or 'n/a'}</td>"
            f"<td class='mono'>{escape(item.ended_at) or 'n/a'}</td>"
            f"<td><a href='runs/{escape(item.run_id)}/summary.json'>summary</a> | "
            f"<a href='runs/{escape(item.run_id)}/context.json'>context</a></td>"
            "</tr>"
        )

    html = """<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width,initial-scale=1'/>
  <title>Continuum Evidence Viewer</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700;800&family=Manrope:wght@400;600;700&family=JetBrains+Mono:wght@500&display=swap');
    :root {
      --ink: #12243a;
      --ink-soft: #3e566f;
      --panel: rgba(255, 255, 255, 0.90);
      --line: #cfdeed;
      --hero-a: #06162c;
      --hero-b: #0d3b63;
      --hero-c: #097f7d;
      --radius: 22px;
      --shadow: 0 34px 78px rgba(7, 26, 52, 0.18);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Manrope", "Aptos", "Segoe UI Variable", "Trebuchet MS", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 10% -10%, rgba(26, 105, 188, 0.34), transparent 35%),
        radial-gradient(circle at 90% 0%, rgba(4, 169, 153, 0.22), transparent 40%),
        linear-gradient(160deg, #edf3fc 0%, #f9fbff 52%, #ebf3fc 100%);
      min-height: 100vh;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image: linear-gradient(transparent 97%, rgba(16, 46, 80, 0.06) 98%);
      background-size: 100% 38px;
      opacity: 0.25;
      z-index: -1;
    }
    .shell {
      max-width: 1280px;
      margin: 0 auto;
      padding: 28px 20px 44px;
    }
    .hero {
      position: relative;
      overflow: hidden;
      border-radius: calc(var(--radius) + 8px);
      padding: 26px 24px;
      background: linear-gradient(118deg, var(--hero-a) 0%, var(--hero-b) 58%, var(--hero-c) 100%);
      color: #eaf6ff;
      box-shadow: var(--shadow);
      animation: riseIn 560ms cubic-bezier(.2,.8,.25,1);
    }
    .hero::after {
      content: "";
      position: absolute;
      width: 280px;
      height: 280px;
      right: -70px;
      top: -90px;
      background: radial-gradient(circle, rgba(255, 255, 255, 0.38) 0%, transparent 65%);
      pointer-events: none;
    }
    .eyebrow {
      margin: 0 0 6px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.72rem;
      font-weight: 700;
      color: rgba(234, 246, 255, 0.78);
    }
    .hero h1 {
      margin: 0;
      font-family: "Space Grotesk", "Bahnschrift SemiCondensed", "Aptos Display", "Segoe UI", sans-serif;
      font-size: clamp(1.75rem, 1.4rem + 1.4vw, 2.7rem);
      letter-spacing: 0.01em;
    }
    .hero p {
      margin: 10px 0 0;
      max-width: 820px;
      color: rgba(234, 246, 255, 0.92);
    }
    .hero-meta {
      margin-top: 18px;
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      font-size: 0.92rem;
      color: rgba(234, 246, 255, 0.95);
    }
    .meta-pill {
      padding: 6px 10px;
      border-radius: 999px;
      border: 1px solid rgba(255, 255, 255, 0.25);
      background: rgba(5, 25, 52, 0.24);
      backdrop-filter: blur(3px);
    }
    .cards {
      margin-top: 16px;
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
    }
    .card {
      padding: 14px 14px 12px;
      border-radius: 14px;
      border: 1px solid rgba(255, 255, 255, 0.22);
      background: rgba(4, 25, 49, 0.24);
      animation: riseIn 620ms cubic-bezier(.2,.8,.25,1) both;
      animation-delay: calc(var(--i, 0) * 70ms);
    }
    .card-label {
      font-size: 0.74rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      opacity: 0.86;
    }
    .card-value {
      margin-top: 6px;
      font-family: "Space Grotesk", sans-serif;
      font-size: clamp(1.1rem, 0.95rem + 0.8vw, 1.6rem);
      font-weight: 700;
    }
    .workspace {
      margin-top: 16px;
      padding: 18px;
      border-radius: var(--radius);
      border: 1px solid var(--line);
      background: var(--panel);
      backdrop-filter: blur(6px);
      box-shadow: 0 22px 42px rgba(12, 30, 56, 0.10);
      animation: riseIn 720ms cubic-bezier(.2,.8,.25,1);
    }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 12px;
    }
    .search-block {
      flex: 1 1 300px;
      min-width: 240px;
    }
    .search-block input {
      width: 100%;
      border: 1px solid #b8cce0;
      border-radius: 999px;
      padding: 10px 14px;
      font-size: 0.95rem;
      background: #f7fbff;
      color: var(--ink);
      outline: none;
    }
    .search-block input:focus {
      border-color: #2276b6;
      box-shadow: 0 0 0 3px rgba(34, 118, 182, 0.18);
    }
    .status-filters {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .status-pill {
      border: 1px solid #b7c8db;
      background: #ffffff;
      color: #1f3852;
      border-radius: 999px;
      padding: 7px 12px;
      font-size: 0.84rem;
      font-weight: 600;
      cursor: pointer;
      transition: all 180ms ease;
    }
    .status-pill:hover {
      transform: translateY(-1px);
      border-color: #8caecd;
    }
    .status-pill[aria-pressed='true'] {
      background: #0f3964;
      color: #f0f8ff;
      border-color: #0f3964;
    }
    .controls {
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }
    .controls select {
      border-radius: 10px;
      border: 1px solid #b7c8db;
      padding: 8px 10px;
      background: #ffffff;
      color: #1f3852;
    }
    .visible-count {
      color: var(--ink-soft);
      font-size: 0.88rem;
    }
    .table-wrap {
      margin-top: 8px;
      overflow-x: auto;
      border: 1px solid #c8d9ea;
      border-radius: 14px;
      background: #ffffff;
    }
    table {
      border-collapse: collapse;
      width: 100%;
      min-width: 860px;
    }
    thead th {
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-size: 0.72rem;
      background: linear-gradient(180deg, #edf4fc 0%, #e6eff9 100%);
      color: #20405f;
    }
    th, td {
      border-bottom: 1px solid #e2ebf4;
      padding: 11px 10px;
      text-align: left;
      vertical-align: top;
      font-size: 0.86rem;
      white-space: nowrap;
    }
    tbody tr {
      transition: background-color 140ms ease, transform 140ms ease;
    }
    tbody tr:hover {
      background: #f4f9ff;
      transform: translateY(-1px);
    }
    .run-link {
      font-family: "Space Grotesk", sans-serif;
      font-weight: 700;
      color: #0f4c81;
      text-decoration: none;
    }
    .run-link:hover { text-decoration: underline; }
    .status-badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      border-radius: 999px;
      padding: 4px 10px;
      font-size: 0.76rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      border: 1px solid transparent;
    }
    .status-success {
      color: #0c6d48;
      background: #e3f8ef;
      border-color: #b7ebd3;
    }
    .status-danger {
      color: #993124;
      background: #ffe8e4;
      border-color: #f3c2bb;
    }
    .status-active {
      color: #145189;
      background: #e4f2ff;
      border-color: #bddcff;
    }
    .status-muted {
      color: #4f5b6c;
      background: #f0f3f6;
      border-color: #d8dee7;
    }
    .mono {
      font-family: "JetBrains Mono", "IBM Plex Mono", "Consolas", monospace;
      font-size: 0.82rem;
    }
    code {
      font-family: "JetBrains Mono", "IBM Plex Mono", "Consolas", monospace;
      font-size: 0.78rem;
      color: #173757;
      background: #f0f6fc;
      padding: 2px 6px;
      border-radius: 6px;
      border: 1px solid #d7e5f3;
      display: inline-block;
      max-width: 320px;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    a {
      color: #0f4c81;
      font-weight: 600;
    }
    #emptyRow td {
      text-align: center;
      color: var(--ink-soft);
      padding: 24px;
      font-size: 0.95rem;
    }
    .select-cell {
      width: 38px;
      text-align: center;
    }
    .compare-check {
      width: 15px;
      height: 15px;
      accent-color: #1b6fb6;
      cursor: pointer;
    }
    tbody tr.is-selected {
      box-shadow: inset 3px 0 0 #1b6fb6;
      background: #edf6ff;
    }
    .compare-panel {
      margin-top: 12px;
      border: 1px solid #d4e2ef;
      border-radius: 14px;
      background: #ffffff;
      padding: 12px;
    }
    .compare-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
    }
    .compare-head h2 {
      margin: 0;
      font-family: "Space Grotesk", sans-serif;
      font-size: 1rem;
    }
    .compare-hint {
      margin: 6px 0;
      color: var(--ink-soft);
      font-size: 0.85rem;
    }
    .compare-grid {
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .compare-card {
      border: 1px solid #dbe7f3;
      border-radius: 10px;
      background: #f9fcff;
      padding: 10px;
    }
    .compare-card .title {
      font-family: "Space Grotesk", sans-serif;
      font-weight: 700;
      color: #1f3f5f;
      font-size: 0.9rem;
    }
    .kv {
      margin-top: 6px;
      display: grid;
      gap: 4px;
      font-size: 0.79rem;
    }
    .kv-row {
      display: grid;
      grid-template-columns: 84px 1fr;
      gap: 8px;
    }
    .kv-row .k {
      text-transform: uppercase;
      letter-spacing: 0.06em;
      font-size: 0.66rem;
      font-weight: 700;
      color: #536a80;
    }
    .kv-row .v {
      color: #1f3b58;
      overflow-wrap: anywhere;
    }
    .diff-table {
      margin-top: 8px;
      border: 1px solid #dbe7f3;
      border-radius: 10px;
      overflow: hidden;
    }
    .diff-table table {
      min-width: 0;
      width: 100%;
    }
    .diff-table thead th {
      position: static;
      font-size: 0.66rem;
      background: #ecf4fc;
    }
    .diff-table td {
      white-space: normal;
      font-size: 0.78rem;
      padding: 8px;
    }
    .changed {
      background: #fff2df;
      color: #765100;
      font-weight: 700;
    }
    @media (max-width: 1080px) {
      .cards { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    }
    @media (max-width: 760px) {
      .shell { padding: 18px 12px 26px; }
      .hero { padding: 20px 16px; }
      .workspace { padding: 14px; }
      .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .hero-meta { gap: 8px; }
    }
    @media (max-width: 520px) {
      .cards { grid-template-columns: 1fr; }
      .toolbar { gap: 10px; }
      .status-filters { width: 100%; }
      .controls { width: 100%; justify-content: space-between; }
      .compare-grid { grid-template-columns: 1fr; }
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
  <div class='shell'>
    <section class='hero'>
      <p class='eyebrow'>Operational Audit Fabric</p>
      <h1>Continuum Evidence Viewer</h1>
      <p>Deterministic run intelligence with audit-grade traceability. Compare runs by status, trace ID, and git head in one executive control room.</p>
      <div class='hero-meta'>
        <span class='meta-pill'>Index Source: <code>site/runs/index.json</code></span>
        <span class='meta-pill'>Published Runs: <strong id='totalRuns'>__RUN_COUNT__</strong></span>
        <span class='meta-pill'>Visible Rows: <strong id='visibleCount'>__RUN_COUNT__</strong></span>
        <span class='meta-pill'>Success Rate: <strong id='successRate'>__SUCCESS_RATE__%</strong></span>
      </div>
      <div class='cards'>
        <article class='card' style='--i: 0'><div class='card-label'>Succeeded</div><div class='card-value'>__SUCCEEDED_COUNT__</div></article>
        <article class='card' style='--i: 1'><div class='card-label'>Failed</div><div class='card-value'>__FAILED_COUNT__</div></article>
        <article class='card' style='--i: 2'><div class='card-label'>Active</div><div class='card-value'>__ACTIVE_COUNT__</div></article>
        <article class='card' style='--i: 3'><div class='card-label'>Other</div><div class='card-value'>__OTHER_COUNT__</div></article>
        <article class='card' style='--i: 4'><div class='card-label'>Compare Data</div><div class='card-value'>Trace + Git</div></article>
      </div>
    </section>
    <section class='workspace'>
      <div class='toolbar'>
        <div class='search-block'>
          <input id='q' type='search' placeholder='Filter by run ID, status, trace ID, git head, or timestamp'/>
        </div>
        <div class='status-filters' role='group' aria-label='Status filters'>
          <button type='button' class='status-pill' data-status='all' aria-pressed='true'>All</button>
          <button type='button' class='status-pill' data-status='success' aria-pressed='false'>Succeeded</button>
          <button type='button' class='status-pill' data-status='danger' aria-pressed='false'>Failed</button>
          <button type='button' class='status-pill' data-status='active' aria-pressed='false'>Active</button>
          <button type='button' class='status-pill' data-status='muted' aria-pressed='false'>Other</button>
        </div>
        <div class='controls'>
          <label for='sort'>Sort</label>
          <select id='sort'>
            <option value='newest'>Newest started</option>
            <option value='oldest'>Oldest started</option>
            <option value='status'>Status (A-Z)</option>
            <option value='run'>Run ID (A-Z)</option>
          </select>
          <span class='visible-count'>Live filter enabled</span>
        </div>
      </div>
      <div class='table-wrap'>
        <table id='runs'>
          <thead><tr><th>Select</th><th>Run ID</th><th>Status</th><th>Trace ID</th><th>Git HEAD</th><th>Signed?</th><th>Policy OK?</th><th>Started</th><th>Ended</th><th>Compare Data</th></tr></thead>
          <tbody>
            __ROWS__
            <tr id='emptyRow' hidden><td colspan='8'>No runs match the current filter.</td></tr>
          </tbody>
        </table>
      </div>
      <section class='compare-panel'>
        <div class='compare-head'>
          <h2>Compare Workbench</h2>
          <p class='compare-hint'><strong id='compareCount'>0</strong> / 2 selected</p>
        </div>
        <p id='compareHint' class='compare-hint'>Select up to two runs to compare status, trace, and git metadata.</p>
        <div class='compare-grid' id='compareGrid'></div>
        <div class='diff-table' id='diffTable' hidden></div>
      </section>
    </section>
  </div>
  <script>
    const rows = Array.from(document.querySelectorAll("#runs tbody tr[data-row='run']"));
    const qInput = document.getElementById("q");
    const sortSelect = document.getElementById("sort");
    const emptyRow = document.getElementById("emptyRow");
    const visibleCount = document.getElementById("visibleCount");
    const pills = Array.from(document.querySelectorAll(".status-pill"));
    const compareCount = document.getElementById("compareCount");
    const compareHint = document.getElementById("compareHint");
    const compareGrid = document.getElementById("compareGrid");
    const diffTable = document.getElementById("diffTable");

    const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    })[char]);

    function activeStatus() {
      const active = pills.find((pill) => pill.getAttribute("aria-pressed") === "true");
      return active ? active.dataset.status : "all";
    }

    function toTime(value) {
      const parsed = Date.parse(value || "");
      return Number.isFinite(parsed) ? parsed : 0;
    }

    function selectedRows() {
      return rows.filter((row) => {
        const input = row.querySelector(".compare-check");
        return Boolean(input && input.checked);
      });
    }

    function rowData(row) {
      return {
        runId: row.dataset.runId || "",
        status: row.dataset.statusLabel || "",
        traceId: row.dataset.traceId || "",
        gitHead: row.dataset.gitHead || "",
        signed: row.dataset.signed || "false",
        policyOk: row.dataset.policyOk || "false",
        started: row.dataset.started || "",
        ended: row.dataset.ended || ""
      };
    }

    function renderCompare() {
      const selected = selectedRows().map(rowData);
      compareCount.textContent = String(selected.length);

      rows.forEach((row) => {
        const input = row.querySelector(".compare-check");
        row.classList.toggle("is-selected", Boolean(input && input.checked));
      });

      if (selected.length === 0) {
        compareHint.textContent = "Select up to two runs to compare status, trace, and git metadata.";
        compareGrid.innerHTML = "";
        diffTable.hidden = true;
        diffTable.innerHTML = "";
        return;
      }

      compareGrid.innerHTML = selected
        .map((item) => `
          <article class='compare-card'>
            <div class='title'>${esc(item.runId)}</div>
            <div class='kv'>
              <div class='kv-row'><span class='k'>Status</span><span class='v'>${esc(item.status || "n/a")}</span></div>
              <div class='kv-row'><span class='k'>Trace</span><span class='v mono'>${esc(item.traceId || "n/a")}</span></div>
              <div class='kv-row'><span class='k'>Git</span><span class='v mono'>${esc(item.gitHead || "n/a")}</span></div>
              <div class='kv-row'><span class='k'>Signed</span><span class='v'>${esc(item.signed)}</span></div>
              <div class='kv-row'><span class='k'>Policy OK</span><span class='v'>${esc(item.policyOk)}</span></div>
              <div class='kv-row'><span class='k'>Start</span><span class='v mono'>${esc(item.started || "n/a")}</span></div>
            </div>
          </article>
        `)
        .join("");

      if (selected.length === 1) {
        compareHint.textContent = "Select one more run for a side-by-side diff.";
        diffTable.hidden = true;
        diffTable.innerHTML = "";
        return;
      }

      compareHint.textContent = "Live diff for selected runs.";
      const fields = [
        ["Status", selected[0].status, selected[1].status],
        ["Trace ID", selected[0].traceId, selected[1].traceId],
        ["Git HEAD", selected[0].gitHead, selected[1].gitHead],
        ["Signed", selected[0].signed, selected[1].signed],
        ["Policy OK", selected[0].policyOk, selected[1].policyOk],
        ["Started", selected[0].started, selected[1].started],
        ["Ended", selected[0].ended, selected[1].ended]
      ];
      const diffRows = fields
        .map(([label, left, right]) => {
          const changed = String(left || "") !== String(right || "");
          return `
            <tr>
              <td>${esc(label)}</td>
              <td class='${changed ? "changed" : ""}'>${esc(left || "n/a")}</td>
              <td class='${changed ? "changed" : ""}'>${esc(right || "n/a")}</td>
            </tr>
          `;
        })
        .join("");
      diffTable.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>Field</th>
              <th>${esc(selected[0].runId)}</th>
              <th>${esc(selected[1].runId)}</th>
            </tr>
          </thead>
          <tbody>${diffRows}</tbody>
        </table>
      `;
      diffTable.hidden = false;
    }

    function enforceCompareLimit(target) {
      const checked = selectedRows();
      if (checked.length <= 2) {
        return true;
      }
      target.checked = false;
      return false;
    }

    function applySort() {
      const tbody = document.querySelector("#runs tbody");
      const mode = sortSelect.value;
      const sorted = [...rows].sort((left, right) => {
        if (mode === "oldest") {
          return toTime(left.dataset.started) - toTime(right.dataset.started);
        }
        if (mode === "status") {
          const byStatus = (left.dataset.statusValue || "").localeCompare(right.dataset.statusValue || "");
          return byStatus || (left.dataset.runId || "").localeCompare(right.dataset.runId || "");
        }
        if (mode === "run") {
          return (left.dataset.runId || "").localeCompare(right.dataset.runId || "");
        }
        return toTime(right.dataset.started) - toTime(left.dataset.started);
      });
      for (const row of sorted) {
        tbody.appendChild(row);
      }
      tbody.appendChild(emptyRow);
    }

    function applyFilters() {
      const query = (qInput.value || "").trim().toLowerCase();
      const status = activeStatus();
      let visible = 0;

      for (const row of rows) {
        const matchesStatus = status === "all" || row.dataset.status === status;
        const matchesQuery = !query || (row.dataset.search || "").includes(query);
        const show = matchesStatus && matchesQuery;
        row.hidden = !show;
        if (show) {
          visible += 1;
        }
      }

      visibleCount.textContent = String(visible);
      emptyRow.hidden = visible !== 0;
    }

    for (const pill of pills) {
      pill.addEventListener("click", () => {
        for (const other of pills) {
          other.setAttribute("aria-pressed", other === pill ? "true" : "false");
        }
        applyFilters();
      });
    }

    for (const check of document.querySelectorAll(".compare-check")) {
      check.addEventListener("change", (event) => {
        if (!enforceCompareLimit(event.target)) {
          return;
        }
        renderCompare();
      });
    }

    qInput.addEventListener("input", applyFilters);
    sortSelect.addEventListener("change", () => {
      applySort();
      applyFilters();
    });

    applySort();
    applyFilters();
    renderCompare();
  </script>
</body>
</html>
"""

    run_count = len(runs)
    success_rate = int(round((succeeded_count / run_count) * 100)) if run_count else 0

    html = html.replace("__ROWS__", "\n            ".join(rows))
    html = html.replace("__RUN_COUNT__", str(run_count))
    html = html.replace("__SUCCESS_RATE__", str(success_rate))
    html = html.replace("__SUCCEEDED_COUNT__", str(succeeded_count))
    html = html.replace("__FAILED_COUNT__", str(failed_count))
    html = html.replace("__ACTIVE_COUNT__", str(active_count))
    html = html.replace("__OTHER_COUNT__", str(other_count))
    (site_dir / "index.html").write_text(html, encoding="utf-8")


def _prune_runs(runs_root: Path, keep_runs: int) -> None:
    if keep_runs <= 0 or not runs_root.exists():
        return
    run_dirs = sorted([p for p in runs_root.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
    for extra in run_dirs[keep_runs:]:
        shutil.rmtree(extra, ignore_errors=True)


def _status_tone(status: str) -> str:
    normalized = status.strip().lower()
    if normalized in {"succeeded", "success", "ok", "passed", "completed"}:
        return "success"
    if normalized in {"failed", "failure", "error", "exception", "infra_failed", "business_failed"}:
        return "danger"
    if normalized in {"running", "queued", "in_progress", "pending", "started"}:
        return "active"
    return "muted"


def _redact_tree(path: Path) -> None:
    for file_path in path.rglob("*"):
        if not file_path.is_file():
            continue
        if file_path.name.endswith((".tmp", ".bak")) or file_path.name == "debug.tmp":
            file_path.unlink(missing_ok=True)
            continue
        if file_path.suffix.lower() in {".json", ".log", ".txt", ".html", ".yaml", ".yml"}:
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            redacted = text
            for pattern, repl in _REDACTION_PATTERNS:
                redacted = re.sub(pattern, repl, redacted)
            if redacted != text:
                file_path.write_text(redacted, encoding="utf-8")
