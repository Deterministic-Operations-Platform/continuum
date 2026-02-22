"""Scenario parsing and deterministic execution primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic, sleep
from typing import Any, Callable

import yaml

from continuum.errors import (
    LifecycleError,
    RuntimeTimeoutError,
    ScenarioValidationError,
    VerificationError,
)


@dataclass(slots=True)
class RetryPolicy:
    max_attempts: int = 1
    backoff_seconds: float = 0.0


@dataclass(slots=True)
class ScenarioStep:
    action: str
    payload: dict[str, Any]


@dataclass(slots=True)
class ScenarioSpec:
    name: str
    rail: str
    lifecycle_start: list[str]
    steps: list[ScenarioStep]
    evidence_export: str

    @staticmethod
    def from_mapping(data: dict[str, Any]) -> "ScenarioSpec":
        if not isinstance(data, dict):
            raise ScenarioValidationError("Scenario document must be a mapping.")

        required = ["name", "rail", "steps"]
        missing = [key for key in required if key not in data]
        if missing:
            raise ScenarioValidationError(
                f"Scenario is missing required field(s): {', '.join(missing)}"
            )

        lifecycle = data.get("lifecycle", {})
        start = lifecycle.get("start", []) if isinstance(lifecycle, dict) else []
        if not isinstance(start, list):
            raise ScenarioValidationError("lifecycle.start must be an array.")

        raw_steps = data["steps"]
        if not isinstance(raw_steps, list) or len(raw_steps) == 0:
            raise ScenarioValidationError("steps must be a non-empty array.")

        parsed_steps: list[ScenarioStep] = []
        for i, step in enumerate(raw_steps):
            if not isinstance(step, dict) or len(step) != 1:
                raise ScenarioValidationError(
                    f"Step {i} must be a single-key mapping like {{send: {{...}}}}."
                )

            action, payload = next(iter(step.items()))
            if not isinstance(payload, dict):
                raise ScenarioValidationError(
                    f"Step {i} payload for '{action}' must be a mapping."
                )
            parsed_steps.append(ScenarioStep(action=action, payload=payload))

        evidence = data.get("evidence", {})
        evidence_export = "audit-bundle"
        if isinstance(evidence, dict):
            evidence_export = evidence.get("export", "audit-bundle")

        return ScenarioSpec(
            name=str(data["name"]),
            rail=str(data["rail"]),
            lifecycle_start=[str(dep) for dep in start],
            steps=parsed_steps,
            evidence_export=str(evidence_export),
        )


@dataclass(slots=True)
class ExecutionEvidence:
    nondeterministic_inputs: dict[str, Any] = field(default_factory=dict)
    step_attempts: list[dict[str, Any]] = field(default_factory=list)


class ScenarioExecutor:
    """Deterministic scenario executor with strict step ordering."""

    def __init__(
        self,
        handlers: dict[str, Callable[[dict[str, Any], dict[str, Any]], None]],
        *,
        retry_policy: RetryPolicy | None = None,
        timeout_seconds: float | None = None,
    ):
        self.handlers = handlers
        self.retry_policy = retry_policy or RetryPolicy()
        self.timeout_seconds = timeout_seconds

    def execute(self, scenario: ScenarioSpec, context: dict[str, Any] | None = None) -> ExecutionEvidence:
        ctx = context or {}
        evidence = ExecutionEvidence()
        started_at = monotonic()

        for dependency in scenario.lifecycle_start:
            if not ctx.get("lifecycle", {}).get(dependency):
                raise LifecycleError(f"Lifecycle dependency not ready: {dependency}")

        for index, step in enumerate(scenario.steps):
            attempts = 0
            while attempts < self.retry_policy.max_attempts:
                attempts += 1
                if self.timeout_seconds is not None and monotonic() - started_at > self.timeout_seconds:
                    raise RuntimeTimeoutError(
                        f"Scenario '{scenario.name}' exceeded timeout policy ({self.timeout_seconds}s)."
                    )

                handler = self.handlers.get(step.action)
                if handler is None:
                    raise ScenarioValidationError(
                        f"No handler configured for step action '{step.action}'."
                    )

                try:
                    handler(step.payload, ctx)
                    evidence.step_attempts.append(
                        {"index": index, "action": step.action, "attempt": attempts, "status": "ok"}
                    )
                    break
                except VerificationError:
                    evidence.step_attempts.append(
                        {"index": index, "action": step.action, "attempt": attempts, "status": "verification_failed"}
                    )
                    if attempts >= self.retry_policy.max_attempts:
                        raise
                    if self.retry_policy.backoff_seconds > 0:
                        sleep(self.retry_policy.backoff_seconds)

        if "nondeterministic_inputs" in ctx and isinstance(ctx["nondeterministic_inputs"], dict):
            evidence.nondeterministic_inputs.update(ctx["nondeterministic_inputs"])

        return evidence


def load_scenario(path: str) -> ScenarioSpec:
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return ScenarioSpec.from_mapping(data)
