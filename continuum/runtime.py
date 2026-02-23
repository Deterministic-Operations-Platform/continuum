"""Runtime interface and deterministic implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import shutil
from time import sleep
from typing import Any, Protocol
import uuid

from continuum.errors import ContinuumError, FailureClass, ScenarioValidationError
from continuum.evidence import EvidenceCollector
from continuum.plugins import PluginRegistry, find_unknown_templates, render_templates, resolve_attach_files
from continuum.scenario import Scenario


class Runtime(Protocol):
    def execute(self, scenario: Scenario, scenario_source: Path, scenario_text: str, run_id: str | None = None) -> dict[str, Any]: ...


def build_plan(
    scenario: Scenario,
    *,
    run_id: str,
    run_dir: Path,
    env: dict[str, str] | None = None,
    vars: dict[str, Any] | None = None,
) -> dict[str, Any]:
    env_map = dict(env or {})
    vars_map = dict(vars or scenario.vars)
    ctx = {"run_id": run_id, "run_dir": str(run_dir), "env": env_map, "vars": vars_map}

    steps: list[dict[str, Any]] = []
    for index, step in enumerate(scenario.steps):
        rendered = render_templates(step.with_, ctx=ctx)
        retry = step.retry or {
            "on": ["exception"],
            "maxAttempts": 1,
            "backoff": "fixed",
            "baseDelayMs": 0,
            "maxDelayMs": 0,
            "jitter": 0.0,
        }
        step_dir = run_dir / "evidence" / f"{index + 1:02d}-{step.name}"
        attempts = [str(step_dir / f"attempt-{attempt:02d}") for attempt in range(1, int(retry["maxAttempts"]) + 1)]
        attach_files = resolve_attach_files(rendered, str(run_dir)) if step.type == "jira.attach" else []
        steps.append(
            {
                "index": index,
                "key": step.key or f"{index + 1:02d}",
                "name": step.name,
                "type": step.type,
                "always": step.always,
                "with": rendered,
                "retry": retry,
                "attach_files": attach_files,
                "evidence_dir": str(step_dir),
                "attempt_dirs": attempts,
            }
        )

    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "scenario": {"name": scenario.name, "rail": scenario.rail},
        "steps": steps,
    }


class DeterministicRuntime:
    def __init__(self, plugin_registry: PluginRegistry, evidence_collector: EvidenceCollector):
        self.plugin_registry = plugin_registry
        self.evidence_collector = evidence_collector

    def execute(self, scenario: Scenario, scenario_source: Path, scenario_text: str, run_id: str | None = None) -> dict[str, Any]:
        resolved_run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        run_dir = Path("runs") / resolved_run_id
        warnings = [
            f"step '{step.name}' uses legacy with.retries/backoffMs shorthand; normalized into step.retry"
            for step in [*scenario.steps, *scenario.cleanup_steps]
            if step.legacy_retry_used
        ]

        context: dict[str, Any] = {
            "run_id": resolved_run_id,
            "run_dir": str(run_dir),
            "vars": dict(scenario.vars),
            "env": dict(os.environ),
            "step_dir": lambda i, n: str(self.evidence_collector.step_dir(run_dir, i, n)),
            "write_json": lambda step_path, filename, payload: self.evidence_collector.write_json(Path(step_path) / filename, payload),
        }

        summary_steps: list[dict[str, Any]] = []
        cleanup_steps: list[dict[str, Any]] = []
        failure: dict[str, str] | None = None

        for index, step in enumerate(scenario.steps):
            if failure and not step.always:
                continue
            step_summary = self._run_one(step=step, step_index=index, context=context)
            summary_steps.append(step_summary)
            if step_summary.get("publish"):
                context["vars"].update(step_summary["publish"])
            if step_summary.get("exports"):
                exports = step_summary["exports"]
                context["vars"].update(exports)
                steps_ns = context["vars"].setdefault("steps", {})
                if isinstance(steps_ns, dict):
                    steps_ns[step.key or f"{index + 1:02d}"] = exports
            if not step_summary["ok"] and failure is None:
                failure = step_summary.get("failure") or {"message": step_summary.get("error", "step failed"), "class": FailureClass.DATA.value}

        for index, step in enumerate(scenario.cleanup_steps):
            cleanup_summary = self._run_one(step=step, step_index=index, context=context, phase="cleanup")
            cleanup_steps.append(cleanup_summary)

        summary = {
            "run_id": resolved_run_id,
            "scenario": {"name": scenario.name, "rail": scenario.rail, "steps": len(scenario.steps)},
            "status": "failed" if failure else "succeeded",
            "steps": summary_steps,
            "cleanup_steps": cleanup_steps,
            "failure": failure,
            "warnings": warnings,
            "evidence_dir": str(run_dir),
        }
        self.evidence_collector.write_run_bundle(
            run_id=resolved_run_id,
            scenario_source=scenario_source,
            scenario_text=scenario_text,
            context_payload={"run_id": resolved_run_id, "run_dir": str(run_dir), "vars": context["vars"]},
            summary=summary,
            manifest_payload={},
        )
        return summary

    def _run_one(self, *, step: Any, step_index: int, context: dict[str, Any], phase: str = "execution") -> dict[str, Any]:
        plugin = self.plugin_registry.resolve(step.type)
        rendered = render_templates(step.with_, ctx=context)
        retry = step.retry
        if retry is None and ("retries" in rendered or "backoffMs" in rendered):
            retry = {"maxAttempts": int(rendered.get("retries", 0)) + 1, "baseDelayMs": int(rendered.get("backoffMs", 0))}
        retry = retry or {"maxAttempts": 1, "baseDelayMs": 0}
        step_input = {k: v for k, v in rendered.items() if k not in {"retries", "backoffMs"}}

        attempts: list[dict[str, Any]] = []
        last_error: dict[str, str] | None = None
        for attempt in range(1, int(retry.get("maxAttempts", 1)) + 1):
            try:
                result = plugin.run(step_name=step.name, step_with=step_input, ctx=context, step_index=step_index)
                attempts.append({"attempt": attempt, "ok": result.ok, "details": result.details, "evidence": result.evidence_paths})
                summary = {
                    "index": step_index,
                    "name": step.name,
                    "key": step.key,
                    "type": step.type,
                    "phase": phase,
                    "status": "succeeded" if result.ok else "failed",
                    "ok": result.ok,
                    "details": result.details,
                    "evidence": result.evidence_paths,
                    "attempts": attempts,
                    "exports": result.exports or {},
                    "publish": self._resolve_publish(step.publish or {}, result.details),
                }
                if result.ok:
                    return summary
                last_error = {"message": f"Step returned unsuccessful status: {step.name}", "class": FailureClass.DATA.value}
            except ContinuumError as err:
                attempts.append({"attempt": attempt, "ok": False, "error": str(err)})
                last_error = {"message": str(err), "class": err.failure_class.value}
            except Exception as err:
                attempts.append({"attempt": attempt, "ok": False, "error": str(err)})
                last_error = {"message": str(err), "class": FailureClass.INFRA.value}

            if attempt < int(retry.get("maxAttempts", 1)) and int(retry.get("baseDelayMs", 0)) > 0:
                sleep(int(retry.get("baseDelayMs", 0)) / 1000)

        return {
            "index": step_index,
            "name": step.name,
            "key": step.key,
            "type": step.type,
            "phase": phase,
            "status": "failed",
            "ok": False,
            "attempts": attempts,
            "failure": last_error,
            "error": (last_error or {}).get("message", "step failed"),
            "publish": {},
            "exports": {},
        }

    def _resolve_publish(self, publish_map: dict[str, str], details: dict[str, Any]) -> dict[str, Any]:
        published: dict[str, Any] = {}
        for target, expr in publish_map.items():
            if not expr.startswith("$.details."):
                continue
            cur: Any = details
            ok = True
            for seg in expr[len("$.details."):].split("."):
                if isinstance(cur, dict) and seg in cur:
                    cur = cur[seg]
                else:
                    ok = False
                    break
            if ok:
                published[target] = cur
        return published


def validate_scenario(scenario: Scenario, *, plugin_registry: PluginRegistry, env: dict[str, str] | None = None) -> tuple[list[str], list[str]]:
    env_map = dict(env or os.environ)
    errors: list[str] = []
    warnings: list[str] = []
    ctx = {"run_id": "validate", "run_dir": "runs/validate", "env": env_map, "vars": dict(scenario.vars)}

    for index, step in enumerate(scenario.steps):
        unknown = find_unknown_templates(step.with_, ctx=ctx)
        if unknown:
            errors.append(f"step {index} ({step.name}): unknown template keys: {', '.join(unknown)}")
        if step.legacy_retry_used:
            warnings.append(f"step {index} ({step.name}): uses legacy with.retries/backoffMs; normalized to step.retry")

        if step.type == "postman.run" and not shutil.which("newman"):
            errors.append(f"step {index} ({step.name}): missing dependency 'newman'")
        if step.type == "mongo.verify":
            try:
                import pymongo  # type: ignore  # noqa: F401
            except Exception:
                errors.append(f"step {index} ({step.name}): missing dependency 'pymongo'")
        if step.type.startswith("jira."):
            missing = [k for k in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN") if not env_map.get(k)]
            if missing:
                errors.append(f"step {index} ({step.name}): missing Jira env vars: {', '.join(missing)}")
        if step.type == "jira.attach":
            rendered = render_templates(step.with_, ctx=ctx)
            files = resolve_attach_files(rendered, ctx["run_dir"])
            warnings.append(f"step {index} ({step.name}): jira.attach would attach {len(files)} file(s)")

        try:
            plugin_registry.resolve(step.type)
        except Exception as err:
            errors.append(f"step {index} ({step.name}): {err}")

    return errors, warnings
