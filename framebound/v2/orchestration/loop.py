"""Bounded tool loop: retrieve state → brief → submit/register → evaluate → bounded repair → packet.

Stops at awaiting_review. Resumes only for a new correction or authorized task.
Parallelizes independent frame checks/provider requests within budgets; never mutates the
same revision concurrently; tool calls match results before the next model turn.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LoopConfig:
    max_attempts_per_target: int = 3
    cost_ceiling: str = "project-default"
    poll_backoff_seconds: float = 2.0


@dataclass
class BoundedLoop:
    config: LoopConfig = field(default_factory=LoopConfig)
    attempts: dict[str, int] = field(default_factory=dict)
    seen_signatures: list[str] = field(default_factory=list)

    def next_step(self, state: str, targets: list[str]) -> dict:
        """Decide the next controller action given persisted run state."""
        if state == "awaiting_review":
            return {"action": "stop", "reason": "awaiting human review; generation halted"}
        key = ",".join(sorted(targets))
        used = self.attempts.get(key, 0)
        if used >= self.config.max_attempts_per_target:
            return {"action": "needs_attention", "reason": f"budget exhausted for {key}",
                    "evidence": {"attempts": used, "targets": targets}}
        self.attempts[key] = used + 1
        return {"action": "attempt", "attempt": used + 1,
                "budget": self.config.max_attempts_per_target, "targets": targets}

    def observe_result(self, signature: str) -> dict:
        if signature in self.seen_signatures:
            return {"action": "needs_attention", "reason": "no-progress signature repeated; stop blind retry"}
        self.seen_signatures.append(signature)
        return {"action": "continue"}
