"""Runtime interface and deterministic implementation."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
from threading import Lock
from time import sleep
from typing import Any, Protocol
import uuid

from continuum.errors import ContinuumError, FailureClass, ScenarioValidationError, StepExecutionError
from continuum.evidence import EvidenceCollector
from continuum.plugins import (
    PluginRegistry,
    ensure_applauncher_session,
    find_unknown_templates,
    render_templates,
    resolve_attach_files,
)
from continuum.scenario import Scenario, ScenarioStep


_SECRET_HINTS = (
    "secret",
    "token",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "private_key",
    "client_secret",
)
_SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"(?i)(token\s*[=:]\s*)([^\s,;]+)", r"\1[REDACTED]"),
    (r"(?i)(password\s*[=:]\s*)([^\s,;]+)", r"\1[REDACTED]"),
    (r"(?i)(cookie\s*[=:]\s*)([^\s,;]+)", r"\1[REDACTED]"),
    (r"(?i)(authorization\s*:\s*bearer\s+)([^\s,;]+)", r"\1[REDACTED]"),
)


class Runtime(Protocol):
    def execute(self, scenario: Scenario, scenario_source: Path, scenario_text: str, run_id: str | None = None) -> dict[str, Any]: ...


class _PayloadRedactor:
    def __init__(self, *, env: dict[str, str], vars_payload: dict[str, Any]):
        secrets: set[str] = set()
        for key, value in [*env.items(), *vars_payload.items()]:
            if isinstance(value, str) and value and any(hint in str(key).lower() for hint in _SECRET_HINTS):
                secrets.add(value)
        self._secrets = tuple(sorted((value for value in secrets if len(value) >= 6), key=len, reverse=True))

    def redact(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            return {k: self.redact(v) for k, v in payload.items()}
        if isinstance(payload, list):
            return [self.redact(v) for v in payload]
        if isinstance(payload, tuple):
            return [self.redact(v) for v in payload]
        if not isinstance(payload, str):
            return payload
        text = payload
        for secret in self._secrets:
            if secret in text:
                text = text.replace(secret, "[REDACTED]")
        for pattern, replacement in _SECRET_PATTERNS:
            text = re.sub(pattern, replacement, text)
        return text


class _AuditLog:
    def __init__(self, *, path: Path, run_id: str, trace_id: str, redactor: _PayloadRedactor):
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._run_id = run_id
        self._trace_id = trace_id
        self._redactor = redactor
        self._lock = Lock()
        self._seq = 0
        self._head_hash = ""
        if self._path.exists():
            try:
                lines = [line for line in self._path.read_text(encoding="utf-8").splitlines() if line.strip()]
                if lines:
                    last = json.loads(lines[-1])
                    self._seq = int(last.get("seq", 0))
                    self._head_hash = str(last.get("hash", ""))
            except Exception:
                self._seq = 0
                self._head_hash = ""

    def append(self, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._seq += 1
            event = {
                "seq": self._seq,
                "ts": datetime.now(timezone.utc).isoformat(),
                "runId": self._run_id,
                "traceId": self._trace_id,
                "event": event_type,
                "prevHash": self._head_hash,
                "payload": self._redactor.redact(payload or {}),
            }
            event["hash"] = hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True) + "\n")
            self._head_hash = str(event["hash"])
            return event

    def state(self) -> dict[str, Any]:
        return {"path": str(self._path), "events": self._seq, "headHash": self._head_hash, "algorithm": "sha256"}


def _step_key(step: ScenarioStep, index: int) -> str:
    return step.key if isinstance(step.key, str) and step.key.strip() else f"{index + 1:02d}_{step.name}"


def _step_dependencies(steps: tuple[ScenarioStep, ...], index: int) -> tuple[str, ...]:
    step = steps[index]
    if step.depends_on is not None:
        return tuple(step.depends_on)
    if index == 0:
        return ()
    return (_step_key(steps[index - 1], index - 1),)


def _normalized_retry(step: ScenarioStep, rendered_with: dict[str, Any]) -> dict[str, Any]:
    retry = step.retry or {}
    legacy_attempts = 1
    if "retries" in rendered_with:
        try:
            legacy_attempts = max(1, int(rendered_with.get("retries", 0)) + 1)
        except Exception:
            legacy_attempts = 1
    return {
        "on": list(retry.get("on", ["exception"])),
        "maxAttempts": max(1, int(retry.get("maxAttempts", legacy_attempts))),
        "backoff": str(retry.get("backoff", "fixed")),
        "baseDelayMs": max(0, int(retry.get("baseDelayMs", rendered_with.get("backoffMs", 0)))),
        "maxDelayMs": max(0, int(retry.get("maxDelayMs", retry.get("baseDelayMs", rendered_with.get("backoffMs", 0))))),
        "jitter": float(retry.get("jitter", 0.0)),
    }


def build_plan(
    scenario: Scenario,
    *,
    run_id: str,
    run_dir: Path,
    env: dict[str, str] | None = None,
    vars: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ctx = {"run_id": run_id, "run_dir": str(run_dir), "env": dict(env or {}), "vars": dict(vars or scenario.vars)}
    steps: list[dict[str, Any]] = []
    for index, step in enumerate(scenario.steps):
        rendered = render_templates(step.with_, ctx=ctx)
        retry = _normalized_retry(step, rendered)
        step_dir = run_dir / "evidence" / f"{index + 1:02d}-{step.name}"
        attempts = [str(step_dir / f"attempt-{attempt:02d}") for attempt in range(1, int(retry["maxAttempts"]) + 1)]
        attach_files = resolve_attach_files(rendered, str(run_dir)) if step.type == "jira.attach" else []
        steps.append(
            {
                "index": index,
                "key": _step_key(step, index),
                "name": step.name,
                "type": step.type,
                "always": step.always,
                "dependsOn": list(_step_dependencies(scenario.steps, index)),
                "resources": list(step.resources),
                "with": rendered,
                "retry": retry,
                "attach_files": attach_files,
                "evidence_dir": str(step_dir),
                "attempt_dirs": attempts,
            }
        )
    return {"run_id": run_id, "run_dir": str(run_dir), "scenario": {"name": scenario.name, "rail": scenario.rail}, "steps": steps}


class DeterministicRuntime:
    def __init__(self, plugin_registry: PluginRegistry, evidence_collector: EvidenceCollector):
        self.plugin_registry = plugin_registry
        self.evidence_collector = evidence_collector

    def execute(
        self,
        scenario: Scenario,
        scenario_source: Path,
        scenario_text: str,
        run_id: str | None = None,
        *,
        no_services: bool = False,
        stop_services: bool = False,
        reuse_sessions: bool = True,
        resume_run_id: str | None = None,
        resume_id: str | None = None,
        rerun_selectors: tuple[str, ...] | list[str] = (),
        from_failure: bool = False,
        from_selector: str | None = None,
        to_selector: str | None = None,
        only_selectors: tuple[str, ...] | list[str] = (),
        skip_selectors: tuple[str, ...] | list[str] = (),
        no_cleanup: bool = False,
        cli_vars: dict[str, Any] | None = None,
        max_parallel: int = 1,
        actor: str | None = None,
        actor_roles: tuple[str, ...] | list[str] = (),
        approval_file: str | None = None,
    ) -> dict[str, Any]:
        resolved_run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        run_dir = Path("runs") / resolved_run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        effective_resume_id = resume_run_id or resume_id
        started_at = datetime.now(timezone.utc).isoformat()

        summary_steps: list[dict[str, Any]] = []
        cleanup_steps: list[dict[str, Any]] = []
        service_states: dict[str, dict[str, Any]] = {}
        service_cleanup: dict[str, Any] = {}
        governance: dict[str, Any] = {}
        selection: dict[int, str] = {}
        failure: dict[str, Any] | None = None
        trace_id = ""
        context: dict[str, Any] = {}
        vars_payload: dict[str, Any] = {}
        redactor: _PayloadRedactor | None = None
        audit: _AuditLog | None = None
        deferred_error: ContinuumError | None = None
        safe_summary: dict[str, Any] | None = None

        warnings = [
            f"step '{step.name}' uses legacy with.retries/backoffMs shorthand; normalized into step.retry"
            for step in [*scenario.steps, *scenario.cleanup_steps]
            if step.legacy_retry_used
        ]

        try:
            previous_summary, previous_context = self._load_resume_bundle(effective_resume_id)
            prev_vars = (previous_context or {}).get("vars", {}) if isinstance(previous_context, dict) else {}
            prev_vars = prev_vars if isinstance(prev_vars, dict) else {}
            vars_payload = _deep_merge(_deep_merge(dict(prev_vars), dict(scenario.vars)), dict(cli_vars or {}))
            trace_id = self._resolve_trace_id(scenario_text=scenario_text, run_id=resolved_run_id, vars_payload=vars_payload)
            vars_payload["traceId"] = trace_id

            redactor = _PayloadRedactor(env=dict(os.environ), vars_payload=vars_payload)
            audit = _AuditLog(path=run_dir / "events.log", run_id=resolved_run_id, trace_id=trace_id, redactor=redactor)
            context = {
                "run_id": resolved_run_id,
                "run_dir": str(run_dir),
                "vars": vars_payload,
                "env": dict(os.environ),
                "step_dir": lambda i, n: str(self.evidence_collector.step_dir(run_dir, i, n)),
                "write_json": lambda step_path, filename, payload: self.evidence_collector.write_json(Path(step_path) / filename, redactor.redact(payload)),
            }
            self.evidence_collector.write_json(run_dir / "trace.json", redactor.redact({"runId": resolved_run_id, "traceId": trace_id}))
            audit.append("run.started", {"scenario": scenario.name, "resumedFrom": effective_resume_id, "maxParallel": max(1, int(max_parallel))})

            governance = self._enforce_governance(
                scenario=scenario,
                run_id=resolved_run_id,
                trace_id=trace_id,
                actor=actor,
                actor_roles=tuple(actor_roles),
                approval_file=approval_file,
                run_dir=run_dir,
                redactor=redactor,
            )
            if governance:
                audit.append("governance.checked", governance)

            service_states = self._ensure_services(scenario=scenario, context=context, run_dir=run_dir, no_services=no_services, reuse_sessions=reuse_sessions, audit=audit)
            dep_map = self._dependency_index_map(scenario.steps)
            self._validate_dependency_map(dep_map)
            prev_status = self._build_previous_status_map(previous_summary)
            selection = self._selection_map(
                scenario.steps,
                from_selector=from_selector,
                to_selector=to_selector,
                only_selectors=tuple(only_selectors),
                skip_selectors=tuple(skip_selectors),
                prev_status_by_key=prev_status,
                rerun_selectors=tuple(rerun_selectors),
                from_failure=from_failure,
                previous_summary=previous_summary,
            )
            summary_steps, failure = self._execute_steps(scenario=scenario, context=context, selection_map=selection, dependency_map=dep_map, max_parallel=max_parallel, audit=audit)
        except ContinuumError as err:
            failure = {"message": str(err), "class": err.failure_class.value}
            if isinstance(err, ScenarioValidationError):
                deferred_error = err
            if audit:
                audit.append("run.error", failure)
        except Exception as err:
            failure = {"message": str(err), "class": FailureClass.INFRA.value}
            if audit:
                audit.append("run.error", failure)
        finally:
            cleanup_failure: dict[str, Any] | None = None
            if context and not no_cleanup:
                cleanup_steps, cleanup_failure = self._run_cleanup_steps(scenario=scenario, context=context, audit=audit)
            if cleanup_failure and failure is None:
                failure = cleanup_failure
            if context:
                service_cleanup = self._stop_services(service_states=service_states, stop_services=stop_services, audit=audit)

            status = "failed" if failure else "succeeded"
            if audit:
                audit.append("run.finished", {"status": status, "failure": failure, "stepCount": len(summary_steps), "cleanupCount": len(cleanup_steps)})

            if redactor is None:
                redactor = _PayloadRedactor(env=dict(os.environ), vars_payload=vars_payload if vars_payload else {})
            if not trace_id:
                trace_id = self._resolve_trace_id(scenario_text=scenario_text, run_id=resolved_run_id, vars_payload=vars_payload if vars_payload else {})

            summary = {
                "run_id": resolved_run_id,
                "traceId": trace_id,
                "resumedFrom": effective_resume_id,
                "scenario": {"name": scenario.name, "rail": scenario.rail, "steps": len(scenario.steps)},
                "status": status,
                "steps": summary_steps,
                "cleanup_steps": cleanup_steps,
                "services": service_states,
                "service_cleanup": service_cleanup,
                "governance": governance,
                "selection": {str(k): v for k, v in sorted(selection.items())},
                "failure": failure,
                "warnings": warnings,
                "startedAt": started_at,
                "endedAt": datetime.now(timezone.utc).isoformat(),
                "evidence_dir": str(run_dir),
                "audit": audit.state() if audit else {},
            }
            safe_summary = redactor.redact(summary)
            context_payload = {
                "run_id": resolved_run_id,
                "run_dir": str(run_dir),
                "vars": redactor.redact((context.get("vars") or vars_payload) if isinstance(context, dict) else vars_payload),
                "actor": actor,
                "roles": sorted({str(v).strip() for v in actor_roles if str(v).strip()}),
                "traceId": trace_id,
            }
            self._write_bundle_safely(
                run_id=resolved_run_id,
                scenario_source=scenario_source,
                scenario_text=scenario_text,
                context_payload=context_payload,
                summary=safe_summary,
                manifest_payload={"traceId": trace_id, "audit": audit.state() if audit else {}, "governance": redactor.redact(governance), "status": status},
            )
        if safe_summary is None:
            raise StepExecutionError("run summary was not generated")
        if deferred_error is not None:
            raise deferred_error
        return safe_summary

    def _selection_map(
        self,
        steps: tuple[ScenarioStep, ...],
        *,
        from_selector: str | None,
        to_selector: str | None,
        only_selectors: tuple[str, ...],
        skip_selectors: tuple[str, ...],
        prev_status_by_key: dict[str, str],
        rerun_selectors: tuple[str, ...],
        from_failure: bool,
        previous_summary: dict[str, Any] | None,
    ) -> dict[int, str]:
        out: dict[int, str] = {}
        first_failed_index = self._first_failed_index(previous_summary) if from_failure else None
        start_idx = self._selector_index(steps, from_selector) if from_selector else None
        end_idx = self._selector_index(steps, to_selector) if to_selector else None
        if from_selector and start_idx is None:
            raise StepExecutionError(f"Unknown --from selector: {from_selector}")
        if to_selector and end_idx is None:
            raise StepExecutionError(f"Unknown --to selector: {to_selector}")
        for index, step in enumerate(steps):
            reason: str | None = None
            if first_failed_index is not None and index < first_failed_index:
                reason = "control-flow"
            if reason is None and start_idx is not None and index < start_idx:
                reason = "selector"
            if reason is None and end_idx is not None and index > end_idx:
                reason = "selector"
            if reason is None and only_selectors and not self._selected_by(step, index, only_selectors):
                reason = "selector"
            if reason is None and skip_selectors and self._selected_by(step, index, skip_selectors):
                reason = "selector"
            if reason is None and prev_status_by_key and step.key in prev_status_by_key and step.key not in rerun_selectors and prev_status_by_key.get(step.key) == "succeeded":
                reason = "resume:succeeded"
            if reason is not None:
                out[index] = reason
        return out

    def _dependency_index_map(self, steps: tuple[ScenarioStep, ...]) -> dict[int, set[int]]:
        key_to_index = {_step_key(step, index): index for index, step in enumerate(steps)}
        dep_map: dict[int, set[int]] = {}
        for index, step in enumerate(steps):
            deps: set[int] = set()
            for key in _step_dependencies(steps, index):
                if key not in key_to_index:
                    raise ScenarioValidationError(f"step {index} ({step.name}): unknown dependsOn key '{key}'")
                deps.add(key_to_index[key])
            dep_map[index] = deps
        return dep_map

    def _validate_dependency_map(self, dep_map: dict[int, set[int]]) -> None:
        indegree = {node: len(deps) for node, deps in dep_map.items()}
        dependents: dict[int, set[int]] = {node: set() for node in dep_map}
        for node, deps in dep_map.items():
            for dep in deps:
                dependents.setdefault(dep, set()).add(node)
        queue = sorted([node for node, degree in indegree.items() if degree == 0])
        visited = 0
        while queue:
            node = queue.pop(0)
            visited += 1
            for dependent in sorted(dependents.get(node, set())):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    queue.append(dependent)
        if visited != len(dep_map):
            raise ScenarioValidationError("cycle detected in step dependencies")

    def _execute_steps(
        self,
        *,
        scenario: Scenario,
        context: dict[str, Any],
        selection_map: dict[int, str],
        dependency_map: dict[int, set[int]],
        max_parallel: int,
        audit: _AuditLog,
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        steps = scenario.steps
        summaries: list[dict[str, Any] | None] = [None] * len(steps)
        pending: set[int] = set(range(len(steps)))
        completed: set[int] = set()
        failure: dict[str, Any] | None = None
        lock = Lock()

        for index in sorted(list(pending)):
            reason = selection_map.get(index)
            if reason is None:
                continue
            summaries[index] = self._skipped_step(steps[index], index, reason, context=context)
            pending.remove(index)
            completed.add(index)
            audit.append("step.skipped", {"index": index, "key": _step_key(steps[index], index), "reason": reason})

        active: dict[Future[dict[str, Any]], tuple[int, set[str]]] = {}
        active_resources: set[str] = set()
        max_workers = max(1, int(max_parallel))

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            while pending or active:
                progress = False
                done: set[Future[dict[str, Any]]] = set()
                if active:
                    done, _ = wait(tuple(active.keys()), timeout=0.05, return_when=FIRST_COMPLETED)

                for future in done:
                    index, resources = active.pop(future)
                    active_resources.difference_update(resources)
                    step = steps[index]
                    result = future.result()
                    summaries[index] = result
                    completed.add(index)
                    self._merge_step_outputs(step=step, step_index=index, step_summary=result, context=context, lock=lock)
                    audit.append("step.succeeded" if result.get("ok") else "step.failed", {"index": index, "key": _step_key(step, index)})
                    if not result.get("ok") and failure is None:
                        failure = result.get("failure") or {"message": result.get("error", "step failed"), "class": FailureClass.DATA.value}
                    progress = True

                for index in sorted(list(pending)):
                    if failure is None or steps[index].always:
                        continue
                    if not dependency_map.get(index, set()).issubset(completed):
                        continue
                    summaries[index] = self._skipped_step(steps[index], index, "control-flow", context=context)
                    pending.remove(index)
                    completed.add(index)
                    audit.append("step.skipped", {"index": index, "key": _step_key(steps[index], index), "reason": "control-flow"})
                    progress = True

                slots = max_workers - len(active)
                if slots > 0:
                    for index in sorted(list(pending)):
                        if slots <= 0:
                            break
                        step = steps[index]
                        if failure is not None and not step.always:
                            continue
                        if not dependency_map.get(index, set()).issubset(completed):
                            continue
                        resources = {str(v).strip() for v in step.resources if str(v).strip()}
                        if resources & active_resources:
                            continue
                        pending.remove(index)
                        active_resources.update(resources)
                        audit.append("step.started", {"index": index, "key": _step_key(step, index), "resources": sorted(resources)})
                        active[pool.submit(self._run_one, step=step, step_index=index, context=context)] = (index, resources)
                        slots -= 1
                        progress = True

                if not progress and not active and pending:
                    blocked = [f"{index}:{_step_key(steps[index], index)}" for index in sorted(pending)]
                    raise ScenarioValidationError(f"execution deadlock; blocked steps: {', '.join(blocked)}")

        return [item for item in summaries if item is not None], failure

    def _run_cleanup_steps(self, *, scenario: Scenario, context: dict[str, Any], audit: _AuditLog | None) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
        cleanup: list[dict[str, Any]] = []
        failure: dict[str, Any] | None = None
        for index, step in enumerate(scenario.cleanup_steps):
            if audit:
                audit.append("cleanup.started", {"index": index, "key": _step_key(step, index)})
            result = self._run_one(step=step, step_index=index, context=context, phase="cleanup")
            cleanup.append(result)
            if audit:
                audit.append("cleanup.succeeded" if result.get("ok") else "cleanup.failed", {"index": index, "key": _step_key(step, index)})
            if not result.get("ok") and failure is None:
                failure = result.get("failure") or {"message": result.get("error", "cleanup failed"), "class": FailureClass.DATA.value}
        return cleanup, failure

    def _run_one(self, *, step: ScenarioStep, step_index: int, context: dict[str, Any], phase: str = "execution") -> dict[str, Any]:
        trace_id = str(context.get("vars", {}).get("traceId") or "")
        started_at = datetime.now(timezone.utc).isoformat()
        attempts: list[dict[str, Any]] = []
        last_error: dict[str, str] | None = None
        try:
            plugin = self.plugin_registry.resolve(step.type)
        except ContinuumError as err:
            return {
                "index": step_index,
                "name": step.name,
                "key": _step_key(step, step_index),
                "type": step.type,
                "phase": phase,
                "status": "failed",
                "ok": False,
                "attempts": [],
                "failure": {"message": str(err), "class": err.failure_class.value},
                "error": str(err),
                "publish": {},
                "exports": {},
                "startedAt": started_at,
                "endedAt": datetime.now(timezone.utc).isoformat(),
                "traceId": trace_id,
            }

        rendered = render_templates(step.with_, ctx=context)
        retry = _normalized_retry(step, rendered)
        step_input = {k: v for k, v in rendered.items() if k not in {"retries", "backoffMs"}}
        run_dir = Path(str(context.get("run_dir", "")))
        for attempt in range(1, int(retry.get("maxAttempts", 1)) + 1):
            attempt_dir = self.evidence_collector.attempt_dir(run_dir, step_index, step.name, attempt)
            try:
                result = plugin.run(step_name=step.name, step_with=step_input, ctx=context, step_index=step_index)
                attempt_path = context["write_json"](str(attempt_dir), "result.json", {"attempt": attempt, "ok": bool(result.ok), "details": result.details, "traceId": trace_id})
                attempts.append({"attempt": attempt, "ok": bool(result.ok), "details": result.details, "evidence": result.evidence_paths, "attemptPath": attempt_path})
                if bool(result.ok):
                    return {
                        "index": step_index,
                        "name": step.name,
                        "key": _step_key(step, step_index),
                        "type": step.type,
                        "phase": phase,
                        "status": "succeeded",
                        "ok": True,
                        "details": result.details,
                        "evidence": list(result.evidence_paths) + [attempt_path],
                        "attempts": attempts,
                        "exports": result.exports or {},
                        "publish": self._resolve_publish(step.publish or {}, result.details),
                        "startedAt": started_at,
                        "endedAt": datetime.now(timezone.utc).isoformat(),
                        "traceId": trace_id,
                    }
                last_error = {"message": f"Step returned unsuccessful status: {step.name}", "class": FailureClass.DATA.value}
            except ContinuumError as err:
                attempt_path = context["write_json"](str(attempt_dir), "result.json", {"attempt": attempt, "ok": False, "error": str(err), "failureClass": err.failure_class.value, "traceId": trace_id})
                attempts.append({"attempt": attempt, "ok": False, "error": str(err), "attemptPath": attempt_path})
                last_error = {"message": str(err), "class": err.failure_class.value}
            except Exception as err:
                attempt_path = context["write_json"](str(attempt_dir), "result.json", {"attempt": attempt, "ok": False, "error": str(err), "failureClass": FailureClass.INFRA.value, "traceId": trace_id})
                attempts.append({"attempt": attempt, "ok": False, "error": str(err), "attemptPath": attempt_path})
                last_error = {"message": str(err), "class": FailureClass.INFRA.value}
            if attempt < int(retry.get("maxAttempts", 1)) and int(retry.get("baseDelayMs", 0)) > 0:
                sleep(int(retry.get("baseDelayMs", 0)) / 1000)

        return {
            "index": step_index,
            "name": step.name,
            "key": _step_key(step, step_index),
            "type": step.type,
            "phase": phase,
            "status": "failed",
            "ok": False,
            "attempts": attempts,
            "failure": last_error or {"message": "step failed", "class": FailureClass.DATA.value},
            "error": (last_error or {}).get("message", "step failed"),
            "publish": {},
            "exports": {},
            "startedAt": started_at,
            "endedAt": datetime.now(timezone.utc).isoformat(),
            "traceId": trace_id,
        }

    def _resolve_publish(self, publish_map: dict[str, str], details: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for target, expr in publish_map.items():
            if not expr.startswith("$.details."):
                continue
            cur: Any = details
            ok = True
            for segment in expr[len("$.details.") :].split("."):
                if isinstance(cur, dict) and segment in cur:
                    cur = cur[segment]
                else:
                    ok = False
                    break
            if ok:
                out[target] = cur
        return out

    def _write_bundle_safely(
        self,
        *,
        run_id: str,
        scenario_source: Path,
        scenario_text: str,
        context_payload: dict[str, Any],
        summary: dict[str, Any],
        manifest_payload: dict[str, Any],
    ) -> None:
        try:
            self.evidence_collector.write_run_bundle(
                run_id=run_id,
                scenario_source=scenario_source,
                scenario_text=scenario_text,
                context_payload=context_payload,
                summary=summary,
                manifest_payload=manifest_payload,
            )
        except Exception as err:
            fallback = dict(summary)
            fallback["status"] = "failed"
            fallback["failure"] = fallback.get("failure") or {"message": f"failed to write run bundle: {err}", "class": FailureClass.INFRA.value}
            run_dir = Path("runs") / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "scenario.yaml").write_text(scenario_text, encoding="utf-8")
            (run_dir / "context.json").write_text(json.dumps(context_payload, indent=2, sort_keys=True), encoding="utf-8")
            (run_dir / "summary.json").write_text(json.dumps(fallback, indent=2, sort_keys=True), encoding="utf-8")

    def _resolve_trace_id(self, *, scenario_text: str, run_id: str, vars_payload: dict[str, Any]) -> str:
        explicit = vars_payload.get("traceId")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        return f"{run_id}-{hashlib.sha1(scenario_text.encode('utf-8')).hexdigest()[:8]}"

    def _enforce_governance(
        self,
        *,
        scenario: Scenario,
        run_id: str,
        trace_id: str,
        actor: str | None,
        actor_roles: tuple[str, ...],
        approval_file: str | None,
        run_dir: Path,
        redactor: _PayloadRedactor,
    ) -> dict[str, Any]:
        cfg = dict(getattr(scenario, "governance", {}) or {})
        roles = sorted({str(v).strip() for v in actor_roles if isinstance(v, str) and v.strip()})
        allowed_roles = sorted({str(v).strip() for v in (cfg.get("allowedRoles", cfg.get("requiredRoles", [])) or []) if str(v).strip()})
        if allowed_roles and not (set(roles) & set(allowed_roles)):
            raise StepExecutionError(f"RBAC denied: actor roles {roles or ['<none>']} do not satisfy allowed roles {allowed_roles}")
        approval_result: dict[str, Any] = {"required": False, "verified": True}
        approval_path_value = approval_file or cfg.get("approvalFile")
        if cfg.get("requireApproval", False) or approval_path_value:
            approval_result = {"required": True, "verified": False}
            if not isinstance(approval_path_value, str) or not approval_path_value.strip():
                raise StepExecutionError("approval is required but no approval file was provided")
            approval_path = Path(approval_path_value)
            if not approval_path.is_file():
                raise StepExecutionError(f"approval file not found: {approval_path}")
            record = self._match_approval_record(
                approval_payload=json.loads(approval_path.read_text(encoding="utf-8")),
                scenario_name=scenario.name,
                run_id=run_id,
                trace_id=trace_id,
                approval_id=str(cfg.get("approvalId", "") or ""),
            )
            if record is None:
                raise StepExecutionError("approval file does not contain a matching approved record")
            approval_result = {"required": True, "verified": True, "file": str(approval_path), "approvalId": record.get("approvalId"), "approvedBy": record.get("approvedBy"), "approvedAt": record.get("approvedAt")}
        governance = {"actor": str(actor or os.environ.get("CONTINUUM_ACTOR") or "").strip() or None, "roles": roles, "allowedRoles": allowed_roles, "approval": approval_result}
        self.evidence_collector.write_json(run_dir / "governance.json", redactor.redact(governance))
        return governance

    def _match_approval_record(self, *, approval_payload: Any, scenario_name: str, run_id: str, trace_id: str, approval_id: str) -> dict[str, Any] | None:
        records: list[dict[str, Any]] = []
        if isinstance(approval_payload, list):
            records = [item for item in approval_payload if isinstance(item, dict)]
        elif isinstance(approval_payload, dict):
            nested = approval_payload.get("approvals")
            records = [item for item in nested if isinstance(item, dict)] if isinstance(nested, list) else [approval_payload]
        for record in records:
            if str(record.get("status", "")).strip().lower() != "approved":
                continue
            if approval_id and str(record.get("approvalId", "")).strip() != approval_id:
                continue
            scenario_value = str(record.get("scenario", "")).strip()
            if scenario_value and scenario_value != scenario_name:
                continue
            run_value = str(record.get("runId", "")).strip()
            if run_value and run_value != run_id:
                continue
            trace_value = str(record.get("traceId", "")).strip()
            if trace_value and trace_value != trace_id:
                continue
            return record
        return None

    def _load_resume_bundle(self, resume_run_id: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if not resume_run_id:
            return None, None
        run_dir = Path("runs") / resume_run_id
        summary_path = run_dir / "summary.json"
        context_path = run_dir / "context.json"
        if not summary_path.is_file() or not context_path.is_file():
            raise StepExecutionError(f"resume context not found for run '{resume_run_id}'")
        return json.loads(summary_path.read_text(encoding="utf-8")), json.loads(context_path.read_text(encoding="utf-8"))

    def _build_previous_status_map(self, summary: dict[str, Any] | None) -> dict[str, str]:
        out: dict[str, str] = {}
        if isinstance(summary, dict):
            for item in summary.get("steps", []):
                if isinstance(item, dict) and isinstance(item.get("key"), str) and isinstance(item.get("status"), str):
                    out[item["key"]] = item["status"]
        return out

    def _first_failed_index(self, summary: dict[str, Any] | None) -> int | None:
        if not isinstance(summary, dict):
            return None
        for item in summary.get("steps", []):
            if isinstance(item, dict) and item.get("status") == "failed" and isinstance(item.get("index"), int):
                return int(item["index"])
        return None

    def _matches_selector(self, step: ScenarioStep, index: int, selector: str) -> bool:
        sel = str(selector).strip()
        if not sel:
            return False
        return sel in {f"{index + 1:02d}", str(index), step.key, step.name, step.type}

    def _selected_by(self, step: ScenarioStep, index: int, selectors: tuple[str, ...]) -> bool:
        return any(self._matches_selector(step, index, selector) for selector in selectors)

    def _selector_index(self, steps: tuple[ScenarioStep, ...], selector: str | None) -> int | None:
        if not selector:
            return None
        for index, step in enumerate(steps):
            if self._matches_selector(step, index, selector):
                return index
        return None

    def _merge_step_outputs(
        self,
        *,
        step: ScenarioStep,
        step_index: int,
        step_summary: dict[str, Any],
        context: dict[str, Any],
        lock: Lock,
    ) -> None:
        with lock:
            if isinstance(step_summary.get("publish"), dict):
                context["vars"].update(step_summary["publish"])
            if isinstance(step_summary.get("exports"), dict):
                exports = step_summary["exports"]
                context["vars"].update(exports)
                steps_ns = context["vars"].setdefault("steps", {})
                if isinstance(steps_ns, dict):
                    steps_ns[_step_key(step, step_index)] = exports

    def _skipped_step(self, step: ScenarioStep, index: int, reason: str, *, context: dict[str, Any], phase: str = "execution") -> dict[str, Any]:
        payload = {"index": index, "name": step.name, "key": _step_key(step, index), "type": step.type, "phase": phase, "status": "skipped", "ok": True, "skipReason": reason, "attempts": [], "publish": {}, "exports": {}, "traceId": str(context.get("vars", {}).get("traceId") or "")}
        context["write_json"](context["step_dir"](index, step.name), "skipped.json", payload)
        return payload

    def _ensure_services(self, *, scenario: Scenario, context: dict[str, Any], run_dir: Path, no_services: bool, reuse_sessions: bool, audit: _AuditLog | None) -> dict[str, dict[str, Any]]:
        service_states: dict[str, dict[str, Any]] = {}
        if no_services or not scenario.services:
            return service_states
        registry = self._load_session_registry()
        for service_name, service_cfg in scenario.services.items():
            cfg = render_templates(service_cfg, ctx=context)
            service_type = str(cfg.get("type", ""))
            if service_type != "applauncher":
                raise StepExecutionError(f"unsupported service type '{service_type}' for service '{service_name}'")
            if audit:
                audit.append("service.ensure.started", {"service": service_name})
            exports, verify_evidence = ensure_applauncher_session(
                cfg,
                session_registry=registry,
                allow_reuse=reuse_sessions,
                extra_env={"CONTINUUM_TRACE_ID": str(context.get("vars", {}).get("traceId") or ""), "CONTINUUM_RUN_ID": str(context.get("run_id") or "")},
            )
            service_states[service_name] = {"type": service_type, **exports, "stopOnExit": bool(cfg.get("stopOnExit", False)), "session": cfg.get("session")}
            services_ns = context["vars"].setdefault("services", {})
            if isinstance(services_ns, dict):
                services_ns[service_name] = service_states[service_name]
            evidence_root = run_dir / "evidence" / "00-services" / service_name
            self.evidence_collector.write_json(evidence_root / "verify.json", verify_evidence)
            self.evidence_collector.write_json(evidence_root / "service_env.json", verify_evidence.get("env", {}))
            if audit:
                audit.append("service.ensure.finished", {"service": service_name, "reused": bool(exports.get("reused"))})
        self.evidence_collector.write_json(run_dir / "services.json", service_states)
        self._write_session_registry(registry)
        return service_states

    def _stop_services(self, *, service_states: dict[str, dict[str, Any]], stop_services: bool, audit: _AuditLog | None = None) -> dict[str, Any]:
        cleanup: dict[str, Any] = {}
        if not service_states:
            return cleanup
        registry = self._load_session_registry()
        for service_name, state in service_states.items():
            should_stop = stop_services or bool(state.get("stopOnExit", False))
            if not should_stop:
                cleanup[service_name] = {"stopped": False}
                continue
            pid = state.get("pid")
            if pid:
                try:
                    os.kill(int(pid), signal.SIGTERM)
                    cleanup[service_name] = {"stopped": True, "pid": int(pid)}
                except ProcessLookupError:
                    cleanup[service_name] = {"stopped": False, "pid": int(pid), "reason": "not-found"}
                except Exception as err:
                    cleanup[service_name] = {"stopped": False, "pid": int(pid), "reason": str(err)}
            else:
                cleanup[service_name] = {"stopped": False, "pid": None}
            session_name = state.get("session")
            if isinstance(session_name, str):
                registry.pop(session_name, None)
            if audit:
                audit.append("service.stop.finished", {"service": service_name, **cleanup[service_name]})
        self._write_session_registry(registry)
        return cleanup

    def _session_registry_path(self) -> Path:
        return Path("runs") / ".service-sessions.json"

    def _load_session_registry(self) -> dict[str, Any]:
        path = self._session_registry_path()
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_session_registry(self, payload: dict[str, Any]) -> None:
        path = self._session_registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(out.get(key), dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def validate_scenario(scenario: Scenario, *, plugin_registry: PluginRegistry, env: dict[str, str] | None = None) -> tuple[list[str], list[str]]:
    env_map = dict(env or os.environ)
    errors: list[str] = []
    warnings: list[str] = []
    ctx = {"run_id": "validate", "run_dir": "runs/validate", "env": env_map, "vars": dict(scenario.vars)}

    try:
        runtime = DeterministicRuntime(plugin_registry=plugin_registry, evidence_collector=EvidenceCollector())
        dep_map = runtime._dependency_index_map(scenario.steps)
        runtime._validate_dependency_map(dep_map)
    except ContinuumError as err:
        errors.append(str(err))

    keys = {_step_key(step, i) for i, step in enumerate(scenario.steps)}
    for index, step in enumerate(scenario.steps):
        unknown = find_unknown_templates(step.with_, ctx=ctx)
        if unknown:
            errors.append(f"step {index} ({step.name}): unknown template keys: {', '.join(unknown)}")
        if step.legacy_retry_used:
            warnings.append(f"step {index} ({step.name}): uses legacy with.retries/backoffMs; normalized to step.retry")
        for dep in _step_dependencies(scenario.steps, index):
            if dep not in keys:
                errors.append(f"step {index} ({step.name}): unknown dependsOn key '{dep}'")

        if step.type == "postman.run" and not bool(step.with_.get("allowMissingDependency", False)) and not shutil.which("newman"):
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
            files = resolve_attach_files(render_templates(step.with_, ctx=ctx), ctx["run_dir"])
            warnings.append(f"step {index} ({step.name}): jira.attach would attach {len(files)} file(s)")

        try:
            plugin = plugin_registry.resolve(step.type)
            preflight = getattr(plugin, "preflight", None)
            if callable(preflight):
                result = preflight(step_with=render_templates(step.with_, ctx=ctx), ctx=ctx)
                if isinstance(result, dict) and not bool(result.get("ok", True)):
                    if step.type == "postman.run" and bool(step.with_.get("allowMissingDependency", False)):
                        continue
                    missing = ", ".join(str(v) for v in (result.get("missing") or []))
                    errors.append(f"step {index} ({step.name}): preflight failed{': ' + missing if missing else ''}")
        except Exception as err:
            errors.append(f"step {index} ({step.name}): {err}")

    return errors, warnings
