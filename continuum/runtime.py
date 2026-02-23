"""Runtime interface and deterministic implementation."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, Any
import uuid

from continuum.errors import ContinuumError, FailureClass
from continuum.evidence import EvidenceCollector, StepRecord
from continuum.plugins import PluginRegistry
from continuum.scenario import Scenario, ScenarioStep, PreflightCheck


class Runtime(Protocol):
    def execute(self, scenario: Scenario, scenario_source: Path, run_id: str | None = None) -> dict[str, Any]:
        ...


class DeterministicRuntime:
    def __init__(self, plugin_registry: PluginRegistry, evidence_collector: EvidenceCollector):
        self.plugin_registry = plugin_registry
        self.evidence_collector = evidence_collector

    def execute(self, scenario: Scenario, scenario_source: Path, run_id: str | None = None) -> dict[str, Any]:
        resolved_run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        context: dict[str, Any] = {
            "rail": scenario.rail,
            "scenario": scenario.name,
            "available_plugins": self.plugin_registry.available_plugin_names(),
        }
        records: list[StepRecord] = []
        failure: dict[str, Any] | None = None

        try:
            self._run_preflight_checks(records, scenario, scenario_source, resolved_run_id, context)
            self._run_lifecycle(records, scenario.lifecycle_start, context)
            self._run_execution_steps(records, scenario.steps, context)
        except ContinuumError as err:
            failure = {
                "message": str(err),
                "class": err.failure_class.value,
            }
        except Exception as err:  # defensive classification
            failure = {
                "message": str(err),
                "class": FailureClass.INFRA.value,
            }

        summary = {
            "run_id": resolved_run_id,
            "scenario": {
                "name": scenario.name,
                "rail": scenario.rail,
                "steps": len(scenario.steps),
                "lifecycle_start": list(scenario.lifecycle_start),
            },
            "status": "failed" if failure else "succeeded",
            "steps": [asdict(record) for record in records],
            "failure": failure,
            "evidence_dir": str(Path("runs") / resolved_run_id),
        }
        run_dir = self.evidence_collector.write_run_bundle(
            run_id=resolved_run_id,
            scenario_source=scenario_source,
            summary=summary,
        )
        summary["evidence_dir"] = str(run_dir)
        return summary

    def _run_preflight_checks(
        self,
        records: list[StepRecord],
        scenario: Scenario,
        scenario_source: Path,
        run_id: str,
        context: dict[str, Any],
    ) -> None:
        preflight_plugin = self.plugin_registry.resolve("preflight")

        if not scenario_source.exists():
            raise ContinuumError(
                message=f"Scenario source does not exist: {scenario_source}",
                failure_class=FailureClass.INFRA,
            )

        preflight_steps = [
            ScenarioStep(
                plugin="preflight",
                action="plugins",
                input={
                    "plugins": sorted(
                        {
                            *(f"lifecycle-{service}" for service in scenario.lifecycle_start),
                            *(step.plugin for step in scenario.steps),
                        }
                    )
                },
            ),
            ScenarioStep(
                plugin="preflight",
                action="artifacts-dir",
                input={"path": str(Path("runs") / run_id)},
            ),
        ]

        for check in scenario.preflight:
            preflight_steps.append(ScenarioStep(plugin="preflight", action=check.kind, input=check.params))

        for idx, step in enumerate(preflight_steps):
            result = preflight_plugin.execute(step.action, step.input, context)
            records.append(
                StepRecord(
                    index=len(records),
                    plugin=step.plugin,
                    action=step.action,
                    status=result.status,
                    phase="preflight",
                    output=result.output,
                )
            )

    def _run_lifecycle(self, records: list[StepRecord], services: tuple[str, ...], context: dict[str, Any]) -> None:
        for service in services:
            plugin_name = f"lifecycle-{service}"
            plugin = self.plugin_registry.resolve(plugin_name)
            result = plugin.execute("start", {}, context)
            records.append(
                StepRecord(
                    index=len(records),
                    plugin=plugin_name,
                    action="start",
                    status=result.status,
                    phase="lifecycle",
                    output=result.output,
                )
            )

    def _run_execution_steps(
        self,
        records: list[StepRecord],
        steps: tuple[ScenarioStep, ...],
        context: dict[str, Any],
    ) -> None:
        for step in steps:
            plugin = self.plugin_registry.resolve(step.plugin)
            result = plugin.execute(step.action, step.input, context)
            records.append(
                StepRecord(
                    index=len(records),
                    plugin=step.plugin,
                    action=step.action,
                    status=result.status,
                    phase="execution",
                    output=result.output,
                )
            )
