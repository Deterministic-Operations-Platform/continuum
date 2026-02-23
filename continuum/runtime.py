"""Runtime interface and deterministic implementation."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import json
from pathlib import Path
import os
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
        retry = _normalized_retry(step, rendered)
        step_dir = run_dir / "evidence" / f"{index + 1:02d}-{step.name}"
        attempts = [str(step_dir / f"attempt-{attempt:02d}") for attempt in range(1, int(retry["maxAttempts"]) + 1)]
        attach_files = resolve_attach_files(rendered, str(run_dir)) if step.type == "jira.attach" else []
        depends_on = list(step.depends_on) if step.depends_on is not None else ([_step_key(scenario.steps[index - 1], index - 1)] if index > 0 else [])
        steps.append(
            {
                "index": index,
                "key": _step_key(step, index),
                "name": step.name,
                "type": step.type,
                "always": step.always,
                "dependsOn": depends_on,
                "resources": list(step.resources),
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
        from_selector: str | None = None,
        to_selector: str | None = None,
        only_selectors: tuple[str, ...] | list[str] = (),
        skip_selectors: tuple[str, ...] | list[str] = (),
        rerun_selectors: tuple[str, ...] | list[str] = (),
        from_failure: bool = False,
        no_cleanup: bool = False,
        max_parallel: int = 4,
        no_parallel: bool = False,
    ) -> dict[str, Any]:
        resolved_run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        run_dir = Path("runs") / resolved_run_id
        resolved_resume_id = resume_id or resume_run_id

        previous_summary, previous_context = self._load_resume_bundle(resolved_resume_id)
        prev_status_by_key = self._build_previous_status_map(previous_summary)
        prev_vars = (previous_context or {}).get("vars", {})

        warnings = [
            f"step '{step.name}' uses legacy with.retries/backoffMs shorthand; normalized into step.retry"
            for step in [*scenario.steps, *scenario.cleanup_steps]
            if step.legacy_retry_used
        ]

        context: dict[str, Any] = {
            "run_id": resolved_run_id,
            "run_dir": str(run_dir),
            "vars": _deep_merge(dict(prev_vars if isinstance(prev_vars, dict) else {}), dict(scenario.vars)),
            "env": dict(os.environ),
            "step_dir": lambda i, n: str(self.evidence_collector.step_dir(run_dir, i, n)),
            "write_json": lambda step_path, filename, payload: self.evidence_collector.write_json(Path(step_path) / filename, payload),
        }

        service_states = self._ensure_services(
            scenario=scenario,
            context=context,
            run_dir=run_dir,
            no_services=no_services,
            reuse_sessions=reuse_sessions,
        )

        selection = self._selection_map(
            scenario.steps,
            from_selector=from_selector,
            to_selector=to_selector,
            only_selectors=tuple(only_selectors),
            skip_selectors=tuple(skip_selectors),
            prev_status_by_key=prev_status_by_key,
            rerun_selectors=tuple(rerun_selectors),
            from_failure=from_failure,
            previous_summary=previous_summary,
        )

        summary_steps, failure = self._run_steps_parallel(
            steps=scenario.steps,
            context=context,
            selection=selection,
            max_parallel=1 if no_parallel else max(1, int(max_parallel)),
        )

        cleanup_steps: list[dict[str, Any]] = []
        if not no_cleanup:
            for index, step in enumerate(scenario.cleanup_steps):
                cleanup_steps.append(self._run_one(step=step, step_index=index, context=context, phase="cleanup"))

        service_cleanup = self._stop_services(
            scenario=scenario,
            service_states=service_states,
            stop_services=stop_services,
        )

        summary = {
            "run_id": resolved_run_id,
            "resumedFrom": resolved_resume_id,
            "scenario": {"name": scenario.name, "rail": scenario.rail, "steps": len(scenario.steps)},
            "status": "failed" if failure else "succeeded",
            "steps": summary_steps,
            "cleanup_steps": cleanup_steps,
            "services": service_states,
            "service_cleanup": service_cleanup,
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

    def _run_steps_parallel(
        self,
        *,
        steps: tuple[ScenarioStep, ...],
        context: dict[str, Any],
        selection: dict[int, str | None],
        max_parallel: int,
    ) -> tuple[list[dict[str, Any]], dict[str, str] | None]:
        key_to_index = {_step_key(step, i): i for i, step in enumerate(steps)}
        self._validate_dag(steps, key_to_index)
        deps = {
            i: (list(step.depends_on) if step.depends_on is not None else ([_step_key(steps[i - 1], i - 1)] if i > 0 else []))
            for i, step in enumerate(steps)
        }
        reverse: dict[int, list[int]] = {i: [] for i in range(len(steps))}
        for idx, dep_keys in deps.items():
            for dep_key in dep_keys:
                reverse[key_to_index[dep_key]].append(idx)

        status: list[str] = ["pending"] * len(steps)
        results: list[dict[str, Any] | None] = [None] * len(steps)
        failure: dict[str, str] | None = None

        for idx, reason in selection.items():
            if reason:
                status[idx] = "skipped"
                results[idx] = self._skipped_summary(steps[idx], idx, reason, context)

        context_lock = Lock()
        resource_locks: dict[str, Lock] = {}

        def job(idx: int) -> dict[str, Any]:
            step = steps[idx]
            acquired: list[Lock] = []
            for name in sorted(set(step.resources)):
                lock = resource_locks.setdefault(name, Lock())
                lock.acquire()
                acquired.append(lock)
            try:
                return self._run_one(step=step, step_index=idx, context=context)
            finally:
                for lock in reversed(acquired):
                    lock.release()

        futures: dict[Future[dict[str, Any]], int] = {}
        with ThreadPoolExecutor(max_workers=max_parallel) as pool:
            while True:
                progress = False
                for idx in range(len(steps)):
                    if status[idx] != "pending":
                        continue
                    dep_statuses = [status[key_to_index[d]] for d in deps[idx]]
                    if any(s in {"pending", "running"} for s in dep_statuses):
                        continue
                    if any(s == "failed" for s in dep_statuses):
                        status[idx] = "skipped"
                        results[idx] = self._skipped_summary(steps[idx], idx, "dependency-failed", context)
                        progress = True
                        continue
                    if failure and not steps[idx].always:
                        status[idx] = "skipped"
                        results[idx] = self._skipped_summary(steps[idx], idx, "control-flow", context)
                        progress = True
                        continue

                    status[idx] = "running"
                    futures[pool.submit(job, idx)] = idx
                    progress = True

                if not futures:
                    if not progress:
                        break
                    continue

                done, _ = wait(list(futures.keys()), return_when=FIRST_COMPLETED)
                for fut in done:
                    idx = futures.pop(fut)
                    summary = fut.result()
                    status[idx] = "succeeded" if summary.get("ok") else "failed"
                    results[idx] = summary
                    with context_lock:
                        if summary.get("publish"):
                            context["vars"].update(summary["publish"])
                        if summary.get("exports"):
                            exports = summary["exports"]
                            context["vars"].update(exports)
                            steps_ns = context["vars"].setdefault("steps", {})
                            if isinstance(steps_ns, dict):
                                steps_ns[_step_key(steps[idx], idx)] = exports
                    if not summary.get("ok") and failure is None:
                        failure = summary.get("failure") or {
                            "message": summary.get("error", "step failed"),
                            "class": FailureClass.DATA.value,
                        }

        final_results = [r or self._skipped_summary(steps[i], i, "control-flow", context) for i, r in enumerate(results)]
        return final_results, failure

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
    ) -> dict[int, str | None]:
        selected = [True] * len(steps)

        if from_selector or to_selector:
            start = self._resolve_selector_index(steps, from_selector) if from_selector else 0
            end = self._resolve_selector_index(steps, to_selector) if to_selector else len(steps) - 1
            for i in range(len(steps)):
                selected[i] = start <= i <= end

        if only_selectors:
            selected = [self._matches_any_selector(step, i, only_selectors) for i, step in enumerate(steps)]

        for i, step in enumerate(steps):
            if self._matches_any_selector(step, i, skip_selectors):
                selected[i] = False

        if from_failure and previous_summary:
            first_failed = None
            for prev in previous_summary.get("steps", []):
                if prev.get("status") == "failed":
                    first_failed = int(prev.get("index", 0))
                    break
            if first_failed is not None:
                for i in range(first_failed):
                    selected[i] = False

        reasons: dict[int, str | None] = {i: None for i in range(len(steps))}
        for i, step in enumerate(steps):
            if not selected[i]:
                reasons[i] = "control-flow"
                continue
            if prev_status_by_key.get(_step_key(step, i)) == "succeeded" and not self._matches_any_selector(step, i, rerun_selectors):
                reasons[i] = "resume:succeeded"
        return reasons

    def _resolve_selector_index(self, steps: tuple[ScenarioStep, ...], selector: str) -> int:
        for i, step in enumerate(steps):
            if self._matches_selector(step, i, selector):
                return i
        raise ScenarioValidationError(f"selector '{selector}' did not match any step")

    def _matches_any_selector(self, step: ScenarioStep, index: int, selectors: tuple[str, ...] | list[str]) -> bool:
        return any(self._matches_selector(step, index, sel) for sel in selectors if sel)

    def _matches_selector(self, step: ScenarioStep, index: int, selector: str) -> bool:
        normalized = selector.strip()
        candidates = {_step_key(step, index), step.name, step.type, str(index + 1), f"{index + 1:02d}"}
        return normalized in candidates

    def _validate_dag(self, steps: tuple[ScenarioStep, ...], key_to_index: dict[str, int]) -> None:
        for idx, step in enumerate(steps):
            dep_keys = step.depends_on if step.depends_on is not None else (() if idx == 0 else (_step_key(steps[idx - 1], idx - 1),))
            for dep in dep_keys:
                if dep not in key_to_index:
                    raise ScenarioValidationError(f"step '{_step_key(step, idx)}' depends on unknown step '{dep}'")

        visited: dict[int, int] = {}

        def dfs(i: int) -> None:
            state = visited.get(i, 0)
            if state == 1:
                raise ScenarioValidationError("step dependency graph contains a cycle")
            if state == 2:
                return
            visited[i] = 1
            deps = steps[i].depends_on if steps[i].depends_on is not None else (() if i == 0 else (_step_key(steps[i - 1], i - 1),))
            for dep in deps:
                dfs(key_to_index[dep])
            visited[i] = 2

        for i in range(len(steps)):
            dfs(i)

    def _skipped_summary(self, step: ScenarioStep, idx: int, reason: str, context: dict[str, Any]) -> dict[str, Any]:
        step_dir = Path(context["step_dir"](idx, step.name))
        self.evidence_collector.write_json(step_dir / "skipped.json", {"status": "skipped", "reason": reason})
        now = datetime.now(timezone.utc).isoformat()
        return {
            "index": idx,
            "name": step.name,
            "key": _step_key(step, idx),
            "type": step.type,
            "phase": "execution",
            "status": "skipped",
            "ok": True,
            "attempts": [],
            "publish": {},
            "exports": {},
            "skipReason": reason,
            "startedAt": now,
            "endedAt": now,
        }

    def _load_resume_bundle(self, resume_id: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if not resume_id:
            return None, None
        root = Path("runs") / resume_id
        summary_path = root / "summary.json"
        context_path = root / "context.json"
        if not summary_path.is_file() or not context_path.is_file():
            raise StepExecutionError(f"resume bundle not found for run '{resume_id}'")
        return (
            json.loads(summary_path.read_text(encoding="utf-8")),
            json.loads(context_path.read_text(encoding="utf-8")),
        )

    def _build_previous_status_map(self, previous_summary: dict[str, Any] | None) -> dict[str, str]:
        if not previous_summary:
            return {}
        mapping: dict[str, str] = {}
        for step in previous_summary.get("steps", []):
            key = step.get("key")
            status = step.get("status")
            if isinstance(key, str) and isinstance(status, str):
                mapping[key] = status
        return mapping

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

    def _ensure_services(
        self,
        *,
        scenario: Scenario,
        context: dict[str, Any],
        run_dir: Path,
        no_services: bool,
        reuse_sessions: bool,
    ) -> dict[str, dict[str, Any]]:
        service_defs = scenario.services or {}
        service_states: dict[str, dict[str, Any]] = {}
        if no_services or not service_defs:
            return service_states

        registry = self._load_session_registry()
        for service_name, service_cfg in service_defs.items():
            cfg = render_templates(service_cfg, ctx=context)
            service_type = str(cfg.get("type", ""))
            evidence_root = run_dir / "evidence" / "00-services" / service_name
            if service_type == "applauncher":
                exports, verify_evidence = ensure_applauncher_session(
                    cfg,
                    session_registry=registry,
                    allow_reuse=reuse_sessions,
                )
            else:
                raise StepExecutionError(f"unsupported service type '{service_type}' for service '{service_name}'")

            service_states[service_name] = {
                "type": service_type,
                **exports,
                "stopOnExit": bool(cfg.get("stopOnExit", False)),
                "session": cfg.get("session"),
            }
            services_ns = context["vars"].setdefault("services", {})
            if isinstance(services_ns, dict):
                services_ns[service_name] = service_states[service_name]

            self.evidence_collector.write_json(evidence_root / "verify.json", verify_evidence)

        self.evidence_collector.write_json(run_dir / "services.json", service_states)
        self._write_session_registry(registry)
        return service_states

    def _stop_services(self, *, scenario: Scenario, service_states: dict[str, dict[str, Any]], stop_services: bool) -> dict[str, Any]:
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
            else:
                cleanup[service_name] = {"stopped": False, "pid": None}

            session_name = state.get("session")
            if isinstance(session_name, str) and session_name in registry:
                registry.pop(session_name, None)

        self._write_session_registry(registry)
        return cleanup

    def _run_one(self, *, step: Any, step_index: int, context: dict[str, Any], phase: str = "execution") -> dict[str, Any]:
        plugin = self.plugin_registry.resolve(step.type)
        rendered = render_templates(step.with_, ctx=context)
        retry = _normalized_retry(step, rendered)
        step_input = {k: v for k, v in rendered.items() if k not in {"retries", "backoffMs"}}

        attempts: list[dict[str, Any]] = []
        last_error: dict[str, str] | None = None
        started_at = datetime.now(timezone.utc).isoformat()
        for attempt in range(1, int(retry.get("maxAttempts", 1)) + 1):
            try:
                result = plugin.run(step_name=step.name, step_with=step_input, ctx=context, step_index=step_index)
                attempts.append({"attempt": attempt, "ok": result.ok, "details": result.details, "evidence": result.evidence_paths})
                summary = {
                    "index": step_index,
                    "name": step.name,
                    "key": _step_key(step, step_index),
                    "type": step.type,
                    "phase": phase,
                    "status": "succeeded" if result.ok else "failed",
                    "ok": result.ok,
                    "details": result.details,
                    "evidence": result.evidence_paths,
                    "attempts": attempts,
                    "exports": result.exports or {},
                    "publish": self._resolve_publish(step.publish or {}, result.details),
                    "startedAt": started_at,
                    "endedAt": datetime.now(timezone.utc).isoformat(),
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
            "key": _step_key(step, step_index),
            "type": step.type,
            "phase": phase,
            "status": "failed",
            "ok": False,
            "attempts": attempts,
            "failure": last_error,
            "error": (last_error or {}).get("message", "step failed"),
            "publish": {},
            "exports": {},
            "startedAt": started_at,
            "endedAt": datetime.now(timezone.utc).isoformat(),
        }

    def _resolve_publish(self, publish_map: dict[str, str], details: dict[str, Any]) -> dict[str, Any]:
        published: dict[str, Any] = {}
        for target, expr in publish_map.items():
            if not expr.startswith("$.details."):
                continue
            cur: Any = details
            ok = True
            for seg in expr[len("$.details.") :].split("."):
                if isinstance(cur, dict) and seg in cur:
                    cur = cur[seg]
                else:
                    ok = False
                    break
            if ok:
                published[target] = cur
        return published


def _normalized_retry(step: ScenarioStep, rendered: dict[str, Any]) -> dict[str, Any]:
    retry = step.retry
    if retry is None and ("retries" in rendered or "backoffMs" in rendered):
        retry = {
            "on": ["exception"],
            "maxAttempts": int(rendered.get("retries", 0)) + 1,
            "backoff": "fixed",
            "baseDelayMs": int(rendered.get("backoffMs", 0)),
            "maxDelayMs": int(rendered.get("backoffMs", 0)),
            "jitter": 0.0,
        }
    return retry or {
        "on": ["exception"],
        "maxAttempts": 1,
        "backoff": "fixed",
        "baseDelayMs": 0,
        "maxDelayMs": 0,
        "jitter": 0.0,
    }


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged[key]), value)
        else:
            merged[key] = value
    return merged


def _step_key(step: ScenarioStep, index: int) -> str:
    return step.key or f"{index + 1:02d}"


def validate_scenario(scenario: Scenario, *, plugin_registry: PluginRegistry, env: dict[str, str] | None = None) -> tuple[list[str], list[str]]:
    env_map = dict(env or os.environ)
    errors: list[str] = []
    warnings: list[str] = []
    ctx = {"run_id": "validate", "run_dir": "runs/validate", "env": env_map, "vars": dict(scenario.vars)}

    keys = {_step_key(step, i) for i, step in enumerate(scenario.steps)}
    for index, step in enumerate(scenario.steps):
        unknown = find_unknown_templates(step.with_, ctx=ctx)
        if unknown:
            errors.append(f"step {index} ({step.name}): unknown template keys: {', '.join(unknown)}")
        if step.legacy_retry_used:
            warnings.append(f"step {index} ({step.name}): uses legacy with.retries/backoffMs; normalized to step.retry")
        for dep in (step.depends_on or ()):
            if dep not in keys:
                errors.append(f"step {index} ({step.name}): unknown dependsOn key '{dep}'")

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
