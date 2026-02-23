"""Plugin contracts and in-memory plugin registry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Any
import os

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


class LifecycleAppLauncherPlugin:
    """Deterministic lifecycle simulator for AppLauncher startup."""

    name = "lifecycle-applauncher"

    def execute(self, action: str, step_input: dict[str, Any], context: dict[str, Any]) -> StepResult:
        if action != "start":
            raise StepExecutionError(f"Unsupported action '{action}' for {self.name}")

        ready_env = str(os.getenv("CONTINUUM_APPLAUNCHER_READY", "true")).strip().lower()
        if ready_env not in {"true", "1", "yes"}:
            raise StepExecutionError("AppLauncher readiness check failed (set CONTINUUM_APPLAUNCHER_READY=true)")

        return StepResult(
            status="ok",
            output={
                "service": "applauncher",
                "started": True,
            },
        )


class PreflightPlugin:
    """Deterministic preflight checks for environment readiness."""

    name = "preflight"

    def execute(self, action: str, step_input: dict[str, Any], context: dict[str, Any]) -> StepResult:
        if action == "plugins":
            required_plugins = step_input.get("plugins", [])
            if not isinstance(required_plugins, list):
                raise StepExecutionError("preflight.plugins expects plugins as an array")
            missing = [name for name in required_plugins if name not in context.get("available_plugins", set())]
            if missing:
                raise StepExecutionError(f"Missing required plugins: {', '.join(sorted(missing))}")
            return StepResult(status="ok", output={"check": "plugins", "missing": []})

        if action == "artifacts-dir":
            path_value = step_input.get("path")
            if not isinstance(path_value, str) or not path_value.strip():
                raise StepExecutionError("preflight.artifacts-dir requires a non-empty path")
            path = Path(path_value)
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".continuum.write.test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return StepResult(status="ok", output={"check": "artifacts-dir", "path": str(path)})

        if action == "env":
            name = step_input.get("name")
            if not isinstance(name, str) or not name.strip():
                raise StepExecutionError("preflight.env requires a non-empty name")
            value = os.getenv(name)
            if value is None or not str(value).strip():
                raise StepExecutionError(f"Required env var is missing: {name}")
            return StepResult(status="ok", output={"check": "env", "name": name})

        raise StepExecutionError(f"Unsupported action '{action}' for {self.name}")


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
        initial_plugins = plugins or [
            DefaultPlugin(),
            PreflightPlugin(),
            LifecycleAppLauncherPlugin(),
            TransportPostmanPlugin(),
            VerifyMongoPlugin(),
        ]
        self._plugins = {plugin.name: plugin for plugin in initial_plugins}

    def resolve(self, name: str) -> Plugin:
        plugin = self._plugins.get(name)
        if plugin is None:
            raise PluginResolutionError(f"No plugin registered for '{name}'")
        return plugin

    def available_plugin_names(self) -> set[str]:
        return set(self._plugins.keys())
