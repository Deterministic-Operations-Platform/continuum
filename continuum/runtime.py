"""Runtime interface and deterministic implementation."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import math
import os
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
        failure: dict[str, str] | None = None

        for index, step in enumerate(scenario.steps):
            plugin = self.plugin_registry.resolve(step.type)
            step_with = render_templates(step.with_, ctx=context)
            step_started = datetime.now(timezone.utc)
            step_key = f"{index}:{step.name}:{step.type}"

            retry_cfg = step.retry or {
                "on": ["exception"],
                "maxAttempts": 1,
                "backoff": "fixed",
                "baseDelayMs": 0,
                "maxDelayMs": 0,
                "jitter": 0,
            }
            max_attempts = max(1, int(retry_cfg.get("maxAttempts", 1)))
            retry_on = set(retry_cfg.get("on", ["exception"]))

            attempt_summaries: list[dict[str, Any]] = []
            final_result = None
            step_ok = False
            final_error: str | None = None
            final_error_class = FailureClass.DATA.value

            for attempt in range(1, max_attempts + 1):
                if attempt > 1:
                    delay_ms = compute_delay_ms(resolved_run_id, step_key, attempt, retry_cfg)
                    if delay_ms > 0:
                        time.sleep(delay_ms / 1000.0)

                attempt_started = datetime.now(timezone.utc)
                attempt_dir = self.evidence_collector.step_dir(run_dir, index, step.name) / f"attempt-{attempt:02d}"
                attempt_dir.mkdir(parents=True, exist_ok=True)
                context["step_evidence_dir"] = str(attempt_dir)
                context["attempt"] = attempt
                context["attemptMax"] = max_attempts

                try:
                    result = plugin.run(step_name=step.name, step_with=step_with, ctx=context, step_index=index)
                    final_result = result
                    step_ok = bool(result.ok)
                    attempt_summaries.append(
                        {
                            "attempt": attempt,
                            "ok": step_ok,
                            "ms": int((datetime.now(timezone.utc) - attempt_started).total_seconds() * 1000),
                        }
                    )
                    if step_ok:
                        break
                    if "failure" not in retry_on:
                        break
                except ContinuumError as err:
                    final_error = str(err)
                    final_error_class = err.failure_class.value
                    attempt_summaries.append(
                        {
                            "attempt": attempt,
                            "ok": False,
                            "exception": str(err),
                            "ms": int((datetime.now(timezone.utc) - attempt_started).total_seconds() * 1000),
                        }
                    )
                    if "exception" not in retry_on:
                        break
                except Exception as err:  # noqa: BLE001
                    final_error = str(err)
                    final_error_class = FailureClass.INFRA.value
                    attempt_summaries.append(
                        {
                            "attempt": attempt,
                            "ok": False,
                            "exception": str(err),
                            "ms": int((datetime.now(timezone.utc) - attempt_started).total_seconds() * 1000),
                        }
                    )
                    if "exception" not in retry_on:
                        break

            context["step_evidence_dir"] = None

            step_summary: dict[str, Any] = {
                "index": index,
                "name": step.name,
                "type": step.type,
                "ok": step_ok,
                "ms": int((datetime.now(timezone.utc) - step_started).total_seconds() * 1000),
                "attempts": attempt_summaries,
            }

            if final_result is not None:
                step_summary["details"] = final_result.details
                step_summary["evidence"] = final_result.evidence_paths
            if final_error:
                step_summary["error"] = final_error

            summary_steps.append(step_summary)
            if not step_ok:
                failure = {
                    "message": final_error or f"Step returned unsuccessful status: {step.name}",
                    "class": final_error_class,
                }
                break

        summary = {
            "run_id": resolved_run_id,
            "scenario": {"name": scenario.name, "rail": scenario.rail, "steps": len(scenario.steps)},
            "started_at": started_at.isoformat(),
            "ended_at": datetime.now(timezone.utc).isoformat(),
            "status": "failed" if failure else "succeeded",
            "steps": summary_steps,
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
