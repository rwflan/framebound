"""Check registry: every check declares applicability, inputs, units, limits, blind spots."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CheckSpec:
    code: str
    schema_version: str = "2.0"
    applicability: str = ""
    required_inputs: str = ""
    method: str = ""
    units: str = ""
    limits: str = ""
    severity: str = "error"
    coverage: str = "required"
    blind_spots: str = ""


CHECKS: dict[str, CheckSpec] = {}


def register(spec: CheckSpec):
    CHECKS[spec.code] = spec
    return spec


def get_check(code: str) -> CheckSpec:
    if code not in CHECKS:
        raise KeyError(f"unknown check {code}")
    return CHECKS[code]
