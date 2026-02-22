"""Typed errors for deterministic Continuum orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FailureClass(str, Enum):
    INFRA = "infra_failure"
    LOGIC = "logic_failure"
    DATA = "data_failure"


@dataclass(slots=True)
class ContinuumError(Exception):
    message: str
    failure_class: FailureClass

    def __str__(self) -> str:
        return self.message


class ScenarioValidationError(ContinuumError):
    def __init__(self, message: str):
        super().__init__(message=message, failure_class=FailureClass.LOGIC)


class PluginResolutionError(ContinuumError):
    def __init__(self, message: str):
        super().__init__(message=message, failure_class=FailureClass.INFRA)


class StepExecutionError(ContinuumError):
    def __init__(self, message: str):
        super().__init__(message=message, failure_class=FailureClass.DATA)
