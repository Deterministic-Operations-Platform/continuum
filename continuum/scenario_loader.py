"""YAML scenario loader for the Continuum CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class Scenario:
    name: str
    rail: str
    lifecycle_start: list[str]
    steps: list[dict[str, Any]]
    evidence_export: str
    raw: dict[str, Any]


class ScenarioLoader:
    """Load and minimally validate scenario YAML documents."""

    def load(self, path: str | Path) -> Scenario:
        scenario_path = Path(path)
        with scenario_path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)

        if not isinstance(payload, dict):
            raise ValueError("Scenario YAML must contain a top-level mapping.")

        name = payload.get("name")
        rail = payload.get("rail")
        steps = payload.get("steps")

        if not isinstance(name, str) or not name.strip():
            raise ValueError("Scenario field 'name' must be a non-empty string.")
        if not isinstance(rail, str) or not rail.strip():
            raise ValueError("Scenario field 'rail' must be a non-empty string.")
        if not isinstance(steps, list):
            raise ValueError("Scenario field 'steps' must be an array.")

        lifecycle = payload.get("lifecycle")
        lifecycle_start: list[str] = []
        if isinstance(lifecycle, dict):
            raw_start = lifecycle.get("start", [])
            if not isinstance(raw_start, list):
                raise ValueError("Scenario field 'lifecycle.start' must be an array.")
            lifecycle_start = [str(item) for item in raw_start]

        evidence = payload.get("evidence")
        evidence_export = ""
        if isinstance(evidence, dict):
            export_value = evidence.get("export", "")
            evidence_export = str(export_value) if export_value is not None else ""

        return Scenario(
            name=name,
            rail=rail,
            lifecycle_start=lifecycle_start,
            steps=steps,
            evidence_export=evidence_export,
            raw=payload,
        )
