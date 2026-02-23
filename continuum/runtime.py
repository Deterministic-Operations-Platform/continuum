"""Runtime interface and deterministic implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, Any
import uuid

from continuum.errors import ContinuumError, FailureClass
from continuum.evidence import EvidenceCollector
from continuum.preflight import gather_versions
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
            "env": dict(__import__("os").environ),
            "available_plugins": sorted(self.plugin_registry.available_plugin_names()),
        }

        def step_dir(step_index: int, step_name: str) -> str:
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
        failure: dict[str, str] | None = None

        for index, step in enumerate(scenario.steps):
            plugin = self.plugin_registry.resolve(step.type)
            step_with = render_templates(step.with_, ctx=context)
            step_started = datetime.now(timezone.utc)
            try:
                result = plugin.run(step_name=step.name, step_with=step_with, ctx=context, step_index=index)
                summary_steps.append(
                    {
                        "index": index,
                        "name": step.name,
                        "type": step.type,
                        "ok": result.ok,
                        "ms": int((datetime.now(timezone.utc) - step_started).total_seconds() * 1000),
                        "details": result.details,
                        "evidence": result.evidence_paths,
                    }
                )
                if not result.ok:
                    error_message = str(result.details.get("error") or f"Step returned unsuccessful status: {step.name}")
                    failure = {
                        "message": error_message,
                        "class": FailureClass.DATA.value,
                    }
                    break
            except ContinuumError as err:
                failure = {"message": str(err), "class": err.failure_class.value}
                summary_steps.append(
                    {
                        "index": index,
                        "name": step.name,
                        "type": step.type,
                        "ok": False,
                        "details": {"error": str(err)},
                        "evidence": [],
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
                        "type": step.type,
                        "ok": False,
                        "details": {"error": str(err)},
                        "evidence": [],
                        "ms": int((datetime.now(timezone.utc) - step_started).total_seconds() * 1000),
                    }
                )
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
            manifest_payload=manifest_payload,
        )
        summary["evidence_dir"] = str(run_dir)
        return summary
