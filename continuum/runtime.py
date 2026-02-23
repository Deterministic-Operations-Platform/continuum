"""Runtime interface and deterministic implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from time import sleep
from pathlib import Path
import time
from typing import Protocol, Any
import uuid

from continuum.errors import ContinuumError, FailureClass
from continuum.evidence import EvidenceCollector
from continuum.plugins import PluginRegistry, render_templates
from continuum.scenario import Scenario


class Runtime(Protocol):
    def execute(
        self,
        scenario: Scenario,
        scenario_source: Path,
        scenario_text: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        ...


def _deterministic_unit(run_id: str, step_key: str, attempt: int) -> float:
    payload = f"{run_id}:{step_key}:{attempt}".encode("utf-8")
    digest = hashlib.sha256(payload).digest()
    int_value = int.from_bytes(digest[:8], "big")
    return int_value / float(2**64)


def compute_delay_ms(run_id: str, step_key: str, attempt: int, retry_cfg: dict[str, Any]) -> int:
    base_delay_ms = int(retry_cfg["baseDelayMs"])
    max_delay_ms = int(retry_cfg["maxDelayMs"])
    backoff_mode = str(retry_cfg["backoff"])
    jitter = float(retry_cfg["jitter"])

    # attempt is 1-based. delay applies before attempt 2,3,...
    backoff_index = max(0, attempt - 2)

    if backoff_mode == "exponential":
        delay_ms = base_delay_ms * (2**backoff_index)
    elif backoff_mode == "linear":
        delay_ms = base_delay_ms * (backoff_index + 1)
    else:
        delay_ms = base_delay_ms

    delay_ms = min(delay_ms, max_delay_ms)

    if jitter > 0:
        unit = _deterministic_unit(run_id, step_key, attempt)
        jitter_factor = (unit * 2.0 - 1.0) * jitter
        delay_ms = int(max(0, math.floor(delay_ms * (1.0 + jitter_factor))))

    return delay_ms


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
    ) -> dict[str, Any]:
        resolved_run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        run_dir = Path("runs") / resolved_run_id

        context: dict[str, Any] = {
            "run_id": resolved_run_id,
            "run_dir": str(run_dir),
            "repo_root": str(Path.cwd()),
            "vars": dict(scenario.vars),
            "env": dict(os.environ),
            "available_plugins": sorted(self.plugin_registry.available_plugin_names()),
            "step_evidence_dir": None,
            "attempt": 1,
            "attemptMax": 1,
        }

        def step_dir(step_index: int, step_name: str) -> str:
            configured_path = context.get("step_evidence_dir")
            if isinstance(configured_path, str) and configured_path:
                return configured_path
            return str(self.evidence_collector.step_dir(run_dir, step_index, step_name))

        context["step_dir"] = step_dir
        context["write"] = lambda step_path, filename, content: self.evidence_collector.write_text(
            Path(step_path) / filename,
            content if isinstance(content, str) else content.decode("utf-8", errors="replace"),
        )
        context["write_json"] = (
            lambda step_path, filename, payload: self.evidence_collector.write_json(Path(step_path) / filename, payload)
        )

        started_at = datetime.now(timezone.utc)
        summary_steps: list[dict[str, Any]] = []
        cleanup_steps: list[dict[str, Any]] = []
        failure: dict[str, str] | None = None
        failed_at: int | None = None

        for index, step in enumerate(scenario.steps):
            step_started = datetime.now(timezone.utc)
            try:
                result = plugin.run(step_name=step.name, step_with=step_with, ctx=context, step_index=index)

                exports = result.exports or {}
                if exports:
                    context["vars"].update(exports)
                    steps_ns = context["vars"].setdefault("steps", {})
                    if not isinstance(steps_ns, dict):
                        steps_ns = {}
                        context["vars"]["steps"] = steps_ns
                    steps_ns[step.key] = exports

                summary_steps.append(
                    {
                        "index": index,
                        "name": step.name,
                        "key": step.key,
                        "type": step.type,
                        "ok": result.ok,
                        "ms": int((datetime.now(timezone.utc) - step_started).total_seconds() * 1000),
                        "details": result.details,
                        "evidence": result.evidence_paths,
                        "exports": exports,
                    }
                )
                if not result.ok:
                    failure = {
                        "message": f"Step returned unsuccessful status: {step.name}",
                        "class": FailureClass.EXECUTION.value,
                    }
                    break
            except ContinuumError as err:
                failure = {"message": str(err), "class": err.failure_class.value}
                summary_steps.append(
                    {
                        "index": index,
                        "name": step.name,
                        "key": step.key,
                        "type": step.type,
                        "ok": False,
                        "error": str(err),
                        "ms": int((datetime.now(timezone.utc) - step_started).total_seconds() * 1000),
                    }
                )
                break
            except Exception as err:  # noqa: BLE001
                failure = {"message": str(err), "class": FailureClass.INFRA.value}
                summary_steps.append(
                    {
                        "index": index,
                        "name": step.name,
                        "key": step.key,
                        "type": step.type,
                        "ok": False,
                        "error": str(err),
                        "ms": int((datetime.now(timezone.utc) - step_started).total_seconds() * 1000),
                    }
                )
            execution = self._run_step_with_retries(step=step, context=context, step_index=index, started=step_started)
            summary_steps.append(execution)
            if execution.get("publish"):
                context["vars"].update(execution["publish"])
            if not execution["ok"]:
                failure = execution.get("failure") or {
                    "message": f"Step returned unsuccessful status: {step.name}",
                    "class": FailureClass.EXECUTION.value,
                }
                break

        cleanup_offset = len(scenario.steps)
        for cleanup_index, step in enumerate(scenario.cleanup_steps):
            step_started = datetime.now(timezone.utc)
            execution = self._run_step_with_retries(
                step=step,
                context=context,
                step_index=cleanup_offset + cleanup_index,
                started=step_started,
                phase="cleanup",
            )
            cleanup_steps.append(execution)
            if execution.get("publish"):
                context["vars"].update(execution["publish"])
            if not execution["ok"] and failure is None:
                failure = execution.get("failure") or {
                    "message": f"Cleanup step failed: {step.name}",
                    "class": FailureClass.EXECUTION.value,
                }

        summary = {
            "run_id": resolved_run_id,
            "scenario": {"name": scenario.name, "rail": scenario.rail, "steps": len(scenario.steps)},
            "started_at": started_at.isoformat(),
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed" if failure else "succeeded",
            "steps": summary_steps,
            "cleanup_steps": cleanup_steps,
            "failure": failure,
            "evidence_dir": str(run_dir),
        }

        run_dir = self.evidence_collector.write_run_bundle(
            run_id=resolved_run_id,
            scenario_source=scenario_source,
            scenario_text=scenario_text,
            context_payload={
                "run_id": resolved_run_id,
                "run_dir": str(run_dir),
                "vars": context["vars"],
            },
            summary=summary,
        )
        summary["evidence_dir"] = str(run_dir)
        return summary

    def _run_step_with_retries(
        self,
        *,
        step: Any,
        context: dict[str, Any],
        step_index: int,
        started: datetime,
        phase: str = "execution",
    ) -> dict[str, Any]:
        plugin = self.plugin_registry.resolve(step.type)
        rendered = render_templates(step.with_, ctx=context)
        retries = max(0, int(rendered.get("retries", 0)))
        backoff_ms = max(0, int(rendered.get("backoffMs", 0)))
        step_with = {k: v for k, v in rendered.items() if k not in {"retries", "backoffMs"}}

        attempts: list[dict[str, Any]] = []
        last_error: dict[str, str] | None = None
        for attempt in range(1, retries + 2):
            try:
                result = plugin.run(step_name=step.name, step_with=step_with, ctx=context, step_index=step_index)
                published = self._resolve_publish(step.publish, result.details)
                attempt_data = {
                    "attempt": attempt,
                    "ok": result.ok,
                    "details": result.details,
                    "evidence": result.evidence_paths,
                }
                attempts.append(attempt_data)

                step_summary = {
                    "index": step_index,
                    "name": step.name,
                    "type": step.type,
                    "phase": phase,
                    "ok": result.ok,
                    "ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
                    "details": result.details,
                    "evidence": result.evidence_paths,
                    "attempts": attempts,
                    "publish": published,
                }
                if result.ok:
                    return step_summary

                last_error = {
                    "message": f"Step returned unsuccessful status: {step.name}",
                    "class": FailureClass.EXECUTION.value,
                }
            except ContinuumError as err:
                last_error = {"message": str(err), "class": err.failure_class.value}
                attempts.append({"attempt": attempt, "ok": False, "error": str(err)})
            except Exception as err:  # noqa: BLE001
                last_error = {"message": str(err), "class": FailureClass.INFRA.value}
                attempts.append({"attempt": attempt, "ok": False, "error": str(err)})

            if attempt <= retries and backoff_ms > 0:
                sleep(backoff_ms / 1000)

        return {
            "index": step_index,
            "name": step.name,
            "type": step.type,
            "phase": phase,
            "ok": False,
            "ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
            "attempts": attempts,
            "failure": last_error,
            "error": (last_error or {}).get("message", "step failed"),
            "publish": {},
        }

    def _resolve_publish(self, publish_map: dict[str, str], details: dict[str, Any]) -> dict[str, Any]:
        if not publish_map:
            return {}
        published: dict[str, Any] = {}
        base = {"details": details}
        for target_key, expression in publish_map.items():
            if not expression.startswith("$."):
                continue
            cursor: Any = base
            found = True
            for segment in expression[2:].split("."):
                if not isinstance(cursor, dict) or segment not in cursor:
                    found = False
                    break
                cursor = cursor[segment]
            if found:
                published[target_key] = cursor
        return published
