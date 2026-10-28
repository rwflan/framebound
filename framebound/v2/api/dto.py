"""Wire DTOs for the review desk: one typed contract per endpoint.

These Pydantic models are the single source for `web/src/api-types.ts`
(via scripts/gen_api_types.py) and are enforced as FastAPI response models
with extra="allow": documented fields are guaranteed, server additions never
break the desk. A regression test validates live responses against these.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Strict(BaseModel):
    model_config = {"extra": "allow", "str_strip_whitespace": True}


class CanvasDto(Strict):
    width: int = 0
    height: int = 0
    units: str = "native_px"


class CharacterReferenceDto(Strict):
    id: str
    identity_asset_ids: list[str]
    style_asset_ids: list[str]


class GuideEntryDto(Strict):
    phase: str
    asset_id: str


class GuideReferenceDto(Strict):
    id: str
    character_revision_id: str
    entries: list[GuideEntryDto]


class ReferenceApprovalDto(Strict):
    character_revision_id: str
    motion_guide_id: str


class ReferencesDto(Strict):
    character_revisions: list[CharacterReferenceDto]
    motion_guides: list[GuideReferenceDto]
    reference_approvals: list[ReferenceApprovalDto]
    assets: list[dict[str, Any]]


class ReferenceApproveBodyDto(Strict):
    model_config = {'extra': 'forbid'}
    character_revision_id: str
    motion_guide_id: str
    event_id: str | None = None


class TimingDto(Strict):
    ticks_per_second: int = 60
    holds: list[int] = Field(default_factory=list)


class FrameRefDto(Strict):
    frame_instance_id: str
    slot: int
    asset_id: str
    phase: str
    hold_ticks: int
    asset_url: str


class EvalResultDto(Strict):
    constraint_id: str
    scope: str
    outcome: str
    reason: str


class EvaluationDto(Strict):
    id: str
    technical_status: str
    coverage_status: str
    results: list[EvalResultDto]


class PacketBundleDto(Strict):
    packet: dict[str, Any]
    evaluation: EvaluationDto
    revision: dict[str, Any]
    frames: list[FrameRefDto]
    contract: dict[str, Any]
    current_decision: dict[str, Any]


class CompareSideDto(Strict):
    revision_id: str
    contract_id: str
    evaluation_id: str | None
    technical_status: str
    frames: list[FrameRefDto]
    holds: list[int]
    ticks_per_second: int
    loop: bool


class CompareBundleDto(Strict):
    base: CompareSideDto
    other: CompareSideDto
    same_contract: bool
    timing_equal: bool
    timing_note: str


class AttemptViewDto(Strict):
    id: str
    result: str
    candidates: list[str]


class IssueDetailDto(Strict):
    event_id: str
    clip_revision_id: str
    category: str
    note: str
    actor_id: str
    created_at: str
    lease_valid: bool
    attempts: list[AttemptViewDto]
    candidate_revisions: list[dict[str, Any]]
    findings: list[EvalResultDto]
    coverage: str
    current_acceptance: str
    packet_id: str | None = None
    frame_instance_id: str | None = None
    frame_range: list[int] | None = None
    roi: dict[str, int] | None = None
    task_id: str | None = None
    task_status: str | None = None
    baseline_evaluation_id: str | None = None
    resolution_event_id: str | None = None


class TaskStatusDto(Strict):
    task: dict[str, Any]
    version: int
    lease_valid: bool
    attempts: list[AttemptViewDto]
    issue: dict[str, Any] | None = None


class CorrectionsListDto(Strict):
    open: list[dict[str, Any]] | None = None
    tasks: list[dict[str, Any]] | None = None
    count: int = 0


class ActivityEventDto(Strict):
    id: str
    action: str
    actor_type: str
    actor_id: str
    clip_revision_id: str
    packet_id: str | None = None
    created_at: str
    note: str


class ActivityPageDto(Strict):
    events: list[ActivityEventDto]
    cursor: str | None = None


class ContactSheetDto(Strict):
    packet_id: str = ""
    revision_id: str = ""
    image_url: str = ""
    slots: int = 0
    content_sha256: str = ""


class PreviewDto(Strict):
    packet_id: str
    revision_id: str
    artifact: str
    video_url: str
    frames: int
    ticks_per_second: int
    total_ticks: int
    ffmpeg_command: str
    content_sha256: str


class ExportResultDto(Strict):
    name: str
    ok: bool
    issues: list[str]
    skipped: list[str]
    counts: dict[str, int]
    exclusions: list[dict[str, Any]]


class EligibilityDto(Strict):
    revision_id: str
    eligible: bool
    evaluation_id: str | None
    reasons: list[str]


class ProjectSummaryDto(Strict):
    summary: dict[str, Any] = Field(default_factory=dict)


class PacketsDto(Strict):
    packets: list[dict[str, Any]] = Field(default_factory=list)


class CorrectionSubmitResultDto(Strict):
    ok: bool = False
    attempt_id: str | None = None
    revision_id: str | None = None
    evaluation: dict[str, Any] | None = None
    packet: dict[str, Any] | None = None
    subjective: bool = False
    awaiting_human_comparison: bool = False
    task_status: str | None = None
    reason: str | None = None
    deduped: bool = False


class MaskApproveResultDto(Strict):
    id: str = ""
    issue_event_id: str = ""
    task_id: str = ""
    mask_asset_id: str = ""
    covered_slots: list[int] = Field(default_factory=list)
    approved_by: str = ""
    approval_event_id: str = ""
