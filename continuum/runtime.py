"""Runtime interface and deterministic implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Any, Protocol
import json
import os
import uuid

from continuum.errors import ContinuumError, FailureClass
from continuum.evidence import EvidenceCollector
from continuum.preflight import gather_versions
from continuum.plugins import PluginRegistry, render_templates
from continuum.scenario import Scenario, ScenarioStep


class Runtime(Protocol):
    def execute(
        self,
        scenario: Scenario,
        scenario_source: Path,
        scenario_text: str,
        run_id: str | None = None,
        *,
        resume_id: str | None = None,
        rerun_selectors: list[str] | None = None,
        from_failure: bool = False,
        no_cleanup: bool = False,
        cli_vars: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...


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
        resume_id: str | None = None,
        rerun_selectors: list[str] | None = None,
        from_failure: bool = False,
        no_cleanup: bool = False,
        cli_vars: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resolved_run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        run_dir = Path("runs") / resolved_run_id

        previous_summary, previous_context = self._load_resume_bundle(resume_id)
        prev_status_by_key = self._build_previous_status_map(previous_summary)
        prev_vars = (previous_context or {}).get("vars", {})

        merged_vars = _deep_merge(dict(prev_vars if isinstance(prev_vars, dict) else {}), dict(scenario.vars))
        merged_vars = _deep_merge(merged_vars, dict(cli_vars or {}))

        context: dict[str, Any] = {
            "run_id": resolved_run_id,
            "run_dir": str(run_dir),
            "repo_root": str(Path.cwd()),
            "vars": merged_vars,
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

        rerun_selectors = rerun_selectors or []
        skip_candidates, first_failure_key = self._compute_resume_mask(scenario.steps, prev_status_by_key, rerun_selectors)
        from_key = first_failure_key if from_failure else None
        has_seen_from = from_key is None

        for index, step in enumerate(scenario.steps):
            current_key = _effective_step_key(step, index)
            should_run = True
            if not has_seen_from:
                has_seen_from = current_key == from_key
                should_run = has_seen_from

            if failure and not step.always:
                should_run = False

            if should_run and current_key in skip_candidates:
                skip_entry = {
                    "index": index,
                    "name": step.name,
                    "key": current_key,
                    "type": step.type,
                    "phase": "execution",
                    "ok": True,
                    "status": "skipped",
                    "skipReason": "resume:succeeded",
                    "ms": 0,
                    "attempts": [],
                    "publish": {},
                    "exports": context["vars"].get("steps", {}).get(current_key, {}),
                }
                summary_steps.append(skip_entry)
                self._write_skipped_evidence(run_dir, index, step.name, skip_entry)
                continue

            if not should_run:
                summary_steps.append(
                    {
                        "index": index,
                        "name": step.name,
                        "key": current_key,
                        "type": step.type,
                        "phase": "execution",
                        "ok": True,
                        "status": "skipped",
                        "skipReason": "control-flow",
                        "ms": 0,
                        "attempts": [],
                        "publish": {},
                        "exports": {},
                    }
                )
                continue

            step_started = datetime.now(timezone.utc)
            execution = self._run_step_with_retries(step=step, context=context, step_index=index, started=step_started)
            summary_steps.append(execution)
            if execution.get("publish"):
                context["vars"].update(execution["publish"])
            if execution.get("exports"):
                self._merge_step_exports(context, current_key, execution["exports"])
            if not execution["ok"] and failure is None:
                failure = execution.get("failure") or {
                    "message": f"Step returned unsuccessful status: {step.name}",
                    "class": FailureClass.DATA.value,
                }

        if not no_cleanup:
            cleanup_offset = len(scenario.steps)
            for cleanup_index, step in enumerate(scenario.cleanup_steps):
                current_key = _effective_step_key(step, cleanup_offset + cleanup_index)
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
                    self._merge_step_exports(context, current_key, execution["exports"])
                if not execution["ok"] and failure is None:
                    failure = execution.get("failure") or {
                        "message": f"Cleanup step failed: {step.name}",
                        "class": FailureClass.DATA.value,
                    }

        summary = {
            "run_id": resolved_run_id,
            "resumedFrom": resume_id,
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
                "resumed_from": resume_id,
            },
            summary=summary,
            manifest_payload=manifest_payload,
        )
        if resume_id:
            skipped_steps = [s["key"] for s in summary_steps if s.get("skipReason") == "resume:succeeded"]
            self.evidence_collector.write_json(
                run_dir / "resume.json",
                {"resumedFrom": resume_id, "importedVars": True, "skippedSteps": skipped_steps},
            )
        summary["evidence_dir"] = str(run_dir)
        return summary

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
                attempts.append({"attempt": attempt, "ok": result.ok, "details": result.details, "evidence": result.evidence_paths})
                step_summary = {
                    "index": step_index,
                    "name": step.name,
                    "key": _effective_step_key(step, step_index),
                    "type": step.type,
                    "phase": phase,
                    "ok": result.ok,
                    "status": "succeeded" if result.ok else "failed",
                    "ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
                    "details": result.details,
                    "evidence": result.evidence_paths,
                    "attempts": attempts,
                    "publish": published,
                    "exports": result.exports or {},
                }
                if result.ok:
                    return step_summary
                last_error = {
                    "message": f"Step returned unsuccessful status: {step.name}",
                    "class": FailureClass.DATA.value,
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
            "key": _effective_step_key(step, step_index),
            "type": step.type,
            "phase": phase,
            "ok": False,
            "status": "failed",
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

    def _compute_resume_mask(
        self,
        steps: tuple[ScenarioStep, ...],
        prev_status_by_key: dict[str, str],
        rerun_selectors: list[str],
    ) -> tuple[set[str], str | None]:
        skip: set[str] = set()
        first_failed: str | None = None
        for index, step in enumerate(steps):
            key = _effective_step_key(step, index)
            prev = prev_status_by_key.get(key)
            if prev == "succeeded":
                skip.add(key)
            if first_failed is None and prev == "failed":
                first_failed = key

        if rerun_selectors:
            for index, step in enumerate(steps):
                key = _effective_step_key(step, index)
                if _matches_selector(step, key, rerun_selectors):
                    skip.discard(key)
        return skip, first_failed

    def _build_previous_status_map(self, previous_summary: dict[str, Any] | None) -> dict[str, str]:
        status_map: dict[str, str] = {}
        if not previous_summary:
            return status_map
        for item in previous_summary.get("steps", []):
            if not isinstance(item, dict):
                continue
            key = item.get("key")
            if not isinstance(key, str):
                continue
            if "status" in item:
                status = str(item["status"])
            elif item.get("ok") is True:
                status = "succeeded"
            else:
                status = "failed"
            status_map[key] = status
        return status_map

    def _load_resume_bundle(self, resume_id: str | None) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        if not resume_id:
            return None, None
        run_dir = Path("runs") / resume_id
        summary_path = run_dir / "summary.json"
        context_path = run_dir / "context.json"
        if not summary_path.exists() or not context_path.exists():
            raise ContinuumError(f"Resume run '{resume_id}' is missing summary/context bundle", FailureClass.LOGIC)
        return (
            json.loads(summary_path.read_text(encoding="utf-8")),
            json.loads(context_path.read_text(encoding="utf-8")),
        )

    def _merge_step_exports(self, context: dict[str, Any], key: str, exports: dict[str, Any]) -> None:
        if not exports:
            return
        context["vars"].update(exports)
        steps_ns = context["vars"].setdefault("steps", {})
        if not isinstance(steps_ns, dict):
            steps_ns = {}
            context["vars"]["steps"] = steps_ns
        steps_ns[key] = exports

    def _write_skipped_evidence(self, run_dir: Path, index: int, step_name: str, payload: dict[str, Any]) -> None:
        step_path = self.evidence_collector.step_dir(run_dir, index, step_name)
        self.evidence_collector.write_json(step_path / "skipped.json", payload)


def _matches_selector(step: ScenarioStep, step_key: str, selectors: list[str]) -> bool:
    normalized_name = step.name.lower().replace(" ", "_")
    for selector in selectors:
        probe = selector.strip().lower()
        if probe in {step_key.lower(), step.type.lower(), normalized_name}:
            return True
    return False


def _effective_step_key(step: ScenarioStep, index: int) -> str:
    if step.key:
        return step.key
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in step.name).strip("_")
    return f"{index + 1:02d}_{slug or 'step'}"


def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in incoming.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out
