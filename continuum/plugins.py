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


class PluginRegistry:
    def __init__(self, plugins: list[Plugin] | None = None):
        initial_plugins = plugins or [DefaultPlugin()]
        self._plugins = {plugin.name: plugin for plugin in initial_plugins}

    def resolve(self, name: str) -> Plugin:
        plugin = self._plugins.get(name)
        if plugin is None:
            raise PluginResolutionError(f"No plugin registered for '{name}'")
        return plugin
