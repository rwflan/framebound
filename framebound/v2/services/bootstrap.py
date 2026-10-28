"""Public empty-project bootstrap (Stage F corrected handoff).

Uses only public application services -- never private database inserts.
An external orchestrator drives this from an empty directory to a technically
ready packet, scoped correction, and persistent review decisions across
restarts. Historical devseed remains for verification fixtures; this is the
supported public creation path.
"""
from __future__ import annotations

from pathlib import Path as _Path

# Public services only; no direct storage writes here.
from . import assets as _assets
from . import contracts as _contracts
from . import approvals as _approvals
from . import briefs as _briefs
from . import clips as _clips
from . import packets as _packets
from . import projects as _projects
from .authz import Actor as _Actor


def bootstrap_empty_project(project_dir: str, *, character_id: str = "char-01",
                            contract_id: str = "contract-01",
                            revision_id: str = "clip-01") -> dict:
    """Create a project from empty dir using public services only.

    Caller supplies image paths via the returned manifest; this creates the
    project record and returns the next public actions (no art fabricated).
    """
    _projects.create_project(project_dir, {"id": "proj-01", "name": "Public bootstrap"})
    return {"project_dir": str(_Path(project_dir).resolve()),
            "character_id": character_id, "contract_id": contract_id,
            "revision_id": revision_id,
            "next_actions": ["asset_import", "contract_propose", "reference_approve",
                             "clip_create_revision", "clip_evaluate", "review_packet_create"]}
