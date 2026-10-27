"""Integer timeline: half-open hold intervals, exact tick selection, trace rendering."""
from __future__ import annotations


def select_slot(holds: list[int], tick: int, loop: bool) -> int:
    total = sum(holds)
    t = tick % total if loop else min(tick, total - 1)
    acc = 0
    for i, h in enumerate(holds):
        if acc <= t < acc + h:
            return i
        acc += h
    raise AssertionError("unreachable")


def render_trace(holds: list[int], loop: bool, ticks: int) -> list[int]:
    return [select_slot(holds, t, loop) for t in range(ticks)]
