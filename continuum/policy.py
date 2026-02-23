"""Policy loading and gate evaluation for provable runs."""

from __future__ import annotations

from dataclasses import dataclass
import glob
from pathlib import Path
from typing import Any

import yaml

from continuum.scenario import Scenario


DEFAULT_POLICY_PATH = Path("policy.yaml")


class PolicyValidationError(ValueError):
    """Raised when a policy document is malformed."""


@dataclass(frozen=True, slots=True)
class PolicyRequirement:
    id: str
    description: str
    patterns: tuple[str, ...]
    match: str
    when_step_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RunPolicy:
    name: str
    version: str
    required_evidence: tuple[PolicyRequirement, ...]
    source_path: str


def load_policy(path: str | Path | None = None) -> RunPolicy | None:
    policy_path = Path(path) if path is not None else DEFAULT_POLICY_PATH
    if not policy_path.is_file():
        return None

    try:
        payload = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    except Exception as err:
        raise PolicyValidationError(f"failed to parse policy file '{policy_path}': {err}") from err

    if not isinstance(payload, dict):
        raise PolicyValidationError("policy document must be a mapping")

    raw_required = payload.get("required_evidence") or payload.get("requiredEvidence") or []
    if not isinstance(raw_required, list) or not raw_required:
        raise PolicyValidationError("policy.required_evidence must be a non-empty list")

    requirements: list[PolicyRequirement] = []
    for idx, item in enumerate(raw_required):
        if not isinstance(item, dict):
            raise PolicyValidationError(f"required_evidence[{idx}] must be a mapping")
        requirement_id = str(item.get("id") or f"requirement_{idx + 1}").strip()
        if not requirement_id:
            raise PolicyValidationError(f"required_evidence[{idx}].id must be non-empty")
        description = str(item.get("description") or item.get("name") or requirement_id).strip()

        patterns, match = _parse_requirement_patterns(item=item, index=idx)
        when_step_types = tuple(str(v).strip() for v in (item.get("when_step_types") or item.get("whenStepTypes") or []) if str(v).strip())

        requirements.append(
            PolicyRequirement(
                id=requirement_id,
                description=description,
                patterns=patterns,
                match=match,
                when_step_types=when_step_types,
            )
        )

    return RunPolicy(
        name=str(payload.get("name") or "provable-runs-policy").strip() or "provable-runs-policy",
        version=str(payload.get("version") or "v0.2").strip() or "v0.2",
        required_evidence=tuple(requirements),
        source_path=str(policy_path),
    )


def evaluate_policy_pre(
    *,
    policy: RunPolicy | None,
    scenario: Scenario,
    policy_path: str | Path,
    load_error: str | None = None,
) -> dict[str, Any]:
    if load_error:
        return {
            "enabled": True,
            "path": str(policy_path),
            "ok": False,
            "requirements": [],
            "violations": [load_error],
        }

    if policy is None:
        return {
            "enabled": False,
            "path": str(policy_path),
            "ok": True,
            "requirements": [],
            "violations": [],
            "reason": "policy file not found; governance gate skipped",
        }

    step_types = {step.type for step in scenario.steps}
    requirement_results: list[dict[str, Any]] = []
    violations: list[str] = []
    for requirement in policy.required_evidence:
        applicable = _is_applicable(requirement=requirement, step_types=step_types)
        req_result = {
            "id": requirement.id,
            "description": requirement.description,
            "match": requirement.match,
            "patterns": list(requirement.patterns),
            "whenStepTypes": list(requirement.when_step_types),
            "applicable": applicable,
            "ok": True,
        }
        if applicable and not requirement.patterns:
            req_result["ok"] = False
            req_result["reason"] = "requirement has no evidence patterns"
            violations.append(f"policy requirement '{requirement.id}' has no evidence patterns")
        requirement_results.append(req_result)

    return {
        "enabled": True,
        "path": policy.source_path,
        "name": policy.name,
        "version": policy.version,
        "ok": not violations,
        "requirements": requirement_results,
        "violations": violations,
    }


def evaluate_policy_post(*, policy: RunPolicy | None, scenario: Scenario, run_dir: Path) -> dict[str, Any]:
    if policy is None:
        return {
            "enabled": False,
            "path": str(DEFAULT_POLICY_PATH),
            "ok": True,
            "requirements": [],
            "violations": [],
        }

    step_types = {step.type for step in scenario.steps}
    requirement_results: list[dict[str, Any]] = []
    violations: list[str] = []
    for requirement in policy.required_evidence:
        applicable = _is_applicable(requirement=requirement, step_types=step_types)
        req_result: dict[str, Any] = {
            "id": requirement.id,
            "description": requirement.description,
            "match": requirement.match,
            "patterns": list(requirement.patterns),
            "whenStepTypes": list(requirement.when_step_types),
            "applicable": applicable,
            "ok": True,
            "matches": {},
        }
        if not applicable:
            requirement_results.append(req_result)
            continue

        pattern_hits: dict[str, list[str]] = {}
        for pattern in requirement.patterns:
            full_pattern = pattern if Path(pattern).is_absolute() else str(run_dir / pattern)
            hits = sorted(glob.glob(full_pattern, recursive=True))
            pattern_hits[pattern] = [_relative_display(path=Path(hit), run_dir=run_dir) for hit in hits]
        req_result["matches"] = pattern_hits

        if requirement.match == "all":
            missing = [pattern for pattern, hits in pattern_hits.items() if not hits]
            req_ok = not missing
            if missing:
                req_result["reason"] = f"missing matches for patterns: {', '.join(missing)}"
        else:
            req_ok = any(hits for hits in pattern_hits.values())
            if not req_ok:
                req_result["reason"] = "no matching evidence files found"

        req_result["ok"] = req_ok
        if not req_ok:
            violations.append(
                f"missing evidence '{requirement.id}' ({requirement.description})"
            )
        requirement_results.append(req_result)

    return {
        "enabled": True,
        "path": policy.source_path,
        "name": policy.name,
        "version": policy.version,
        "ok": not violations,
        "requirements": requirement_results,
        "violations": violations,
    }


def _parse_requirement_patterns(*, item: dict[str, Any], index: int) -> tuple[tuple[str, ...], str]:
    any_of = item.get("any_of")
    if any_of is None:
        any_of = item.get("anyOf")
    all_of = item.get("all_of")
    if all_of is None:
        all_of = item.get("allOf")
    patterns_value = item.get("patterns")

    match = str(item.get("match") or "any").strip().lower()
    if any_of is not None:
        patterns_value = any_of
        match = "any"
    if all_of is not None:
        patterns_value = all_of
        match = "all"
    if match not in {"any", "all"}:
        raise PolicyValidationError(f"required_evidence[{index}].match must be 'any' or 'all'")

    if isinstance(patterns_value, str):
        patterns = (patterns_value,)
    elif isinstance(patterns_value, list) and all(isinstance(v, str) and v.strip() for v in patterns_value):
        patterns = tuple(v.strip() for v in patterns_value)
    else:
        raise PolicyValidationError(f"required_evidence[{index}] must define non-empty string patterns")

    return patterns, match


def _is_applicable(*, requirement: PolicyRequirement, step_types: set[str]) -> bool:
    if not requirement.when_step_types:
        return True
    return any(step_type in step_types for step_type in requirement.when_step_types)


def _relative_display(*, path: Path, run_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(run_dir.resolve()))
    except Exception:
        try:
            return str(path.relative_to(run_dir))
        except Exception:
            return str(path)
