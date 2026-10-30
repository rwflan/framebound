"""Agent task semantics. Never reinterpret v2 guide or reviewer authority."""
from typing import Literal

from pydantic import Field, StrictInt, model_validator

from ..v2.domain import Canvas, Timing, Strict, utcnow


class InputBinding(Strict):
    asset_id: str = Field(min_length=1, max_length=128)
    role: Literal['identity', 'style', 'keyframe', 'mask', 'known_good_animation', 'design_proposal']
    provenance: str = Field(min_length=1, max_length=2000)
    designated_by: str = Field(min_length=1, max_length=200)
    basis: str = Field(min_length=1, max_length=2000)
    tick_range: tuple[StrictInt, StrictInt] | None = None

    @model_validator(mode='after')
    def valid_range(self):
        if self.tick_range and not (0 <= self.tick_range[0] < self.tick_range[1]):
            raise ValueError('input tick range must be nonempty and half-open')
        return self


class Requirement(Strict):
    id: str = Field(min_length=1, max_length=128)
    check: str = Field(min_length=1, max_length=128)
    required: bool = True
    desired_outcome: str = Field(min_length=1, max_length=2000)


class CompletionPolicy(Strict):
    id: Literal['technical-unreviewed-v1', 'human-reviewed-v1'] = 'technical-unreviewed-v1'
    creative_owner: Literal['agent', 'human'] = 'agent'


class Limits(Strict):
    max_submissions: StrictInt = Field(default=8, ge=1, le=1000)
    max_unchanged: StrictInt = Field(default=2, ge=1, le=100)
    provider_execution: Literal['external_only'] = 'external_only'


class TaskSpec(Strict):
    schema_version: Literal['3.0'] = '3.0'
    id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    animation_id: str = Field(min_length=1, max_length=128)
    intent: str = Field(min_length=1, max_length=8000)
    subjects: str = Field(min_length=1, max_length=2000)
    appearance: str = Field(default='', max_length=4000)
    scene_camera: str = Field(default='fixed canvas, controlled view', max_length=2000)
    interactions: str = Field(default='', max_length=2000)
    canvas: Canvas
    timing: Timing
    loop: bool = True
    delivery: str = Field(default='ordered native PNG frames with authored holds', max_length=2000)
    inputs: list[InputBinding] = Field(default_factory=list, max_length=512)
    preserve: list[str] = Field(default_factory=list, max_length=128)
    allowed_changes: list[str] = Field(default_factory=list, max_length=128)
    repair_scope: Literal['full_clip', 'declared_regions'] = 'full_clip'
    profile: Literal['structural-v1', 'fixed-subject-v1'] = 'structural-v1'
    requirements: list[Requirement] = Field(default_factory=list, max_length=128)
    limits: Limits = Field(default_factory=Limits)
    completion: CompletionPolicy = Field(default_factory=CompletionPolicy)
    intervention: Literal['blockers_only', 'explicit_review'] = 'blockers_only'
    supersedes: str | None = Field(default=None, min_length=1, max_length=128)
    change_reason: str | None = Field(default=None, min_length=1, max_length=2000)
    created_at: str = Field(default_factory=utcnow)

    @model_validator(mode='after')
    def valid_spec(self):
        if bool(self.supersedes) != bool(self.change_reason):
            raise ValueError('superseding a specification requires a recorded reason')
        ids = [r.id for r in self.requirements]
        if len(ids) != len(set(ids)):
            raise ValueError('requirement IDs must be unique')
        if any(i.tick_range and i.tick_range[1] > self.timing.total_ticks() for i in self.inputs):
            raise ValueError('input coverage exceeds task timing')
        return self


class NegotiatedRequirement(Strict):
    id: str
    check: str
    required: bool
    applicability: Literal['supported', 'missing_evidence', 'unsupported']
    method: str
    limitation: str
    ways_forward: list[str] = Field(default_factory=list)


class TaskRecord(Strict):
    schema_version: Literal['3.0'] = '3.0'
    id: str
    spec: TaskSpec
    requirements: list[NegotiatedRequirement]
    spec_sha256: str
    evaluator_version: Literal['task-negotiator-v1'] = 'task-negotiator-v1'
    animation_quality_verified: Literal[False] = False
