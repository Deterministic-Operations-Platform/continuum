from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from pathlib import Path
import shutil
from typing import Any
import re


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

        status = str(summary.get("status") or "unknown")
        started = str(summary.get("startedAt") or summary.get("started_at") or "")
        ended = str(summary.get("endedAt") or summary.get("ended_at") or "")
        trace_id = str(summary.get("traceId") or context.get("vars", {}).get("traceId") or "")
        git_head = str(manifest.get("git_head") or manifest.get("gitHead") or "")

        results.append(
            PublishedRun(
                run_id=run_id,
                status=status,
                started_at=started,
                ended_at=ended,
                trace_id=trace_id,
                git_head=git_head,
                report_path=f"runs/{run_id}/report.html",
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
        }
        for item in runs
    ]
    (runs_root / "index.json").write_text(json.dumps(runs_json, indent=2, sort_keys=True), encoding="utf-8")

    rows = []
    for item in runs:
        rows.append(
            "<tr>"
            f"<td><a href='runs/{escape(item.run_id)}/report.html'>{escape(item.run_id)}</a></td>"
            f"<td>{escape(item.status)}</td>"
            f"<td>{escape(item.started_at)}</td>"
            f"<td>{escape(item.ended_at)}</td>"
            "</tr>"
        )
    html = """<!doctype html>
<html lang='en'>
<head>
  <meta charset='utf-8'/>
  <meta name='viewport' content='width=device-width,initial-scale=1'/>
  <title>Continuum Runs</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 0.5rem; text-align: left; }}
    th {{ background: #f4f4f4; }}
  </style>
</head>
<body>
  <h1>Continuum Runs</h1>
  <p>Recent published runs with direct report links.</p>
  <table>
    <thead><tr><th>Run ID</th><th>Status</th><th>Started</th><th>Ended</th></tr></thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</body>
</html>
""".format(rows="\n      ".join(rows))
    (site_dir / "index.html").write_text(html, encoding="utf-8")


def _prune_runs(runs_root: Path, keep_runs: int) -> None:
    if keep_runs <= 0 or not runs_root.exists():
        return
    run_dirs = sorted([p for p in runs_root.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
    for extra in run_dirs[keep_runs:]:
        shutil.rmtree(extra, ignore_errors=True)


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
