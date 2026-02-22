"""Typed error model for continuum scenario execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FailureClass(str, Enum):
    """Top-level execution failure classes for reporting and triage."""

    INFRA = "infra_failure"
    LOGIC = "logic_failure"
    DATA = "data_failure"


@dataclass(slots=True)
class ContinuumError(Exception):
    """Base typed error used by the public execution surface."""

    message: str
    failure_class: FailureClass

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.message


class ScenarioValidationError(ContinuumError):
    def __init__(self, message: str):
        super().__init__(message=message, failure_class=FailureClass.LOGIC)


class PluginResolutionError(ContinuumError):
    def __init__(self, message: str):
        super().__init__(message=message, failure_class=FailureClass.INFRA)


class TransportError(ContinuumError):
    def __init__(self, message: str):
        super().__init__(message=message, failure_class=FailureClass.INFRA)


class VerificationError(ContinuumError):
    def __init__(self, message: str):
        super().__init__(message=message, failure_class=FailureClass.LOGIC)


class LifecycleError(ContinuumError):
    def __init__(self, message: str):
        super().__init__(message=message, failure_class=FailureClass.INFRA)


class RuntimeTimeoutError(ContinuumError):
    def __init__(self, message: str):
        super().__init__(message=message, failure_class=FailureClass.INFRA)
