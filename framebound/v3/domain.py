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
    max_measurement_pixels: StrictInt = Field(default=67108864,ge=1,le=268435456)
    max_evaluation_pixels: StrictInt = Field(default=16777216, ge=1, le=67108864)
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
    profile: Literal['structural-v1', 'fixed-subject-v1', 'tracked-scene-v1'] = 'structural-v1'
    region_observations: list['RegionObservation'] = Field(default_factory=list, max_length=4096)
    temporal_observations: list['TemporalObservation'] = Field(default_factory=list, max_length=4096)
    source_correspondence: 'SourceCorrespondence | None' = None
    scene: 'SceneSpec | None' = None
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
    evaluator_version: Literal['task-negotiator-v1', 'task-negotiator-v2'] = 'task-negotiator-v2'
    animation_quality_verified: Literal[False] = False


class RegionObservation(Strict):
    """A task-authored measurement, not a generated annotation or reviewer decision."""
    id: str = Field(min_length=1, max_length=128)
    family: Literal['feature', 'appearance', 'contact']
    slot: StrictInt = Field(ge=0)
    roi: 'Roi'
    rgba: list[StrictInt] = Field(min_length=4, max_length=4)
    minimum: StrictInt = Field(default=1, ge=0)
    maximum: StrictInt = Field(ge=0)
    visibility: Literal['visible', 'occluded'] = 'visible'
    provenance: str = Field(min_length=1, max_length=2000)
    source: Literal['user_declared', 'agent_proposed', 'model_proposed', 'procedural']

    @model_validator(mode='after')
    def valid_observation(self):
        if any(c < 0 or c > 255 for c in self.rgba) or self.minimum > self.maximum:
            raise ValueError('invalid color or count interval')
        return self


class TemporalObservation(Strict):
    id: str = Field(min_length=1, max_length=128)
    family: Literal['continuity', 'moving', 'loop']
    left_slot: StrictInt = Field(ge=0)
    right_slot: StrictInt = Field(ge=0)
    left_region_id: str | None = None
    right_region_id: str | None = None
    max_distance_px: float = Field(default=0, ge=0, allow_inf_nan=False)
    provenance: str = Field(min_length=1, max_length=2000)
    source: Literal['user_declared', 'agent_proposed', 'model_proposed', 'procedural']


class TimeAnchor(Strict):
    source_tick: StrictInt = Field(ge=0)
    output_tick: StrictInt = Field(ge=0)


class SourceKey(Strict):
    source_tick: StrictInt = Field(ge=0)
    output_tick: StrictInt = Field(ge=0)
    preservation: Literal['exact_pixels', 'alpha_geometry']
    roi: 'Roi | None' = None


class SourceCorrespondence(Strict):
    frame_asset_ids: list[str] = Field(min_length=1, max_length=512)
    timing: Timing
    loop: bool
    designated_by: str = Field(min_length=1, max_length=200)
    designation_basis: str = Field(min_length=1, max_length=2000)
    provenance: str = Field(min_length=1, max_length=2000)
    source_revision_id: str | None = Field(default=None, min_length=1, max_length=128)
    goal: Literal['detail_enhancement', 'interpolation', 'enhancement_and_interpolation']
    time_map: list[TimeAnchor] = Field(min_length=2, max_length=1024)
    protected_keys: list[SourceKey] = Field(min_length=1, max_length=512)
    preserve_duration: Literal[True] = True
    limitation: str = Field(default='Source fidelity checks establish only the declared pixel/alpha anchors and authored time map; fluidity and unmeasured motion remain judgment.',max_length=2000)

    @model_validator(mode='after')
    def valid_source(self):
        if len(self.frame_asset_ids)!=len(self.timing.holds):
            raise ValueError('source frame count must match its frozen authored holds')
        for a,b in zip(self.time_map,self.time_map[1:]):
            if a.source_tick>=b.source_tick or a.output_tick>=b.output_tick:
                raise ValueError('source/output time map must be strictly increasing')
        if self.time_map[0].source_tick!=0 or self.time_map[0].output_tick!=0:
            raise ValueError('time map must begin at both authored origins')
        if self.time_map[-1].source_tick!=self.timing.total_ticks():
            raise ValueError('time map must cover the complete source duration')
        return self


class CameraObservation(Strict):
    slot: StrictInt = Field(ge=0)
    translation: tuple[float, float]
    scale: float = Field(gt=0, le=100, allow_inf_nan=False)
    provenance: str = Field(min_length=1, max_length=2000)
    source: Literal['user_declared', 'agent_proposed', 'model_proposed', 'procedural']


class TrackedFeature(Strict):
    id: str = Field(min_length=1, max_length=128)
    subject_id: str = Field(min_length=1, max_length=128)
    slot: StrictInt = Field(ge=0)
    roi: 'Roi'
    rgba: list[StrictInt] = Field(min_length=4,max_length=4)
    expected_world: tuple[float, float]
    max_error_world: float = Field(ge=0, allow_inf_nan=False)
    minimum_pixels: StrictInt = Field(default=1,ge=1)
    maximum_pixels: StrictInt = Field(ge=1)
    visibility: Literal['visible','occluded','ambiguous'] = 'visible'
    provenance: str = Field(min_length=1, max_length=2000)
    source: Literal['user_declared', 'agent_proposed', 'model_proposed', 'procedural']


class TrackLink(Strict):
    id: str = Field(min_length=1,max_length=128)
    left_feature_id: str
    right_feature_id: str
    max_displacement_world: float = Field(ge=0,allow_inf_nan=False)
    required: bool = True


class SceneEvent(Strict):
    id: str = Field(min_length=1,max_length=128)
    kind: Literal['contact','separation','left_of','above']
    left_feature_id: str
    right_feature_id: str
    distance_world: float = Field(default=0,ge=0,allow_inf_nan=False)
    required: bool = True
    provenance: str = Field(min_length=1,max_length=2000)
    source: Literal['user_declared', 'agent_proposed', 'model_proposed', 'procedural']


class SceneSpec(Strict):
    subjects: list[str] = Field(min_length=1,max_length=16)
    camera: list[CameraObservation] = Field(min_length=1,max_length=512)
    features: list[TrackedFeature] = Field(min_length=1,max_length=8192)
    links: list[TrackLink] = Field(default_factory=list,max_length=8192)
    events: list[SceneEvent] = Field(default_factory=list,max_length=8192)
    method: Literal['declared-color-camera-tracks-v1'] = 'declared-color-camera-tracks-v1'
    limitation: str = Field(default='Only declared exact-color features, uniform 2D camera transforms and landmark events are measured. Occluded geometry, perspective, anatomy, physical forces and arbitrary prose action correctness are unsupported.',max_length=2000)


from ..v2.domain import Roi
RegionObservation.model_rebuild()
TrackedFeature.model_rebuild()
SceneSpec.model_rebuild()
SourceKey.model_rebuild()
SourceCorrespondence.model_rebuild()

TaskSpec.model_rebuild()
TaskRecord.model_rebuild()
