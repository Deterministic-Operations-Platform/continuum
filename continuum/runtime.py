"""Runtime interface and deterministic implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any, Protocol
import os
import uuid

from continuum.errors import ContinuumError, FailureClass, ScenarioValidationError
from continuum.evidence import EvidenceCollector
from continuum.plugins import PluginRegistry, render_templates
from continuum.preflight import gather_versions
from continuum.scenario import Scenario, ScenarioStep


class Runtime(Protocol):
    def execute(
        self,
        scenario: Scenario,
        scenario_source: Path,
        scenario_text: str,
        run_id: str | None = None,
        *,
        from_selector: str | None = None,
        to_selector: str | None = None,
        only_selectors: tuple[str, ...] = (),
        skip_selectors: tuple[str, ...] = (),
        include_cleanup: bool = True,
    ) -> dict[str, Any]: ...


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
        from_selector: str | None = None,
        to_selector: str | None = None,
        only_selectors: tuple[str, ...] = (),
        skip_selectors: tuple[str, ...] = (),
        include_cleanup: bool = True,
    ) -> dict[str, Any]:
        resolved_run_id = run_id or f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"
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
        manifest_payload = gather_versions()
        summary_steps: list[dict[str, Any]] = []
        cleanup_steps: list[dict[str, Any]] = []
        failure: dict[str, str] | None = None

        should_run = self._build_should_run_mask(
            scenario.steps,
            from_selector=from_selector,
            to_selector=to_selector,
            only_selectors=only_selectors,
            skip_selectors=skip_selectors,
        )

        for index, step in enumerate(scenario.steps):
            if failure is not None:
                summary_steps.append(
                    self._record_skipped_step(
                        run_dir=run_dir,
                        step=step,
                        step_index=index,
                        phase="execution",
                        reason="Skipped after earlier failure",
                    )
                )
                continue

            if not should_run[index]:
                summary_steps.append(
                    self._record_skipped_step(
                        run_dir=run_dir,
                        step=step,
                        step_index=index,
                        phase="execution",
                        reason="Excluded by selector",
                    )
                )
                continue

            step_started = datetime.now(timezone.utc)
            execution = self._run_step_with_retries(step=step, context=context, step_index=index, started=step_started)
            summary_steps.append(execution)
            if execution.get("publish"):
                context["vars"].update(execution["publish"])
            if execution.get("exports"):
                context["vars"].update(execution["exports"])
            if not execution["ok"] and failure is None:
                failure = execution.get("failure") or {
                    "message": f"Step returned unsuccessful status: {step.name}",
                    "class": FailureClass.DATA.value,
                }

        cleanup_offset = len(scenario.steps)
        if include_cleanup:
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
                if execution.get("exports"):
                    context["vars"].update(execution["exports"])
                if not execution["ok"] and failure is None:
                    failure = execution.get("failure") or {
                        "message": f"Cleanup step failed: {step.name}",
                        "class": FailureClass.DATA.value,
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
            context_payload={"run_id": resolved_run_id, "run_dir": str(run_dir), "vars": context["vars"]},
            summary=summary,
            manifest_payload=manifest_payload,
        )
        summary["evidence_dir"] = str(run_dir)
        return summary

    def _build_should_run_mask(
        self,
        steps: tuple[ScenarioStep, ...],
        *,
        from_selector: str | None,
        to_selector: str | None,
        only_selectors: tuple[str, ...],
        skip_selectors: tuple[str, ...],
    ) -> list[bool]:
        selected = [True] * len(steps)
        if only_selectors:
            selected = [any(self._selector_matches(s, step, i) for s in only_selectors) for i, step in enumerate(steps)]

        if from_selector is not None:
            from_index = self._first_matching_index(from_selector, steps)
            selected = [ok and i >= from_index for i, ok in enumerate(selected)]

        if to_selector is not None:
            to_index = self._first_matching_index(to_selector, steps)
            selected = [ok and i <= to_index for i, ok in enumerate(selected)]

        for i, step in enumerate(steps):
            if any(self._selector_matches(s, step, i) for s in skip_selectors):
                selected[i] = False

        return selected

    def _first_matching_index(self, selector: str, steps: tuple[ScenarioStep, ...]) -> int:
        for i, step in enumerate(steps):
            if self._selector_matches(selector, step, i):
                return i
        raise ScenarioValidationError(f"Selector did not match any step: {selector}")

    def _selector_matches(self, selector: str, step: ScenarioStep, zero_index: int) -> bool:
        candidate = selector.strip()
        if not candidate:
            return False
        if candidate in {step.key, step.type}:
            return True
        return candidate.isdigit() and int(candidate) == zero_index + 1

    def _record_skipped_step(
        self,
        *,
        run_dir: Path,
        step: ScenarioStep,
        step_index: int,
        phase: str,
        reason: str,
    ) -> dict[str, Any]:
        evidence_dir = self.evidence_collector.step_dir(run_dir, step_index, step.name)
        skipped_path = self.evidence_collector.write_json(
            evidence_dir / "skipped.json",
            {
                "status": "skipped",
                "skipReason": reason,
                "step": {"name": step.name, "key": step.key, "type": step.type, "index": step_index},
            },
        )
        return {
            "index": step_index,
            "name": step.name,
            "key": step.key,
            "type": step.type,
            "phase": phase,
            "status": "skipped",
            "ok": False,
            "skipReason": reason,
            "ms": 0,
            "attempts": [],
            "evidence": [skipped_path],
            "publish": {},
            "exports": {},
        }

    def _run_step_with_retries(
        self,
        *,
        step: ScenarioStep,
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
                exports = result.exports or {}
                if exports:
                    steps_ns = context["vars"].setdefault("steps", {})
                    if not isinstance(steps_ns, dict):
                        steps_ns = {}
                        context["vars"]["steps"] = steps_ns
                    steps_ns[step.key] = exports

                attempts.append({"attempt": attempt, "ok": result.ok, "details": result.details, "evidence": result.evidence_paths})
                step_summary = {
                    "index": step_index,
                    "name": step.name,
                    "key": step.key,
                    "type": step.type,
                    "phase": phase,
                    "status": "succeeded" if result.ok else "failed",
                    "ok": result.ok,
                    "ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
                    "details": result.details,
                    "evidence": result.evidence_paths,
                    "attempts": attempts,
                    "publish": published,
                    "exports": exports,
                }
                if result.ok:
                    return step_summary

                last_error = {"message": f"Step returned unsuccessful status: {step.name}", "class": FailureClass.DATA.value}
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
            "key": step.key,
            "type": step.type,
            "phase": phase,
            "status": "failed",
            "ok": False,
            "ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
            "attempts": attempts,
            "failure": last_error,
            "error": (last_error or {}).get("message", "step failed"),
            "publish": {},
            "exports": {},
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
