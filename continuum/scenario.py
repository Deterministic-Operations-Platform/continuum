"""Scenario loading for YAML/JSON orchestrations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json
import re

import yaml

from continuum.errors import ScenarioValidationError


@dataclass(frozen=True, slots=True)
class ScenarioStep:
    name: str
    type: str
    with_: dict[str, Any]
    key: str = ""
    publish: dict[str, str] = field(default_factory=dict)
    always: bool = False


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    rail: str
    steps: tuple[ScenarioStep, ...]
    cleanup_steps: tuple[ScenarioStep, ...] = ()
    vars: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_mapping(data: dict[str, Any]) -> "Scenario":
        required = ("name", "rail", "steps")
        missing = [field for field in required if field not in data]
        if missing:
            raise ScenarioValidationError(f"Missing required field(s): {', '.join(missing)}")

        raw_steps = data["steps"]
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ScenarioValidationError("steps must be a non-empty array")

        raw_cleanup_steps = data.get("cleanup_steps", [])
        if raw_cleanup_steps is None:
            raw_cleanup_steps = []
        if not isinstance(raw_cleanup_steps, list):
            raise ScenarioValidationError("cleanup_steps must be an array when provided")

        raw_vars = data.get("vars", {})
        if raw_vars is None:
            raw_vars = {}
        if not isinstance(raw_vars, dict):
            raise ScenarioValidationError("vars must be a mapping when provided")

        return Scenario(
            name=str(data["name"]),
            rail=str(data["rail"]),
            steps=tuple(_parse_steps(raw_steps, label="steps")),
            cleanup_steps=tuple(_parse_steps(raw_cleanup_steps, label="cleanup_steps")),
            vars=raw_vars,
        )


def step_key(step: dict[str, Any], index: int) -> str:
    explicit_id = step.get("id")
    if isinstance(explicit_id, str) and explicit_id.strip():
        return explicit_id.strip()

    raw_name = str(step.get("name") or f"step_{index + 1}")
    slug = re.sub(r"[^a-z0-9]+", "_", raw_name.strip().lower()).strip("_")
    if not slug:
        slug = f"step_{index + 1}"
    return f"{index + 1:02d}_{slug}"


def _parse_steps(raw_steps: list[Any], *, label: str) -> list[ScenarioStep]:
    parsed_steps: list[ScenarioStep] = []
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise ScenarioValidationError(f"{label} step {index} must be a mapping")

        if {"name", "type"}.issubset(raw_step.keys()):
            step_with = raw_step.get("with", {})
            if not isinstance(step_with, dict):
                raise ScenarioValidationError(f"{label} step {index} with must be a mapping")
            publish = raw_step.get("publish", {}) or {}
            if not isinstance(publish, dict) or not all(isinstance(v, str) for v in publish.values()):
                raise ScenarioValidationError(f"{label} step {index} publish must be a mapping of string expressions")
            parsed_steps.append(
                ScenarioStep(
                    name=str(raw_step["name"]),
                    type=str(raw_step["type"]),
                    key=step_key(raw_step, index),
                    with_=step_with,
                    publish=publish,
                    always=bool(raw_step.get("always", False)),
                )
            )
            continue

        # Backward-compatible shorthand schema.
        if {"plugin", "action"}.issubset(raw_step.keys()):
            plugin = str(raw_step["plugin"])
            action = str(raw_step["action"])
            step_input = raw_step.get("input", {})
            if not isinstance(step_input, dict):
                raise ScenarioValidationError(f"{label} step {index} input must be a mapping")
            parsed_steps.append(
                ScenarioStep(
                    name=f"{plugin}.{action}",
                    type=f"legacy.{plugin}.{action}",
                    key=step_key(raw_step, index),
                    with_=step_input,
                )
            )
            continue

        if len(raw_step) != 1:
            raise ScenarioValidationError(
                f"{label} step {index} must use name/type fields, plugin/action fields, or single action mapping"
            )

        action, payload = next(iter(raw_step.items()))
        if not isinstance(payload, dict):
            raise ScenarioValidationError(f"{label} step {index} payload must be a mapping")

        plugin = str(payload.get("via", "default"))
        step_with = {k: v for k, v in payload.items() if k != "via"}
        parsed_steps.append(
            ScenarioStep(
                name=f"{plugin}.{action}",
                type=f"legacy.{plugin}.{action}",
                key=step_key(raw_step, index),
                with_=step_with,
            )
        )

    return parsed_steps


def load_scenario(path: str | Path) -> Scenario:
    scenario_path = Path(path)
    text = scenario_path.read_text(encoding="utf-8")

    suffix = scenario_path.suffix.lower()
    if suffix == ".json":
        data = json.loads(text)
    elif suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    else:
        raise ScenarioValidationError("Scenario must be .json, .yaml, or .yml")

    if not isinstance(data, dict):
        raise ScenarioValidationError("Scenario document must be a mapping")

    return Scenario.from_mapping(data)
