"""Evidence collector for run artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class StepRecord:
    index: int
    plugin: str
    action: str
    status: str
    phase: str = "execution"
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class EvidenceCollector:
    def write_run_bundle(
        self,
        *,
        run_id: str,
        scenario_source: Path,
        summary: dict[str, Any],
    ) -> Path:
        run_dir = Path("runs") / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        scenario_copy = run_dir / f"scenario{scenario_source.suffix.lower()}"
        scenario_copy.write_text(scenario_source.read_text(encoding="utf-8"), encoding="utf-8")

        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            **summary,
        }

        summary_path = run_dir / "summary.json"
        summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

        events_path = run_dir / "events.log"
        events_path.write_text(self._render_events_log(summary), encoding="utf-8")

        manifest_payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "scenario_source": str(scenario_source),
            "artifacts": [
                self._artifact_metadata(path)
                for path in sorted((scenario_copy, summary_path, events_path), key=lambda item: item.name)
            ],
        }
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest_payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        return run_dir

    def _render_events_log(self, summary: dict[str, Any]) -> str:
        lines = [f"run_id={summary['run_id']} status={summary['status']}"]
        for step in summary.get("steps", []):
            message = (
                f"phase={step.get('phase', 'execution')} step={step['index']} plugin={step['plugin']} "
                f"action={step['action']} status={step['status']}"
            )
            if step.get("error"):
                message = f"{message} error={step['error']}"
            lines.append(message)
        if summary.get("failure"):
            lines.append(
                f"failure_class={summary['failure']['class']} message={summary['failure']['message']}"
            )
        return "\n".join(lines) + "\n"

    def _artifact_metadata(self, path: Path) -> dict[str, Any]:
        file_bytes = path.read_bytes()
        return {
            "name": path.name,
            "size": len(file_bytes),
            "sha256": hashlib.sha256(file_bytes).hexdigest(),
        }
