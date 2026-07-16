"""Load versioned rule YAML from disk into typed ``Rule`` objects (plan Phase 1).

Rules live as code-reviewed YAML artifacts in the repository (plan Phase 1 key decision:
"rules are data, not code"). This loader is the single parse path shared by the engine and
by tests, so the golden dataset exercises the exact rules that run in production.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .schema import Rule


def load_rule(path: str | Path) -> Rule:
    data = yaml.safe_load(Path(path).read_text())
    return Rule.model_validate(data)


def load_rules(directory: str | Path) -> list[Rule]:
    """Load every ``*.yaml`` / ``*.yml`` rule under ``directory`` (sorted for determinism)."""
    root = Path(directory)
    files = sorted([*root.glob("*.yaml"), *root.glob("*.yml")])
    return [load_rule(f) for f in files]
