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
    with_: dict[str, Any] = field(default_factory=dict)
    publish: dict[str, str] | None = None
    key: str = ""
    always: bool = False
    retry: dict[str, Any] | None = None
    legacy_retry_used: bool = False
    depends_on: tuple[str, ...] | None = None
    resources: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    rail: str
    steps: tuple[ScenarioStep, ...]
    vars: dict[str, Any]
    services: dict[str, dict[str, Any]] = field(default_factory=dict)
    governance: dict[str, Any] = field(default_factory=dict)
    policy: dict[str, Any] = field(default_factory=dict)
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

        raw_services = data.get("services") or {}
        if not isinstance(raw_services, dict):
            raise ScenarioValidationError("services must be a mapping when provided")

        raw_governance = data.get("governance") or {}
        if not isinstance(raw_governance, dict):
            raise ScenarioValidationError("governance must be a mapping when provided")

        raw_policy = data.get("policy") or {}
        if not isinstance(raw_policy, dict):
            raise ScenarioValidationError("policy must be a mapping when provided")

        return Scenario(
            name=str(data["name"]),
            rail=str(data["rail"]),
            steps=tuple(_parse_steps(raw_steps, label="steps")),
            cleanup_steps=tuple(_parse_steps(raw_cleanup, label="cleanup_steps")),
            vars=raw_vars,
            services=_parse_services(raw_services),
            governance=_parse_governance(raw_governance),
            policy=_parse_policy(raw_policy),
        )


def _parse_services(raw_services: dict[str, Any]) -> dict[str, dict[str, Any]]:
    parsed: dict[str, dict[str, Any]] = {}
    for name, cfg in raw_services.items():
        if not isinstance(name, str) or not name.strip():
            raise ScenarioValidationError("services keys must be non-empty strings")
        if not isinstance(cfg, dict):
            raise ScenarioValidationError(f"service '{name}' must be a mapping")
        service_type = cfg.get("type")
        if not isinstance(service_type, str) or not service_type.strip():
            raise ScenarioValidationError(f"service '{name}' requires a non-empty type")
        normalized = dict(cfg)
        normalized["type"] = service_type.strip()
        normalized.setdefault("reuse", True)
        normalized.setdefault("verifyTimeoutSec", 10)
        parsed[name.strip()] = normalized
    return parsed


def _parse_governance(raw_governance: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(raw_governance)
    roles_raw = normalized.get("allowedRoles", normalized.get("requiredRoles", [])) or []
    if not isinstance(roles_raw, list) or not all(isinstance(v, str) and v.strip() for v in roles_raw):
        raise ScenarioValidationError("governance.allowedRoles/requiredRoles must be an array of non-empty strings")
    normalized["allowedRoles"] = [str(v).strip() for v in roles_raw]
    if "requiredRoles" in normalized:
        normalized["requiredRoles"] = [str(v).strip() for v in roles_raw]

    if "requireApproval" in normalized and not isinstance(normalized["requireApproval"], bool):
        raise ScenarioValidationError("governance.requireApproval must be boolean when provided")
    approval_file = normalized.get("approvalFile")
    if approval_file is not None and (not isinstance(approval_file, str) or not approval_file.strip()):
        raise ScenarioValidationError("governance.approvalFile must be a non-empty string when provided")
    approval_id = normalized.get("approvalId")
    if approval_id is not None and (not isinstance(approval_id, str) or not approval_id.strip()):
        raise ScenarioValidationError("governance.approvalId must be a non-empty string when provided")
    return normalized


def _parse_policy(raw_policy: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(raw_policy)
    req = normalized.get("requires") or {}
    if req and not isinstance(req, dict):
        raise ScenarioValidationError("policy.requires must be a mapping when provided")
    if isinstance(req, dict):
        files = req.get("files") or []
        if files and (not isinstance(files, list) or not all(isinstance(v, str) and v.strip() for v in files)):
            raise ScenarioValidationError("policy.requires.files must be an array of non-empty strings")
        if "signature" in req and not isinstance(req.get("signature"), bool):
            raise ScenarioValidationError("policy.requires.signature must be boolean when provided")
    return normalized


def step_key(step: dict[str, Any], index: int) -> str:
    explicit_key = step.get("key")
    if isinstance(explicit_key, str) and explicit_key.strip():
        return explicit_key.strip()
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
        if "name" not in raw_step or "type" not in raw_step:
            raise ScenarioValidationError(f"{label} step {index} must include canonical fields 'name' and 'type'")

        name = str(raw_step["name"])
        step_type = str(raw_step["type"])
        if not name.strip():
            raise ScenarioValidationError(f"{label} step {index} name must be a non-empty string")
        if not step_type.strip():
            raise ScenarioValidationError(f"{label} step {index} type must be a non-empty string")

        step_with = raw_step.get("with") or {}
        if not isinstance(step_with, dict):
            raise ScenarioValidationError(f"{label} step {index} with must be a mapping")
        publish = raw_step.get("publish") or {}
        if not isinstance(publish, dict) or not all(isinstance(v, str) for v in publish.values()):
            raise ScenarioValidationError(f"{label} step {index} publish must be a mapping of string expressions")
        retry, legacy = normalize_retry(raw_step)
        depends_on = raw_step.get("dependsOn", None)
        if depends_on is None:
            depends_on = raw_step.get("depends_on", None)
        if depends_on is not None and (
            not isinstance(depends_on, list) or not all(isinstance(v, str) and v.strip() for v in depends_on)
        ):
            raise ScenarioValidationError(f"{label} step {index} dependsOn must be an array of non-empty strings")
        resources = raw_step.get("resources") or []
        if not isinstance(resources, list) or not all(isinstance(v, str) and v.strip() for v in resources):
            raise ScenarioValidationError(f"{label} step {index} resources must be an array of non-empty strings")
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
                depends_on=None if depends_on is None else tuple(v.strip() for v in depends_on),
                resources=tuple(v.strip() for v in resources),
            )
        )
    return parsed_steps


def load_scenario(path: str | Path) -> Scenario:
    scenario_path = Path(path)
    data = load_scenario_document(scenario_path)
    if not isinstance(data, dict):
        raise ScenarioValidationError("Scenario document must be a mapping")

    return Scenario.from_mapping(data)


def load_scenario_document(path: str | Path) -> dict[str, Any] | list[Any] | Any:
    scenario_path = Path(path)
    text = scenario_path.read_text(encoding="utf-8")
    suffix = scenario_path.suffix.lower()
    if suffix == ".json":
        return json.loads(text)
    elif suffix in {".yaml", ".yml"}:
        return yaml.safe_load(text)
    else:
        raise ScenarioValidationError("Scenario must be .json, .yaml, or .yml")
