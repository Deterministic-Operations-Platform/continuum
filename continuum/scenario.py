"""Scenario loading for YAML/JSON orchestrations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json

import yaml

from continuum.errors import ScenarioValidationError


@dataclass(frozen=True, slots=True)
class ScenarioStep:
    name: str
    type: str
    with_: dict[str, Any]
    publish: dict[str, str]


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    rail: str
    steps: tuple[ScenarioStep, ...]
    cleanup_steps: tuple[ScenarioStep, ...]
    vars: dict[str, Any]

    @staticmethod
    def from_mapping(data: dict[str, Any]) -> "Scenario":
        required = ("name", "rail", "steps")
        missing = [field for field in required if field not in data]
        if missing:
            raise ScenarioValidationError(f"Missing required field(s): {', '.join(missing)}")

        raw_steps = data["steps"]
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ScenarioValidationError("steps must be a non-empty array")

        parsed_steps = Scenario._parse_steps(raw_steps, label="steps")
        raw_cleanup_steps = data.get("cleanup_steps", [])
        if raw_cleanup_steps is None:
            raw_cleanup_steps = []
        if not isinstance(raw_cleanup_steps, list):
            raise ScenarioValidationError("cleanup_steps must be an array when provided")
        parsed_cleanup_steps = Scenario._parse_steps(raw_cleanup_steps, label="cleanup_steps")

        raw_vars = data.get("vars", {})
        if raw_vars is None:
            raw_vars = {}
        if not isinstance(raw_vars, dict):
            raise ScenarioValidationError("vars must be a mapping when provided")

        return Scenario(
            name=str(data["name"]),
            rail=str(data["rail"]),
            steps=tuple(parsed_steps),
            cleanup_steps=tuple(parsed_cleanup_steps),
            vars=raw_vars,
        )

    @staticmethod
    def _parse_steps(raw_steps: list[Any], *, label: str) -> list[ScenarioStep]:
        parsed_steps: list[ScenarioStep] = []
        for index, raw_step in enumerate(raw_steps):
            if not isinstance(raw_step, dict):
                raise ScenarioValidationError(f"{label} step {index} must be a mapping")

            if {"name", "type"}.issubset(raw_step.keys()):
                name = str(raw_step["name"])
                step_type = str(raw_step["type"])
                step_with = raw_step.get("with", {})
                if not isinstance(step_with, dict):
                    raise ScenarioValidationError(f"{label} step {index} with must be a mapping")
                publish = raw_step.get("publish", {})
                if publish is None:
                    publish = {}
                if not isinstance(publish, dict) or not all(isinstance(v, str) for v in publish.values()):
                    raise ScenarioValidationError(f"{label} step {index} publish must be a mapping of string expressions")
                parsed_steps.append(ScenarioStep(name=name, type=step_type, with_=step_with, publish=publish))
                continue

            # Backward-compat support for legacy plugin/action schema.
            if {"plugin", "action"}.issubset(raw_step.keys()):
                plugin = str(raw_step["plugin"])
                action = str(raw_step["action"])
                step_input = raw_step.get("input", {})
                if not isinstance(step_input, dict):
                    raise ScenarioValidationError(f"{label} step {index} input must be a mapping")
                parsed_steps.append(
                    ScenarioStep(name=f"{plugin}.{action}", type=f"legacy.{plugin}.{action}", with_=step_input, publish={})
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
                ScenarioStep(name=f"{plugin}.{action}", type=f"legacy.{plugin}.{action}", with_=step_with, publish={})
            )
        return parsed_steps


def normalize_retry(raw_step: dict[str, Any]) -> dict[str, Any] | None:
    retry_raw = raw_step.get("retry")
    if retry_raw is None and "retries" in raw_step:
        retry_raw = {"maxAttempts": int(raw_step["retries"]) + 1}

    if not retry_raw:
        return None

    if not isinstance(retry_raw, dict):
        raise ScenarioValidationError("retry must be a mapping")

    retry_on = retry_raw.get("on", ["exception"])
    if isinstance(retry_on, str):
        retry_on = [retry_on]
    if not isinstance(retry_on, list) or not all(isinstance(item, str) for item in retry_on):
        raise ScenarioValidationError("retry.on must be a list of strings")

    return {
        "on": retry_on,
        "maxAttempts": int(retry_raw.get("maxAttempts", 1)),
        "backoff": str(retry_raw.get("backoff", "fixed")),
        "baseDelayMs": int(retry_raw.get("baseDelayMs", 250)),
        "maxDelayMs": int(retry_raw.get("maxDelayMs", 10_000)),
        "jitter": float(retry_raw.get("jitter", 0.0)),
    }


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
