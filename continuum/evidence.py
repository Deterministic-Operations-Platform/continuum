"""Evidence collector for run artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib
import json
import platform
import subprocess

from continuum.reporting import render_report_html


class EvidenceCollector:
    def step_dir(self, run_dir: Path, step_index: int, step_name: str) -> Path:
        safe_name = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in step_name)
        return run_dir / "evidence" / f"{step_index + 1:02d}-{safe_name}"

    def attempt_dir(self, run_dir: Path, step_index: int, step_name: str, attempt: int) -> Path:
        return self.step_dir(run_dir, step_index, step_name) / f"attempt-{attempt:02d}"

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
        manifest_payload: dict[str, Any] | None = None,
    ) -> Path:
        run_dir = Path("runs") / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "scenario.yaml").write_text(scenario_text, encoding="utf-8")
        (run_dir / "context.json").write_text(json.dumps(context_payload, indent=2, sort_keys=True), encoding="utf-8")
        (run_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

        artifacts = [
            self._artifact_metadata(path)
            for path in sorted(run_dir.rglob("*"))
            if path.is_file() and path.name not in {"manifest.json", "bundle_signature.json", "manifest.sha256"}
        ]
        artifact_set_hash = hashlib.sha256(
            json.dumps([{"path": item["path"], "sha256": item["sha256"]} for item in artifacts], sort_keys=True).encode("utf-8")
        ).hexdigest()

        manifest_data: dict[str, Any] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "scenario_source": str(scenario_source),
            "tooling": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "newman": self._command_version(["newman", "--version"]),
            },
            "integrity": {
                "algorithm": "sha256",
                "artifactSetSha256": artifact_set_hash,
            },
            "artifacts": artifacts,
        }
        if manifest_payload:
            manifest_data.update(manifest_payload)

        manifest_path = run_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_data, indent=2, sort_keys=True), encoding="utf-8")
        signature_payload = None
        signature_path = run_dir / "bundle_signature.json"
        if signature_path.is_file():
            try:
                payload = json.loads(signature_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    signature_payload = payload
            except Exception:
                signature_payload = None
        report_html = render_report_html(summary=summary, manifest=manifest_data, signature=signature_payload)
        (run_dir / "report.html").write_text(report_html, encoding="utf-8")
        return run_dir

    def _artifact_metadata(self, path: Path) -> dict[str, Any]:
        file_bytes = path.read_bytes()
        return {"path": str(path), "size": len(file_bytes), "sha256": hashlib.sha256(file_bytes).hexdigest()}

    def _command_version(self, command: list[str]) -> str | None:
        try:
            proc = subprocess.run(command, capture_output=True, text=True, check=False)
        except Exception:
            return None
        if proc.returncode != 0:
            return None
        text = (proc.stdout or proc.stderr).strip()
        return text.splitlines()[0] if text else None
