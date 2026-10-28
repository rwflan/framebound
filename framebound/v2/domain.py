"""v2 domain models: explicit authority boundaries, separate states, frozen contracts.

Pydantic v2 strict models. Schema version "2.0" throughout. A contract revision is
immutable once stored: changes create a new revision with supersedes + reason.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator
import math

HEX64 = {"pattern": r"^[0-9a-fA-F]{64}$"}


def _finite_float(v):
    """Reject NaN/inf where a real measurement or bound is required."""
    if v is not None and isinstance(v, float) and not math.isfinite(v):
        raise ValueError("must be a finite number")
    return v


SCHEMA_VERSION = "2.0"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TechnicalStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INCOMPLETE = "incomplete"
    ERROR = "error"


class CoverageStatus(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


class HumanAcceptance(str, Enum):
    UNREVIEWED = "unreviewed"
    NEEDS_CHANGES = "needs_changes"
    APPROVED = "approved"
    REJECTED = "rejected"


class PublicationStatus(str, Enum):
    DRAFT = "draft"
    CANDIDATE = "candidate"
    RELEASED = "released"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NEEDS_ATTENTION = "needs_attention"


class CheckOutcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNMEASURED = "unmeasured"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


class CorrectionStatus(str, Enum):
    OPEN = "open"
    CLAIMED = "claimed"
    ATTEMPTING = "attempting"
    AWAITING_COMPARISON = "awaiting_comparison"
    RESOLVED = "resolved"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    REOPENED = "reopened"


class Strict(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}


class Canvas(Strict):
    width: StrictInt = Field(gt=0, le=2048)
    height: StrictInt = Field(gt=0, le=2048)
    units: Literal["native_px"] = "native_px"


class Timing(Strict):
    ticks_per_second: StrictInt = Field(default=60, gt=0, le=240)
    holds: list[StrictInt] = Field(min_length=1, max_length=512)

    @field_validator("holds")
    @classmethod
    def _positive_holds(cls, v: list[int]) -> list[int]:
        if any(not isinstance(h, int) or h <= 0 for h in v):
            raise ValueError("holds must be positive integers (half-open tick intervals)")
        return v

    def total_ticks(self) -> int:
        return sum(self.holds)

    def slot_at_tick(self, tick: int, loop: bool) -> int:
        """Half-open interval selection: slot i covers [sum(holds[:i]), sum(holds[:i+1]))."""
        total = self.total_ticks()
        if total <= 0:
            raise ValueError("empty timing")
        t = tick % total if loop else min(tick, total - 1)
        acc = 0
        for i, h in enumerate(self.holds):
            if acc <= t < acc + h:
                return i
            acc += h
        raise AssertionError("unreachable tick mapping")


class ActionIntent(Strict):
    name: str = Field(min_length=1, max_length=64)
    view: str = Field(min_length=1, max_length=32)
    facing: Literal["left", "right"] = "right"
    loop: bool = True


class RootPolicy(Strict):
    mode: Literal["in_place", "world_grounded"] = "in_place"
    ground_y: float | None = None


class PhaseEntry(Strict):
    slot: StrictInt = Field(ge=0)
    phase: str = Field(min_length=1, max_length=64)
    motion_reference_id: str = Field(min_length=1)


class ConstraintSpec(Strict):
    id: str = Field(min_length=1, max_length=64)
    check: str = Field(min_length=1, max_length=64)
    required: bool = True
    annotation_revision_id: str | None = None
    reference_revision_id: str | None = None
    max_error_px: float | None = Field(default=None, ge=0)

    _finite_max_error = field_validator("max_error_px")(classmethod(lambda cls, v: _finite_float(v)))
    params: dict[str, Any] = Field(default_factory=dict)


class AllowedTransforms(Strict):
    per_pose_scale: bool = False
    rigid_translation_budget_px: float = Field(default=2.0, ge=0)

    _finite_budget = field_validator("rigid_translation_budget_px")(classmethod(lambda cls, v: _finite_float(v)))


class Project(Strict):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    owner: str = Field(min_length=1, max_length=200)
    creation_time: str = Field(default_factory=utcnow)
    rights_policy: str = Field(min_length=1, max_length=200)


class Asset(Strict):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    byte_sha256: str = Field(**HEX64)
    pixel_sha256: str | None = Field(default=None, **HEX64)
    mime: str = Field(min_length=1, max_length=128)
    width: int | None = Field(default=None, gt=0, le=8192)
    height: int | None = Field(default=None, gt=0, le=8192)
    color_policy: str = "srgb_straight_alpha_rgba8"
    alpha_policy: str = Field(default="straight", min_length=1, max_length=64)
    source_kind: Literal["original", "procedural", "generated", "derived", "imported"] = "original"
    lineage: str = Field(default="", max_length=500)
    rights: str = Field(min_length=1, max_length=200)
    eligible_roles: list[str] = Field(default_factory=list)


class CharacterRevision(Strict):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1)
    identity_asset_ids: list[str] = Field(min_length=1)
    style_asset_ids: list[str] = Field(min_length=1)
    view_set: list[str] = Field(min_length=1)
    canvas: Canvas
    scale_ruler: str = Field(min_length=1, max_length=500)
    asymmetry: str = Field(default="symmetric",
        description="'symmetric', or a description of asymmetric costume/weapon layout; "
                    "exact mirrors are prohibited as new drawings when asymmetric")
    reference_approval: dict[str, Any] | None = None  # explicit human approval event ref when set

    @field_validator("identity_asset_ids", "style_asset_ids")
    @classmethod
    def _distinct_roles(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("duplicate asset in role list")
        return v


class ClipContractRevision(Strict):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    character_revision_id: str = Field(min_length=1)
    action: ActionIntent
    canvas: Canvas
    timing: Timing
    root_policy: RootPolicy = Field(default_factory=RootPolicy)
    references: dict[str, str] = Field(min_length=1)
    phase_schedule: list[PhaseEntry] = Field(min_length=1)
    constraints: list[ConstraintSpec] = Field(default_factory=list)
    allowed_transforms: AllowedTransforms = Field(default_factory=AllowedTransforms)
    transition_contract_ids: list[str] = Field(default_factory=list)
    supersedes: str | None = None
    change_reason: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _schedule_covers_holds(self) -> "ClipContractRevision":
        slots = sorted(e.slot for e in self.phase_schedule)
        if len(set(slots)) != len(slots):
            raise ValueError("duplicate slot in phase_schedule")
        if slots != list(range(len(self.timing.holds))):
            raise ValueError(
                f"phase_schedule slots {slots} must cover exactly holds range 0..{len(self.timing.holds) - 1}"
            )
        cids = [c.id for c in self.constraints]
        if len(set(cids)) != len(cids):
            raise ValueError("duplicate constraint id")
        return self


class FrameInstance(Strict):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    clip_revision_id: str = Field(min_length=1)
    slot: int = Field(ge=0)
    asset_id: str = Field(min_length=1)
    phase: str = Field(min_length=1)
    hold_ticks: int = Field(gt=0)
    registration_id: str = Field(min_length=1)
    source_drawing_id: str = Field(min_length=1)
    derivation_recipe: str = Field(min_length=1, max_length=500)
    part_mask_ids: list[str] = Field(default_factory=list)


class TransformOp(Strict):
    op: Literal["translate"] = "translate"
    dx: StrictInt = Field(ge=-512, le=512)
    dy: StrictInt = Field(ge=-512, le=512)


class TransformSpec(Strict):
    """Typed recorded transform: the only thing that can authorize pixel movement.

    A free-text recipe string never authorizes a transform; it is documentation.
    mirror/per_pose_scale are checked against the character + contract at use time.
    """
    ops: list[TransformOp] = Field(default_factory=list)
    mirror: bool = False
    per_pose_scale: bool = False
    note: str = Field(default="", max_length=500)


class Registration(Strict):
    """Persisted verified recipe: how a frame's pixels sit on the frozen canvas."""
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    method: Literal["frozen_native", "verified_translate"] = "frozen_native"
    frame_instance_id: str = Field(min_length=1)
    translation_px: list[StrictInt] = Field(default_factory=lambda: [0, 0],
                                           min_length=2, max_length=2)
    transform: TransformSpec = Field(default_factory=TransformSpec)
    verified_by: str = Field(default="import", min_length=1, max_length=200)
    created_at: str = Field(default_factory=utcnow)


class ClipRevision(Strict):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    contract_revision_id: str = Field(min_length=1)
    frame_instance_ids: list[str] = Field(min_length=1)
    parent_revision_id: str | None = None
    origin_run_id: str | None = None
    created_at: str = Field(default_factory=utcnow)

    @field_validator("frame_instance_ids")
    @classmethod
    def _unique_frames(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("duplicate frame instance in clip revision")
        return v


class AnnotationRevision(Strict):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    source_asset_id: str = Field(min_length=1)
    source_pixel_sha256: str = Field(**HEX64)
    view: str = Field(min_length=1)
    coordinate_space: Literal["native_px"] = "native_px"
    visibility: Literal["visible", "occluded", "ambiguous"] = "visible"
    annotator_type: Literal["human_reviewed", "model_proposed", "imported"] = "model_proposed"
    role: str = Field(default="support", min_length=1, max_length=64)
    frame_instance_id: str | None = None
    points: list[list[float]] | None = Field(default=None, min_length=1)
    mask_asset_id: str | None = None
    transform: dict[str, Any] | None = None
    reviewer: str | None = None
    proposal_event_id: str | None = None
    review_event_id: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    _finite_confidence = field_validator("confidence")(classmethod(lambda cls, v: _finite_float(v)))
    supersedes: str | None = None

    @model_validator(mode="after")
    def _geometry_present(self) -> "AnnotationRevision":
        if self.points is None and self.mask_asset_id is None:
            raise ValueError("annotation needs point geometry, a mask asset, or both: "
                             "a bare label cannot support measurements")
        if self.points is not None:
            for pt in self.points:
                if len(pt) != 2 or not all(math.isfinite(v) for v in pt):
                    raise ValueError("annotation points must be finite [x, y] native_px pairs")
        return self


class CheckResult(Strict):
    constraint_id: str = Field(min_length=1)
    scope: str = Field(min_length=1, max_length=200)
    outcome: CheckOutcome
    observed_value: float | str | None = None
    units: str | None = None
    expected_interval: list[float] | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def _unmeasured_needs_reason(self) -> "CheckResult":
        if self.outcome in (CheckOutcome.UNMEASURED, CheckOutcome.NOT_APPLICABLE, CheckOutcome.ERROR):
            if not self.reason or len(self.reason.strip()) < 8:
                raise ValueError(f"{self.outcome} results need an explicit reason + applicability rule")
        return self


class Evaluation(Strict):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    clip_revision_id: str = Field(min_length=1)
    evidence_manifest_sha256: str = Field(**HEX64)
    analyzer_version: str = Field(min_length=1)
    dependency_lock_id: str = Field(min_length=1)
    results: list[CheckResult] = Field(min_length=1)
    technical_status: TechnicalStatus
    coverage_status: CoverageStatus
    supersedes: str | None = None
    created_at: str = Field(default_factory=utcnow)


class Attempt(Strict):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    baseline_revision_id: str = Field(min_length=1)
    brief_id: str = Field(min_length=1)
    provider: str = Field(min_length=1, max_length=64)
    request_sha256: str = Field(**HEX64)
    response_ref: str | None = None
    candidate_asset_ids: list[str] = Field(default_factory=list)
    cost: str = Field(default="unknown", max_length=200)
    repair_mask_id: str | None = None
    targeted_issue_ids: list[str] = Field(default_factory=list)
    result: str = Field(min_length=1, max_length=64)
    no_progress_signature: str | None = None


class ReviewPacket(Strict):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    clip_revision_id: str = Field(min_length=1)
    evaluation_id: str = Field(min_length=1)
    intent: str = Field(min_length=1, max_length=500)
    comparison_revision_id: str | None = None
    issue_ids: list[str] = Field(default_factory=list)
    unresolved_coverage: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utcnow)


class Roi(Strict):
    left: StrictInt = Field(ge=0)
    top: StrictInt = Field(ge=0)
    right: StrictInt = Field(ge=0)
    bottom: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def _nonempty(self) -> "Roi":
        if not (self.right > self.left and self.bottom > self.top):
            raise ValueError("ROI must be a non-empty pixel-edge rect [left, top, right, bottom)")
        return self


class ReviewEvent(Strict):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    actor_type: Literal["reviewer", "orchestrator", "system"] = "reviewer"
    actor_id: str = Field(min_length=1, max_length=200)
    action: Literal["approve_reference", "approve", "reject", "needs_changes", "mark_issue", "resolve_issue", "reopen_issue", "approve_mask"] = "mark_issue"
    packet_id: str | None = None
    clip_revision_id: str = Field(min_length=1)
    frame_instance_id: str | None = None
    frame_range: list[StrictInt] | None = None
    category: str = Field(default="general", min_length=1, max_length=64)
    roi: Roi | None = None
    note: str = Field(default="", max_length=2000)
    supersedes: str | None = None
    created_at: str = Field(default_factory=utcnow)

    @model_validator(mode="after")
    def _range_shape(self) -> "ReviewEvent":
        if self.frame_range is not None:
            if len(self.frame_range) != 2 or self.frame_range[0] < 0 \
                    or self.frame_range[1] < self.frame_range[0]:
                raise ValueError("frame_range must be [start_tick, end_tick] with 0 <= start <= end")
        return self


class CorrectionTask(Strict):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    source_issue_event_id: str = Field(min_length=1)
    baseline_revision_id: str = Field(min_length=1, max_length=128)
    baseline_evaluation_id: str | None = None
    edit_mask_id: str | None = None
    desired_outcome: str = Field(min_length=1, max_length=1000)
    scope: str = Field(min_length=1, max_length=500)
    status: CorrectionStatus = CorrectionStatus.OPEN
    claim_holder: str | None = Field(default=None, min_length=1, max_length=200)
    claim_token_sha256: str | None = Field(default=None, **HEX64)
    claim_lease: str | None = None
    attempt_ids: list[str] = Field(default_factory=list)
    resolution_event_id: str | None = None
    last_error: str | None = Field(default=None, max_length=2000)
    created_at: str = Field(default_factory=utcnow)


class EditMask(Strict):
    """Reviewer-approved edit support: exactly which pixels a repair may touch.

    An issue ROI suggests scope but never authorizes pixels by itself. Changed
    candidate pixels must lie inside the ROI and/or this approved mask.
    """
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    issue_event_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    mask_asset_id: str = Field(min_length=1)
    mask_byte_sha256: str = Field(**HEX64)
    covered_slots: list[StrictInt] = Field(min_length=1)
    approved_by: str = Field(min_length=1, max_length=200)
    approval_event_id: str = Field(min_length=1)
    created_at: str = Field(default_factory=utcnow)


class Job(Strict):
    """Durable generation job. New fields default so pre-R3 rows still load."""
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    kind: str = Field(min_length=1, max_length=64)
    status: JobStatus = JobStatus.QUEUED
    idempotency_key: str = Field(min_length=1, max_length=256)
    payload_sha256: str = Field(**HEX64)
    provider: str = Field(default="image", max_length=64)
    targets: list[str] = Field(default_factory=list)
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1, le=10)
    budget_reserved: str = Field(default="unbounded-note", max_length=200)
    cost_estimate: str = Field(default="unknown", max_length=200)
    cost_actual: str = Field(default="unknown", max_length=200)
    no_progress_signatures: list[str] = Field(default_factory=list)
    request_brief: dict[str, Any] = Field(default_factory=dict)
    provider_settings: dict[str, Any] = Field(default_factory=dict)
    origin: str = Field(default="unknown", max_length=64)
    fencing_token_sha256: str = ""
    dispatch_count: int = Field(default=0, ge=0)
    reserved_cost: str = Field(default="unbounded-note", max_length=200)
    request_artifact: str | None = None
    response_artifact: str | None = None
    output_asset_ids: list[str] = Field(default_factory=list)
    reconciliation_required: bool = False
    cancel_requested: bool = False
    offline: bool = False
    lease_holder: str | None = None
    lease_expires: str | None = None
    error: str | None = Field(default=None, max_length=2000)
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class Run(Strict):
    """Durable orchestrator run: budget + halt state survive restarts."""
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    status: str = Field(default="running", max_length=64)
    job_ids: list[str] = Field(default_factory=list)
    attempts_used: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1, le=10)
    halt_reason: str | None = Field(default=None, max_length=1000)
    created_at: str = Field(default_factory=utcnow)
    updated_at: str = Field(default_factory=utcnow)


class ExportSnapshot(Strict):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    clip_revision_ids: list[str] = Field(min_length=1)
    policy: str = Field(min_length=1, max_length=500)
    dependency_lock_id: str = Field(min_length=1)
    byte_manifest: dict[str, str] = Field(min_length=1)
    created_at: str = Field(default_factory=utcnow)


class MotionGuideEntry(Strict):
    phase: str = Field(min_length=1, max_length=64)
    asset_id: str = Field(min_length=1, max_length=128)
    byte_sha256: str = Field(**HEX64)


class MotionGuide(Strict):
    """Independent phase authority: reviewed reference art per phase, not candidate-derived."""
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    character_revision_id: str = Field(min_length=1)
    entries: list[MotionGuideEntry] = Field(min_length=1)
    supersedes: str | None = None
    created_at: str = Field(default_factory=utcnow)


class ReferenceApproval(Strict):
    """Stored human approval binding a character revision's references + motion guide."""
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    character_revision_id: str = Field(min_length=1)
    motion_guide_id: str = Field(min_length=1)
    identity_asset_ids: list[str] = Field(min_length=1)
    style_asset_ids: list[str] = Field(min_length=1)
    asset_hashes: dict[str, str] = Field(min_length=1)
    reviewer_id: str = Field(min_length=1, max_length=200)
    event_id: str = Field(min_length=1, max_length=128)
    supersedes: str | None = None
    created_at: str = Field(default_factory=utcnow)


class CompiledBrief(Strict):
    """Immutable frozen conditioning: the ONLY submittable generation request.

    Binds contract/character revisions, the exact human approval + motion guide
    (ids + asset hashes), slot/phase/timing, the full brief dict digest, and
    the per-role asset byte/pixel hashes the provider must receive. Versioned;
    legacy dict-only briefs are rejected at submission, never recompiled from
    caller claims.
    """
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    contract_revision_id: str = Field(min_length=1, max_length=128)
    character_revision_id: str = Field(min_length=1, max_length=128)
    approval_id: str = Field(min_length=1, max_length=128)
    approval_event_id: str = Field(min_length=1, max_length=128)
    motion_guide_id: str = Field(min_length=1, max_length=128)
    slot: StrictInt = Field(ge=0)
    phase: str = Field(min_length=1, max_length=64)
    phase_asset_id: str = Field(min_length=1, max_length=128)
    phase_byte_sha256: str = Field(**HEX64)
    identity_asset_id: str = Field(min_length=1, max_length=128)
    style_asset_id: str = Field(min_length=1, max_length=128)
    brief_digest: str = Field(**HEX64)
    brief: dict[str, Any] = Field(min_length=1)
    created_at: str = Field(default_factory=utcnow)


class WorldTrace(Strict):
    """Stored per-tick world grounding for one clip revision (frozen).

    positions/planted cover every held tick in order; evaluation binds them to
    world_sliding/declared_contacts instead of passing silently. Length must
    equal the contract's total held ticks.
    """
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    id: str = Field(min_length=1, max_length=128)
    clip_revision_id: str = Field(min_length=1, max_length=128)
    positions: list[list[float]] = Field(min_length=1)
    planted: list[bool] = Field(min_length=1)
    units: str = Field(default="world_units", max_length=64)
    created_at: str = Field(default_factory=utcnow)


class ReviewerPairing(Strict):
    code_sha256: str = Field(**HEX64)
    reviewer_id: str = Field(min_length=1, max_length=200)
    expires_at: str = Field(min_length=1)
    used: bool = False


class ReviewerSession(Strict):
    token_sha256: str = Field(**HEX64)
    reviewer_id: str = Field(min_length=1, max_length=200)
    created_at: str = Field(default_factory=utcnow)
    expires_at: str = Field(min_length=1)


class ResultEnvelope(Strict):
    schema_version: Literal["2.0"] = SCHEMA_VERSION
    ok: bool = True
    operation_id: str = Field(min_length=1)
    revision_id: str | None = None
    technical_status: TechnicalStatus | None = None
    human_acceptance: HumanAcceptance = HumanAcceptance.UNREVIEWED
    coverage: dict[str, int] | None = None
    issues: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    cursor: str | None = None
