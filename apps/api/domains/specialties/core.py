"""Pure specialty-pack mechanics (plan Phase 10 — Specialty Protocol Breadth, closes G6).

Django-free and deterministic so the safety-critical breadth logic is exhaustively
unit-testable without a database. Four capabilities, all operating on the same immutable
``Rule`` + ``Scenario`` primitives the production engine (``clinara_protocol_engine``) and the
Rule Studio (``domains.protocols.core``) use:

  * **Pack loading** — parse a parameterized specialty pack YAML into a typed ``SpecialtyPack``.
  * **Parameter binding** — resolve ``{param: <name>}`` placeholders (pack defaults overlaid
    with per-tenant overrides) into a concrete ``Rule``. Binding happens BEFORE the rule is
    validated into the frozen engine schema, so the engine is never touched and every
    evaluation stays a pure, replayable function of literal values. **This is how per-tenant
    threshold customization works with no code change** (plan Phase 10 exit gate).
  * **Pack validation** — a pack cannot be considered live unless every rule parses, no rule
    down-classifies a critical value (``assert_cannot_weaken_safety``), and every required
    test case passes (``run_test_cases``) — the same activation gate the Rule Studio enforces.
  * **Coverage** — assert every registered ambulatory specialty is served by ≥1 active rule.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from clinara_protocol_engine import Rule
from clinara_terminology import CanonicalMarker

from domains.protocols.core import (
    SafetyViolation,
    Scenario,
    assert_cannot_weaken_safety,
    run_test_cases,
)

# A pack file reads only the keys below; anything else (e.g. YAML-anchor hosts like ``_scope``,
# which let packs share a scope list without repetition) is ignored by ``load_pack``.


class PackError(ValueError):
    """A specialty pack is structurally invalid (bad YAML shape, unknown marker, …)."""


class ParameterError(PackError):
    """A ``{param: <name>}`` placeholder has no bound value."""


@dataclass(frozen=True)
class SpecialtyPack:
    specialty: str
    display_name: str
    version: int
    evidence: tuple[str, ...]
    parameters: dict[str, Any]          # pack default threshold values
    raw_rules: tuple[dict, ...]         # unbound rule bodies ({param: ...} placeholders intact)
    test_cases: tuple[dict, ...]
    source: str = ""

    @property
    def markers(self) -> list[str]:
        return sorted({str(r.get("marker")) for r in self.raw_rules})

    @property
    def served_specialties(self) -> set[str]:
        """Every specialty any rule in this pack is scoped to (empty scope = all specialties)."""
        served: set[str] = set()
        for r in self.raw_rules:
            scope = (r.get("scope") or {}).get("specialties") or []
            served.update(scope)
        return served


# --------------------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------------------

def load_pack(path: str | Path) -> SpecialtyPack:
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict):
        raise PackError(f"pack {path} is not a mapping")
    for required in ("specialty", "rules"):
        if required not in data:
            raise PackError(f"pack {path} missing required key {required!r}")
    unknown_markers = [
        m for m in {r.get("marker") for r in data["rules"]}
        if m not in {cm.value for cm in CanonicalMarker}
    ]
    if unknown_markers:
        raise PackError(f"pack {path} references unknown marker(s): {sorted(unknown_markers)}")
    return SpecialtyPack(
        specialty=str(data["specialty"]),
        display_name=str(data.get("display_name", data["specialty"])),
        version=int(data.get("version", 1)),
        evidence=tuple(data.get("evidence", []) or []),
        parameters=dict(data.get("parameters", {}) or {}),
        raw_rules=tuple(data["rules"]),
        test_cases=tuple(data.get("test_cases", []) or []),
        source=str(path),
    )


def load_packs(directory: str | Path) -> list[SpecialtyPack]:
    root = Path(directory)
    files = sorted([*root.glob("*.yaml"), *root.glob("*.yml")])
    return [load_pack(f) for f in files]


# --------------------------------------------------------------------------------------
# Parameter binding — the "no code change" threshold-customization seam
# --------------------------------------------------------------------------------------

def resolve_parameters(pack: SpecialtyPack, overrides: dict[str, Any] | None = None
                       ) -> dict[str, Any]:
    """Effective parameters = pack defaults overlaid with per-practice overrides (deterministic)."""
    resolved = dict(pack.parameters)
    for name, value in (overrides or {}).items():
        if name not in pack.parameters:
            raise ParameterError(
                f"override {name!r} is not a declared parameter of pack {pack.specialty!r}"
            )
        resolved[name] = value
    return resolved


def bind_parameters(node: Any, params: dict[str, Any], used: dict[str, Any] | None = None
                    ) -> Any:
    """Recursively substitute every ``{param: <name>}`` placeholder with its resolved value.

    Pure and total: a placeholder whose name is unbound raises ``ParameterError`` (fail loud,
    never guess). Returns a new structure with only literals, ready for ``Rule.model_validate``.
    """
    if isinstance(node, dict):
        if set(node.keys()) == {"param"}:
            name = node["param"]
            if name not in params:
                raise ParameterError(f"unbound parameter {name!r}")
            if used is not None:
                used[name] = params[name]
            return params[name]
        return {k: bind_parameters(v, params, used) for k, v in node.items()}
    if isinstance(node, list):
        return [bind_parameters(v, params, used) for v in node]
    return node


def bind_rule(raw_rule: dict, params: dict[str, Any]) -> Rule:
    """Bind a raw rule body against ``params`` and validate it into a frozen engine ``Rule``."""
    bound = bind_parameters(raw_rule, params)
    return Rule.model_validate(bound)


def pack_rules(pack: SpecialtyPack, overrides: dict[str, Any] | None = None) -> list[Rule]:
    """Every rule in the pack, bound with the effective (default + override) parameters."""
    params = resolve_parameters(pack, overrides)
    return [bind_rule(r, params) for r in pack.raw_rules]


# --------------------------------------------------------------------------------------
# Test-case scenarios (reuse the Rule Studio primitives)
# --------------------------------------------------------------------------------------

def _scenario(tc: dict) -> Scenario:
    return Scenario(
        name=str(tc["name"]),
        marker=CanonicalMarker(tc["marker"]),
        facts=dict(tc.get("facts", {})),
        specialty=tc.get("specialty") or None,
        conflicting_facts=tuple(tc.get("conflicting_facts", []) or []),
    )


def pack_scenarios(pack: SpecialtyPack) -> list[tuple[Scenario, str]]:
    return [(_scenario(tc), str(tc["expected"])) for tc in pack.test_cases]


# --------------------------------------------------------------------------------------
# Validation — the activation gate for a pack
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class PackValidation:
    specialty: str
    ok: bool
    rule_count: int
    test_total: int
    test_passed: int
    safety_ok: bool
    errors: list[str] = field(default_factory=list)

    @property
    def all_tests_passed(self) -> bool:
        return self.test_total > 0 and self.test_passed == self.test_total


def validate_pack(pack: SpecialtyPack, overrides: dict[str, Any] | None = None) -> PackValidation:
    """Run the full pack activation gate (plan Phase 10 exit gate).

    A pack is ``ok`` only if: every rule binds + parses, every rule's marker is registered, no
    rule would down-classify a critical value, the pack declares ≥1 test case, and every test
    case passes. Mirrors the Rule Studio deploy gate so a pack is safe to ship WITHOUT any
    application code change — content and thresholds are data.
    """
    errors: list[str] = []
    try:
        rules = pack_rules(pack, overrides)
    except (PackError, ValueError) as exc:
        return PackValidation(pack.specialty, False, 0, 0, 0, False, [f"bind/parse: {exc}"])

    scenarios = [s for s, _ in pack_scenarios(pack)]

    safety_ok = True
    for rule in rules:
        try:
            assert_cannot_weaken_safety(rule, scenarios)
        except SafetyViolation as exc:
            safety_ok = False
            errors.append(f"safety: {exc}")

    pairs = pack_scenarios(pack)
    results = run_test_cases(pairs, rules)
    passed = sum(1 for r in results if r.passed)
    for r in results:
        if not r.passed:
            errors.append(f"test {r.name!r}: expected {r.expected}, got {r.actual}")
    if not pairs:
        errors.append("pack declares no required test cases")

    ok = not errors and safety_ok and bool(pairs) and passed == len(pairs)
    return PackValidation(
        specialty=pack.specialty, ok=ok, rule_count=len(rules),
        test_total=len(pairs), test_passed=passed, safety_ok=safety_ok, errors=errors,
    )


# --------------------------------------------------------------------------------------
# Coverage — every registered specialty must be served by ≥1 active rule
# --------------------------------------------------------------------------------------

def covered_specialties(packs: list[SpecialtyPack]) -> set[str]:
    covered: set[str] = set()
    for pack in packs:
        covered |= pack.served_specialties
    return covered


def coverage(packs: list[SpecialtyPack], specialty_keys: list[str]) -> dict[str, bool]:
    """Map each registered specialty → whether an active pack rule is scoped to it."""
    covered = covered_specialties(packs)
    return {key: key in covered for key in specialty_keys}


def uncovered(packs: list[SpecialtyPack], specialty_keys: list[str]) -> list[str]:
    return [k for k, ok in coverage(packs, specialty_keys).items() if not ok]
