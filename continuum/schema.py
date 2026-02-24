"""Canonical scenario schema validation helpers."""

from __future__ import annotations

from typing import Any


def validate_scenario_schema(document: dict[str, Any]) -> list[str]:
    """Return deterministic schema errors for a raw scenario mapping."""
    errors: list[str] = []
    required = ("name", "rail", "steps")
    for field in required:
        if field not in document:
            errors.append(f"missing required field '{field}'")

    _expect_type(errors, document, "name", str)
    _expect_type(errors, document, "rail", str)
    _expect_type(errors, document, "vars", dict, optional=True)
    _expect_type(errors, document, "services", dict, optional=True)
    _expect_type(errors, document, "governance", dict, optional=True)
    _expect_type(errors, document, "policy", dict, optional=True)
    _expect_type(errors, document, "dependencies", dict, optional=True)
    _expect_type(errors, document, "cleanup_steps", list, optional=True)

    steps = document.get("steps")
    if steps is not None:
        if not isinstance(steps, list):
            errors.append("field 'steps' must be of type array")
        elif not steps:
            errors.append("field 'steps' must contain at least one step")
        else:
            for index, step in enumerate(steps):
                errors.extend(_validate_step(step, index=index, label="steps"))

    cleanup_steps = document.get("cleanup_steps")
    if isinstance(cleanup_steps, list):
        for index, step in enumerate(cleanup_steps):
            errors.extend(_validate_step(step, index=index, label="cleanup_steps"))

    policy = document.get("policy")
    if isinstance(policy, dict):
        requires = policy.get("requires")
        if requires is not None and not isinstance(requires, dict):
            errors.append("field 'policy.requires' must be of type object")
        if isinstance(requires, dict):
            files = requires.get("files")
            if files is not None:
                if not isinstance(files, list):
                    errors.append("field 'policy.requires.files' must be of type array")
                elif not all(isinstance(item, str) and item.strip() for item in files):
                    errors.append("field 'policy.requires.files' must contain non-empty string values")
            signature = requires.get("signature")
            if signature is not None and not isinstance(signature, bool):
                errors.append("field 'policy.requires.signature' must be of type bool")

    dependencies = document.get("dependencies")
    if isinstance(dependencies, dict):
        for key, dep in dependencies.items():
            prefix = f"dependencies.{key}"
            if not isinstance(dep, dict):
                errors.append(f"field '{prefix}' must be of type object")
                continue
            if "required" in dep and not isinstance(dep.get("required"), bool):
                errors.append(f"field '{prefix}.required' must be of type bool")
            if "fallback" in dep and dep.get("fallback") not in {"stub", "replay"}:
                errors.append(f"field '{prefix}.fallback' must be one of: stub, replay")
            if "allowed_modes" in dep:
                allowed = dep.get("allowed_modes")
                if not isinstance(allowed, list):
                    errors.append(f"field '{prefix}.allowed_modes' must be of type array")
                elif not all(isinstance(mode, str) and mode in {"live", "stub", "replay"} for mode in allowed):
                    errors.append(f"field '{prefix}.allowed_modes' must contain only live|stub|replay")

    return sorted(set(errors))


def _expect_type(errors: list[str], document: dict[str, Any], key: str, expected: type[Any], *, optional: bool = False) -> None:
    value = document.get(key)
    if value is None:
        if not optional and key in document:
            errors.append(f"field '{key}' must be of type {expected.__name__}")
        return
    if not isinstance(value, expected):
        expected_label = "array" if expected is list else "object" if expected is dict else expected.__name__
        errors.append(f"field '{key}' must be of type {expected_label}")


def _validate_step(step: Any, *, index: int, label: str) -> list[str]:
    errors: list[str] = []
    prefix = f"{label}[{index}]"
    if not isinstance(step, dict):
        return [f"{prefix} must be an object"]
    for required in ("name", "type"):
        if required not in step:
            errors.append(f"{prefix} missing required field '{required}'")

    if "name" in step and not isinstance(step.get("name"), str):
        errors.append(f"{prefix}.name must be a string")
    if "type" in step and not isinstance(step.get("type"), str):
        errors.append(f"{prefix}.type must be a string")
    if "with" in step and not isinstance(step.get("with"), dict):
        errors.append(f"{prefix}.with must be an object")
    if "publish" in step and not isinstance(step.get("publish"), dict):
        errors.append(f"{prefix}.publish must be an object")
    if "dependsOn" in step and not isinstance(step.get("dependsOn"), list):
        errors.append(f"{prefix}.dependsOn must be an array")
    if "retry" in step and not isinstance(step.get("retry"), dict):
        errors.append(f"{prefix}.retry must be an object")
    return errors
