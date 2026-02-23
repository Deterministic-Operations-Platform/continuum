"""Scenario loading for YAML/JSON orchestrations."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any

import yaml

from continuum.errors import ScenarioValidationError


@dataclass(frozen=True, slots=True)
class ScenarioStep:
    name: str
    type: str
    with_: dict[str, Any]
    publish: dict[str, str] | None = None
    key: str = ""
    always: bool = False
    retry: dict[str, Any] | None = None
    legacy_retry_used: bool = False


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    rail: str
    steps: tuple[ScenarioStep, ...]
    vars: dict[str, Any]
    cleanup_steps: tuple[ScenarioStep, ...] = ()

    @staticmethod
    def from_mapping(data: dict[str, Any]) -> "Scenario":
        required = ("name", "rail", "steps")
        missing = [field for field in required if field not in data]
        if missing:
            raise ScenarioValidationError(f"Missing required field(s): {', '.join(missing)}")

        raw_steps = data["steps"]
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ScenarioValidationError("steps must be a non-empty array")

        raw_vars = data.get("vars") or {}
        if not isinstance(raw_vars, dict):
            raise ScenarioValidationError("vars must be a mapping when provided")

        raw_cleanup = data.get("cleanup_steps") or []
        if not isinstance(raw_cleanup, list):
            raise ScenarioValidationError("cleanup_steps must be an array when provided")

        return Scenario(
            name=str(data["name"]),
            rail=str(data["rail"]),
            steps=tuple(_parse_steps(raw_steps, label="steps")),
            cleanup_steps=tuple(_parse_steps(raw_cleanup, label="cleanup_steps")),
            vars=raw_vars,
        )


def step_key(step: dict[str, Any], index: int) -> str:
    explicit_id = step.get("id")
    if isinstance(explicit_id, str) and explicit_id.strip():
        return explicit_id.strip()
    raw_name = str(step.get("name") or f"step_{index + 1}")
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", raw_name).strip("_")
    return f"{index + 1:02d}_{slug or f'step_{index + 1}'}"


def normalize_retry(raw_step: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    legacy_used = False
    retry_raw = raw_step.get("retry")

    step_with = raw_step.get("with") if isinstance(raw_step.get("with"), dict) else {}
    if retry_raw is None and isinstance(step_with, dict) and ("retries" in step_with or "backoffMs" in step_with):
        retry_raw = {
            "maxAttempts": int(step_with.get("retries", 0)) + 1,
            "baseDelayMs": int(step_with.get("backoffMs", 0)),
            "maxDelayMs": int(step_with.get("backoffMs", 0)),
            "backoff": "fixed",
            "jitter": 0.0,
            "on": ["exception"],
        }
        legacy_used = True

    if retry_raw is None:
        return None, legacy_used
    if not isinstance(retry_raw, dict):
        raise ScenarioValidationError("retry must be a mapping")

    retry_on = retry_raw.get("on", ["exception"])
    if isinstance(retry_on, str):
        retry_on = [retry_on]
    if not isinstance(retry_on, list) or not all(isinstance(i, str) for i in retry_on):
        raise ScenarioValidationError("retry.on must be a list of strings")

    return {
        "on": retry_on,
        "maxAttempts": max(1, int(retry_raw.get("maxAttempts", 1))),
        "backoff": str(retry_raw.get("backoff", "fixed")),
        "baseDelayMs": max(0, int(retry_raw.get("baseDelayMs", 0))),
        "maxDelayMs": max(0, int(retry_raw.get("maxDelayMs", retry_raw.get("baseDelayMs", 0)))),
        "jitter": float(retry_raw.get("jitter", 0.0)),
    }, legacy_used


def _parse_steps(raw_steps: list[Any], *, label: str) -> list[ScenarioStep]:
    parsed_steps: list[ScenarioStep] = []
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise ScenarioValidationError(f"{label} step {index} must be a mapping")

        if {"name", "type"}.issubset(raw_step.keys()):
            name = str(raw_step["name"])
            step_type = str(raw_step["type"])
            step_with = raw_step.get("with") or {}
            if not isinstance(step_with, dict):
                raise ScenarioValidationError(f"{label} step {index} with must be a mapping")
            publish = raw_step.get("publish") or {}
            if not isinstance(publish, dict) or not all(isinstance(v, str) for v in publish.values()):
                raise ScenarioValidationError(f"{label} step {index} publish must be a mapping of string expressions")
            retry, legacy = normalize_retry(raw_step)
            parsed_steps.append(
                ScenarioStep(
                    name=name,
                    type=step_type,
                    key=step_key(raw_step, index),
                    with_={k: v for k, v in step_with.items() if k not in {"retries", "backoffMs"}},
                    publish=publish,
                    always=bool(raw_step.get("always", False)),
                    retry=retry,
                    legacy_retry_used=legacy,
                )
            )
            continue

        # Legacy single action mapping.
        if len(raw_step) != 1:
            raise ScenarioValidationError(f"{label} step {index} must include name/type or single action mapping")
        action, payload = next(iter(raw_step.items()))
        if not isinstance(payload, dict):
            raise ScenarioValidationError(f"{label} step {index} payload must be a mapping")
        plugin = str(payload.get("via", "default"))
        parsed_steps.append(
            ScenarioStep(
                name=f"{plugin}.{action}",
                type=f"legacy.{plugin}.{action}",
                key=step_key(raw_step, index),
                with_={k: v for k, v in payload.items() if k != "via"},
                publish={},
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
