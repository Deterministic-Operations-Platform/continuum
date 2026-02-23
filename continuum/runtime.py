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
from continuum.scenario import Scenario


class Runtime(Protocol):
    def execute(self, scenario: Scenario, scenario_source: Path, run_id: str | None = None) -> dict[str, Any]:
        ...


class DeterministicRuntime:
    def __init__(self, plugin_registry: PluginRegistry, evidence_collector: EvidenceCollector):
        self.plugin_registry = plugin_registry
        self.evidence_collector = evidence_collector

    def execute(self, scenario: Scenario, scenario_source: Path, run_id: str | None = None) -> dict[str, Any]:
        resolved_run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        context: dict[str, Any] = {"rail": scenario.rail, "scenario": scenario.name}
        records: list[StepRecord] = []
        failure: dict[str, Any] | None = None

        try:
            for idx, step in enumerate(scenario.steps):
                plugin = self.plugin_registry.resolve(step.plugin)
                result = plugin.execute(step.action, step.input, context)
                records.append(
                    StepRecord(
                        index=idx,
                        plugin=step.plugin,
                        action=step.action,
                        status=result.status,
                        output=result.output,
                    )
                )
        except ContinuumError as err:
            failure = {
                "message": str(err),
                "class": err.failure_class.value,
            }
            records.append(
                StepRecord(
                    index=len(records),
                    plugin=step.plugin,
                    action=step.action,
                    status="failed",
                    error=str(err),
                )
            )
        except Exception as err:  # defensive classification
            failure = {
                "message": str(err),
                "class": FailureClass.INFRA.value,
            }
            records.append(
                StepRecord(
                    index=len(records),
                    plugin=step.plugin,
                    action=step.action,
                    status="failed",
                    error=str(err),
                )
            )

        summary = {
            "run_id": resolved_run_id,
            "scenario": {"name": scenario.name, "rail": scenario.rail, "steps": len(scenario.steps)},
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
