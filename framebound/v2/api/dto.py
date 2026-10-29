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
    project_id: str | None = None
    identity_asset_ids: list[str]
    style_asset_ids: list[str]


class GuideEntryDto(Strict):
    phase: str
    asset_id: str
    editable_mask_asset_id: str | None = None
    protected_mask_asset_id: str | None = None


class GuideReferenceDto(Strict):
    id: str
    character_revision_id: str
    entries: list[GuideEntryDto]
    repair_policy: dict[str,Any] | None = None
    source_calibration: dict[str,Any] | None = None


class ReferenceApprovalDto(Strict):
    id: str
    character_revision_id: str
    motion_guide_id: str


class ReferencesDto(Strict):
    character_revisions: list[CharacterReferenceDto]
    motion_guides: list[GuideReferenceDto]
    reference_approvals: list[ReferenceApprovalDto]
    assets: list[dict[str, Any]]
    revoked_approval_ids: list[str]
    active_approval_ids: list[str]


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
    observed_value: float | str | None = None
    units: str | None = None
    expected_interval: list[float] | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class EvaluationDto(Strict):
    id: str
    technical_status: str
    coverage_status: str
    results: list[EvalResultDto]
    created_at: str | None = None
    evidence_manifest_sha256: str | None = None


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


class ProjectEntryDto(Strict):
    id: str
    name: str


class DeskSessionDto(Strict):
    ready: bool


class ChangesDto(Strict):
    revision: str


class ProjectSummaryDto(Strict):
    summary: dict[str, Any] = Field(default_factory=dict)
    projects: list[ProjectEntryDto] = Field(default_factory=list)


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


from pydantic import StrictBool,StrictInt
from ..services.provider_grants import ProviderGrant as _ProviderGrant
from ..services.provider_recovery import ProviderReceipt as _ProviderReceipt


class AnimationStartBodyDto(Strict):
    model_config={'extra':'forbid'}
    revision_id: str = Field(min_length=1)
    idempotency_key: str | None = None
    provider_settings: dict[str,Any] | None = None
    offline: StrictBool = True


class AnimationRunDto(Strict):
    run_id: str
    status: str
    revision_id: str | None = None
    compiled_plan_id: str | None = None
    local_attempts_used: int | None = None
    compute_steps_used: int | None = None
    operation_ids: list[str] | None = None
    blocker: str | None = None
    evaluation_id: str | None = None
    packet_id: str | None = None
    job_id: str | None = None
    acceptance: str | None = None


class ProviderGrantDto(_ProviderGrant,Strict):
    model_config={'extra':'forbid'}


class ProviderGrantViewDto(Strict):
    grant: ProviderGrantDto
    version: int


class ExpectedVersionBodyDto(Strict):
    model_config={'extra':'forbid'}
    expected_version: StrictInt = Field(ge=1)


class ProviderGrantRevokeResultDto(Strict):
    grant_id: str
    active: bool
    version: int


class ProviderReceiptBodyDto(_ProviderReceipt,Strict):
    model_config={'extra':'forbid'}


class ProviderReconcileResultDto(Strict):
    job_id: str
    status: str
    version: int


class ReferenceRevokeBodyDto(Strict):
    model_config={'extra':'forbid'}
    event_id: str | None = Field(default=None,min_length=1,max_length=128)
    note: str = Field(default='',max_length=2000)


class ReferenceRevokeResultDto(Strict):
    ok: bool
    event_id: str
    approval_id: str
    active: bool


class JobSubmitRequestDto(Strict):
    model_config={'extra':'forbid'}
    brief: dict[str,Any]
    references: list[dict[str,Any]] = Field(default_factory=list)
    idempotency_key: str = Field(min_length=1)
    provider_settings: dict[str,Any] | None = None
    offline: StrictBool = False
    max_attempts: StrictInt = Field(default=3,ge=1,le=10)


class CapabilityEvidenceDto(Strict):
    capability: str
    designed: bool
    implemented: bool
    negative_tested: bool
    public_integrated: bool
    live_observed: bool | None
    human_reviewed: bool | None
    receipts: list[str]
