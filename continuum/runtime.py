"""Runtime interface and deterministic implementation."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import os
import shutil
import signal
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
        # backwards-compatible knobs used in tests
        resume_id: str | None = None,
        rerun_selectors: tuple[str, ...] | list[str] = (),
        from_failure: bool = False,
        from_selector: str | None = None,
        to_selector: str | None = None,
        only_selectors: tuple[str, ...] | list[str] = (),
        skip_selectors: tuple[str, ...] | list[str] = (),
        no_cleanup: bool = False,
        cli_vars: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        run_dir = Path("runs") / resolved_run_id
        effective_resume_id = resume_run_id or resume_id

        warnings = [
            f"step '{step.name}' uses legacy with.retries/backoffMs shorthand; normalized into step.retry"
            for step in [*scenario.steps, *scenario.cleanup_steps]
            if step.legacy_retry_used
        ]

        previous_summary, previous_context = self._load_resume_bundle(effective_resume_id)
        prev_status_by_key = self._build_previous_status_map(previous_summary)
        prev_vars = (previous_context or {}).get("vars", {})

        vars_payload = _deep_merge(dict(prev_vars if isinstance(prev_vars, dict) else {}), dict(scenario.vars))
        vars_payload = _deep_merge(vars_payload, dict(cli_vars or {}))
        trace_id = self._resolve_trace_id(scenario_text=scenario_text, run_id=resolved_run_id, vars_payload=vars_payload)
        vars_payload["traceId"] = trace_id

        context: dict[str, Any] = {
            "run_id": resolved_run_id,
            "run_dir": str(run_dir),
            "vars": vars_payload,
            "env": dict(os.environ),
            "step_dir": lambda i, n: str(self.evidence_collector.step_dir(run_dir, i, n)),
            "write_json": lambda step_path, filename, payload: self.evidence_collector.write_json(Path(step_path) / filename, payload),
        }
        self.evidence_collector.write_json(run_dir / "trace.json", {"runId": resolved_run_id, "traceId": trace_id})

        service_states = self._ensure_services(
            scenario=scenario,
            context=context,
            run_dir=run_dir,
            no_services=no_services,
            reuse_sessions=reuse_sessions,
        )

        summary_steps: list[dict[str, Any]] = []
        cleanup_steps: list[dict[str, Any]] = []
        failure: dict[str, str] | None = None

        first_failed_index = self._first_failed_index(previous_summary) if from_failure else None

        for index, step in enumerate(scenario.steps):
            should_skip = self._should_skip_step(
                step=step,
                index=index,
                scenario=scenario,
                from_selector=from_selector,
                to_selector=to_selector,
                only_selectors=tuple(only_selectors),
                skip_selectors=tuple(skip_selectors),
                from_failure_index=first_failed_index,
                prev_status_by_key=prev_status_by_key,
                rerun_selectors=tuple(rerun_selectors),
                failure_present=failure is not None,
            )
            if should_skip is not None:
                summary_steps.append(self._skipped_step(step, index, should_skip, context=context))
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

        if not no_cleanup:
            for index, step in enumerate(scenario.cleanup_steps):
                cleanup_summary = self._run_one(step=step, step_index=index, context=context, phase="cleanup")
                cleanup_steps.append(cleanup_summary)

        service_cleanup = self._stop_services(service_states=service_states, stop_services=stop_services)

        summary = {
            "run_id": resolved_run_id,
            "traceId": trace_id,
            "resumedFrom": effective_resume_id,
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

    def _resolve_trace_id(self, *, scenario_text: str, run_id: str, vars_payload: dict[str, Any]) -> str:
        explicit = vars_payload.get("traceId")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()
        digest = hashlib.sha1(scenario_text.encode("utf-8")).hexdigest()[:8]
        return f"{run_id}-{digest}"

    def _load_resume_bundle(self, resume_run_id: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if not resume_run_id:
            return None, None
        run_dir = Path("runs") / resume_run_id
        summary_path = run_dir / "summary.json"
        context_path = run_dir / "context.json"
        if not summary_path.is_file() or not context_path.is_file():
            raise StepExecutionError(f"resume context not found for run '{resume_run_id}'")
        return (
            json.loads(summary_path.read_text(encoding="utf-8")),
            json.loads(context_path.read_text(encoding="utf-8")),
        )

    def _build_previous_status_map(self, summary: dict[str, Any] | None) -> dict[str, str]:
        if not isinstance(summary, dict):
            return {}
        out: dict[str, str] = {}
        for item in summary.get("steps", []):
            if isinstance(item, dict):
                key = item.get("key")
                status = item.get("status")
                if isinstance(key, str) and isinstance(status, str):
                    out[key] = status
        return out

    def _first_failed_index(self, summary: dict[str, Any] | None) -> int | None:
        if not isinstance(summary, dict):
            return None
        for item in summary.get("steps", []):
            if isinstance(item, dict) and item.get("status") == "failed":
                idx = item.get("index")
                if isinstance(idx, int):
                    return idx
        return None

    def _matches_selector(self, step: ScenarioStep, index: int, selector: str) -> bool:
        sel = str(selector).strip()
        if not sel:
            return False
        step_num = f"{index + 1:02d}"
        return sel in {step_num, str(index), step.key, step.name, step.type}

    def _selected_by(self, step: ScenarioStep, index: int, selectors: tuple[str, ...]) -> bool:
        return any(self._matches_selector(step, index, selector) for selector in selectors)

    def _should_skip_step(
        self,
        *,
        step: ScenarioStep,
        index: int,
        scenario: Scenario,
        from_selector: str | None,
        to_selector: str | None,
        only_selectors: tuple[str, ...],
        skip_selectors: tuple[str, ...],
        from_failure_index: int | None,
        prev_status_by_key: dict[str, str],
        rerun_selectors: tuple[str, ...],
        failure_present: bool,
    ) -> str | None:
        if failure_present and not step.always:
            return "control-flow"

        if from_failure_index is not None and index < from_failure_index:
            return "control-flow"

        if from_selector:
            start_idx = self._selector_index(scenario.steps, from_selector)
            if start_idx is None:
                raise StepExecutionError(f"Unknown --from selector: {from_selector}")
            if index < start_idx:
                return "selector"
        if to_selector:
            end_idx = self._selector_index(scenario.steps, to_selector)
            if end_idx is None:
                raise StepExecutionError(f"Unknown --to selector: {to_selector}")
            if index > end_idx:
                return "selector"

        if only_selectors and not self._selected_by(step, index, only_selectors):
            return "selector"
        if skip_selectors and self._selected_by(step, index, skip_selectors):
            return "selector"

        if prev_status_by_key and step.key in prev_status_by_key and step.key not in rerun_selectors:
            if prev_status_by_key.get(step.key) == "succeeded":
                return "resume:succeeded"

        return None

    def _selector_index(self, steps: tuple[ScenarioStep, ...], selector: str) -> int | None:
        for i, step in enumerate(steps):
            if self._matches_selector(step, i, selector):
                return i
        return None

    def _skipped_step(self, step: ScenarioStep, index: int, reason: str, *, context: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "index": index,
            "name": step.name,
            "key": step.key,
            "type": step.type,
            "phase": "execution",
            "status": "skipped",
            "ok": True,
            "skipReason": reason,
            "attempts": [],
            "publish": {},
            "exports": {},
        }
        context["write_json"](context["step_dir"](index, step.name), "skipped.json", payload)
        return payload

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
                    extra_env={
                        "CONTINUUM_TRACE_ID": str(context.get("vars", {}).get("traceId") or ""),
                        "CONTINUUM_RUN_ID": str(context.get("run_id") or ""),
                    },
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
            self.evidence_collector.write_json(evidence_root / "service_env.json", verify_evidence.get("env", {}))

        self.evidence_collector.write_json(run_dir / "services.json", service_states)
        self._write_session_registry(registry)
        return service_states

    def _stop_services(self, *, service_states: dict[str, dict[str, Any]], stop_services: bool) -> dict[str, Any]:
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
            for seg in expr[len("$.details.") :].split("."):
                if isinstance(cur, dict) and seg in cur:
                    cur = cur[seg]
                else:
                    ok = False
                    break
            if ok:
                published[target] = cur
        return published


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
