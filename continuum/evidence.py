"""Evidence collector for run artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


class EvidenceCollector:
    def step_dir(self, run_dir: Path, step_index: int, step_name: str) -> Path:
        safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in step_name)
        return run_dir / "evidence" / f"{step_index + 1:02d}-{safe_name}"

    def write_text(self, path: Path, content: str) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path)

    def write_json(self, path: Path, payload: Any) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return str(path)

    def write_run_bundle(
        self,
        *,
        run_id: str,
        scenario_source: Path,
        scenario_text: str,
        context_payload: dict[str, Any],
        summary: dict[str, Any],
    ) -> Path:
        run_dir = Path("runs") / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        (run_dir / "scenario.yaml").write_text(scenario_text, encoding="utf-8")
        (run_dir / "context.json").write_text(json.dumps(context_payload, indent=2, sort_keys=True), encoding="utf-8")
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

        manifest_payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "scenario_source": str(scenario_source),
            "artifacts": [
                self._artifact_metadata(path)
                for path in sorted((run_dir / "scenario.yaml", run_dir / "context.json", run_dir / "summary.json"), key=lambda item: item.name)
            ],
        }
        (run_dir / "manifest.json").write_text(
            json.dumps(manifest_payload, indent=2, sort_keys=True), encoding="utf-8"
        )

        return run_dir

    def _artifact_metadata(self, path: Path) -> dict[str, Any]:
        file_bytes = path.read_bytes()
        return {
            "name": path.name,
            "size": len(file_bytes),
            "sha256": hashlib.sha256(file_bytes).hexdigest(),
        }
