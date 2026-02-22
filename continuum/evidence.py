"""Evidence collector for run artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json


@dataclass(slots=True)
class StepRecord:
    index: int
    plugin: str
    action: str
    status: str
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
        (run_dir / "summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return run_dir
