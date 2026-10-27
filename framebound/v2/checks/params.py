"""Typed check parameters: every contract constraint validates against its check's schema.

Unknown check codes are rejected at contract validation, never silently skipped
at evaluation. Windows are bounds-checked against the contract canvas when known.
"""
from __future__ import annotations

from typing import Any

from pydantic import Field, StrictInt

from ..domain import Strict
from .registry import CHECKS


class _Window(Strict):
    root: list[StrictInt] = Field(min_length=4, max_length=4)


def _window_in_canvas(name: str, w: list[int], cw: int, ch: int) -> None:
    l, t, r, b = w
    if not (0 <= l < r <= cw and 0 <= t < b <= ch):
        raise ValueError(f"{name} {w} outside the {cw}x{ch} canvas")


class RegistrationParams(Strict):
    pass


class SilhouetteParams(Strict):
    max_fraction: float = Field(gt=0, le=1)


class SpanParams(Strict):
    color_a: list[StrictInt] = Field(min_length=3, max_length=3)
    color_b: list[StrictInt] = Field(min_length=3, max_length=3)
    window_a: list[StrictInt] = Field(min_length=4, max_length=4)
    window_b: list[StrictInt] = Field(min_length=4, max_length=4)
    expected: float = Field(ge=0)
    max_delta: float = Field(ge=0)
    occluded_slots: list[StrictInt] = Field(default_factory=list)
    occlusion_note: str = Field(default="", max_length=500)


class PhaseParams(Strict):
    region: list[StrictInt] = Field(min_length=4, max_length=4)
    grid: list[StrictInt] = Field(min_length=2, max_length=2)
    adjacent_slots: list[StrictInt] = Field(default_factory=list)
    alt_slots: list[StrictInt] = Field(default_factory=list)


class ContactsParams(Strict):
    window: list[StrictInt] = Field(min_length=4, max_length=4)
    min_visible: StrictInt = Field(ge=0)
    flight: bool = False
    flight_slots: list[StrictInt] = Field(default_factory=list)
    support_color: list[StrictInt] | None = Field(default=None, min_length=3, max_length=3)


class PaletteParams(Strict):
    max_drift: float = Field(gt=0, le=1)


class PulseParams(Strict):
    max_delta: float = Field(ge=0)


class SlidingParams(Strict):
    tol: float = Field(ge=0)


class CadenceParams(Strict):
    presented: list[StrictInt] | None = None


class SeamParams(Strict):
    region: list[StrictInt] = Field(min_length=4, max_length=4)
    grid: list[StrictInt] = Field(min_length=2, max_length=2)
    max_ratio: float = Field(ge=0)


class ProtectionParams(Strict):
    pass


class ProvenanceParams(Strict):
    pass


PARAM_MODELS: dict[str, type[Strict]] = {
    "native_registration": RegistrationParams,
    "silhouette_area": SilhouetteParams,
    "silhouette_width": SilhouetteParams,
    "silhouette_height": SilhouetteParams,
    "visible_span": SpanParams,
    "phase_correspondence": PhaseParams,
    "declared_contacts": ContactsParams,
    "appearance_palette": PaletteParams,
    "local_pulse": PulseParams,
    "world_sliding": SlidingParams,
    "locked_cadence": CadenceParams,
    "loop_seam": SeamParams,
    "repair_protection": ProtectionParams,
    "provenance_coverage": ProvenanceParams,
}

CANONICAL_CODES = sorted(PARAM_MODELS)


def _finite(v: Any, name: str) -> None:
    import math
    if isinstance(v, float) and not math.isfinite(v):
        raise ValueError(f"{name} must be finite")


def validate_contract_constraints(contract, canvas_w: int | None = None,
                                  canvas_h: int | None = None) -> None:
    """Reject unknown checks, mistyped params, non-finite bounds, out-of-canvas windows."""
    from ..services.errors import InvalidInput
    for c in contract.constraints:
        if c.check not in PARAM_MODELS:
            raise InvalidInput(
                f"unknown check {c.check!r} on constraint {c.id!r}; "
                f"registered checks: {', '.join(CANONICAL_CODES)}")
        try:
            model = PARAM_MODELS[c.check].model_validate(c.params or {})
        except Exception as e:
            raise InvalidInput(f"constraint {c.id!r} ({c.check}): bad params: {e}") from e
        for key in ("max_fraction", "max_drift", "max_delta", "tol", "expected", "max_ratio"):
            _finite_check(model, key, c, InvalidInput)
        if canvas_w is not None and hasattr(model, "window"):
            _checked_window("window", model.window, canvas_w, canvas_h, c, InvalidInput)
        for key in ("window_a", "window_b"):
            if hasattr(model, key):
                _checked_window(key, getattr(model, key), canvas_w, canvas_h, c, InvalidInput)
        if hasattr(model, "region") and canvas_w is not None:
            _checked_window("region", model.region, canvas_w, canvas_h, c, InvalidInput)


def _finite_check(model, key, c, InvalidInput):
    v = getattr(model, key, None)
    if v is not None:
        try:
            _finite(v, key)
        except ValueError as e:
            raise InvalidInput(f"constraint {c.id!r} ({c.check}): {e}") from e


def _checked_window(name, w, cw, ch, c, InvalidInput):
    if cw is None or ch is None:
        return
    try:
        _window_in_canvas(name, list(w), cw, ch)
    except ValueError as e:
        raise InvalidInput(f"constraint {c.id!r} ({c.check}): {e}") from e


def registered_codes() -> list[str]:
    return [c for c in CANONICAL_CODES if c in CHECKS]
