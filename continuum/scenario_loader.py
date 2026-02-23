"""Compatibility wrapper around the canonical scenario loader.

Use :func:`continuum.scenario.load_scenario` directly for new code.
"""

from __future__ import annotations

from pathlib import Path

from continuum.scenario import Scenario, load_scenario


class ScenarioLoader:
    """Load scenarios using the canonical runtime schema."""

    def load(self, path: str | Path) -> Scenario:
        return load_scenario(path)
