"""Actor separation enforced in service authorization, not hidden in tool names.

Orchestrator credentials may propose, generate, repair, and acknowledge — they may never
write reviewer decisions, freeze reference approvals, or alter publication gates.
Review writes require a reviewer session. Local dev must not let the model token act as reviewer.
"""
from __future__ import annotations

from dataclasses import dataclass

from .errors import AuthorizationError

REVIEWER_ONLY_OPS = frozenset({
    "approve_reference", "approve", "approve_art", "reject", "reject_art", "needs_changes",
    "mark_issue", "resolve_issue", "reopen_issue", "approve_mask", "release_publication", "freeze_approval",
})


@dataclass(frozen=True)
class Actor:
    type: str  # "reviewer" | "orchestrator" | "system"
    id: str


def require_reviewer(actor: Actor, op: str) -> None:
    if actor.type != "reviewer":
        raise AuthorizationError(
            f"op {op} requires a reviewer session; actor {actor.type}:{actor.id} is not permitted")
