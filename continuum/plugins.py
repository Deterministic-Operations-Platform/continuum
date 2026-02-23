"""Plugin contracts and in-memory plugin registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Any

from continuum.errors import PluginResolutionError, StepExecutionError


@dataclass(slots=True)
class StepResult:
    status: str
    output: dict[str, Any]


class Plugin(Protocol):
    name: str

    def execute(self, action: str, step_input: dict[str, Any], context: dict[str, Any]) -> StepResult:
        ...


class DefaultPlugin:
    """Deterministic no-op plugin for bootstrapping scenarios in v0.1."""

    name = "default"

    def execute(self, action: str, step_input: dict[str, Any], context: dict[str, Any]) -> StepResult:
        if not action:
            raise StepExecutionError("Action cannot be empty")
        return StepResult(status="ok", output={"action": action, "accepted": step_input})


class TransportPostmanPlugin:
    """Deterministic transport simulator for FedNow send actions."""

    name = "transport-postman"

    def execute(self, action: str, step_input: dict[str, Any], context: dict[str, Any]) -> StepResult:
        if action != "send":
            raise StepExecutionError(f"Unsupported action '{action}' for {self.name}")

        request_ref = step_input.get("requestRef")
        if not isinstance(request_ref, str) or not request_ref.strip():
            raise StepExecutionError("transport-postman requires a non-empty requestRef")

        return StepResult(
            status="ok",
            output={
                "requestRef": request_ref,
                "transport": "simulated",
                "status": "accepted",
            },
        )


class VerifyMongoPlugin:
    """Deterministic verification simulator for FedNow verify actions."""

    name = "verify-mongo"

    def execute(self, action: str, step_input: dict[str, Any], context: dict[str, Any]) -> StepResult:
        if action != "verify":
            raise StepExecutionError(f"Unsupported action '{action}' for {self.name}")

        collection = step_input.get("collection")
        if not isinstance(collection, str) or not collection.strip():
            raise StepExecutionError("verify-mongo requires a non-empty collection")

        expected = step_input.get("expect", {})
        if not isinstance(expected, dict):
            raise StepExecutionError("verify-mongo expect field must be a mapping")

        return StepResult(
            status="ok",
            output={
                "collection": collection,
                "verified": True,
                "expected": expected,
            },
        )


class PluginRegistry:
    def __init__(self, plugins: list[Plugin] | None = None):
        initial_plugins = plugins or [DefaultPlugin(), TransportPostmanPlugin(), VerifyMongoPlugin()]
        self._plugins = {plugin.name: plugin for plugin in initial_plugins}

    def resolve(self, name: str) -> Plugin:
        plugin = self._plugins.get(name)
        if plugin is None:
            raise PluginResolutionError(f"No plugin registered for '{name}'")
        return plugin
