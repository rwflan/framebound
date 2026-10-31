"""Bounded semantic labels; omission never means absence."""
from __future__ import annotations

from typing import Literal
from pydantic import Field, StrictInt, model_validator

from .contracts import Strict, digest

CATEGORIES = ('identity', 'parts', 'prop', 'entities', 'contact', 'temporal', 'action_order', 'artifacts', 'extraction')
Category = Literal['identity','parts','prop','entities','contact','temporal','action_order','artifacts','extraction']
Status = Literal['present','absent_within_assessed_scope','uncertain','not_assessed']


class Binding(Strict):
    request_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    revision_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    timing_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    evaluation_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class Provenance(Strict):
    provider: str = Field(min_length=1,max_length=128)
    requested_model: str = Field(min_length=1,max_length=128)
    observed_model: str | None = Field(default=None,max_length=128)
    observed_version: str | None = Field(default=None,max_length=128)
    rubric_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    raw_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    execution_id: str = Field(min_length=1,max_length=128)


class Finding(Strict):
    id: str = Field(min_length=1,max_length=96)
    category: Category
    slots: list[StrictInt] = Field(min_length=1,max_length=24)
    tick_range: tuple[StrictInt,StrictInt]
    subject: str = Field(min_length=1,max_length=128)
    part: str | None = Field(default=None,max_length=128)
    severity: Literal['minor','material','critical']
    confidence: float | None = Field(default=None,ge=0,le=1)
    confidence_calibration: str | None = Field(default=None,max_length=128)
    observed: str = Field(min_length=1,max_length=2000)
    expected: str = Field(min_length=1,max_length=2000)
    counterexamples: str = Field(min_length=1,max_length=1000)
    roi: tuple[StrictInt,StrictInt,StrictInt,StrictInt] | None = None
    visibility: Literal['supported','uncertain','occluded'] = 'uncertain'


class Coverage(Strict):
    category: Category
    status: Status
    slots: list[StrictInt] = Field(default_factory=list,max_length=24)
    limitations: str = Field(min_length=1,max_length=2000)


class Assessment(Strict):
    schema_version: Literal['1.0'] = '1.0'
    binding: Binding
    provenance: Provenance
    coverage: list[Coverage] = Field(min_length=9,max_length=9)
    findings: list[Finding] = Field(default_factory=list,max_length=64)

    @model_validator(mode='after')
    def complete_taxonomy(self):
        if {c.category for c in self.coverage} != set(CATEGORIES):
            raise ValueError('every taxonomy category needs explicit coverage')
        if len({f.id for f in self.findings}) != len(self.findings):
            raise ValueError('duplicate finding IDs')
        covered = {c.category:c for c in self.coverage}
        for f in self.findings:
            c = covered[f.category]
            if c.status != 'present' or not set(f.slots).issubset(c.slots):
                raise ValueError('finding is outside explicitly present scope')
        if any(c.status == 'present' and not any(f.category == c.category for f in self.findings) for c in self.coverage):
            raise ValueError('positive coverage requires observed findings')
        return self

    def validate_evidence(self, binding: Binding, holds: list[int], canvas: tuple[int,int]):
        if self.binding != binding:
            raise ValueError('stale request/revision/timing/evaluation binding')
        ends = [0]
        for h in holds:
            if type(h) is not int or h <= 0:
                raise ValueError('invalid authored timing')
            ends.append(ends[-1]+h)
        for c in self.coverage:
            if len(set(c.slots)) != len(c.slots) or any(s < 0 or s >= len(holds) for s in c.slots):
                raise ValueError('coverage slot is not a native frame')
            if c.status in {'present','absent_within_assessed_scope'} and not c.slots:
                raise ValueError('positive/negative labels require an assessed native scope')
        for f in self.findings:
            if not 0 <= f.tick_range[0] < f.tick_range[1] <= ends[-1]:
                raise ValueError('finding tick range exceeds native timing')
            if any(ends[s] >= f.tick_range[1] or ends[s+1] <= f.tick_range[0] for s in f.slots):
                raise ValueError('finding slots do not overlap evidence time')
            if f.roi:
                x0,y0,x1,y1 = f.roi
                if not 0 <= x0 < x1 <= canvas[0] or not 0 <= y0 < y1 <= canvas[1]:
                    raise ValueError('nonexistent native ROI')
        return self

    def targets(self):
        """Sequence labels and masks, separately from teacher probabilities."""
        return {c.category: dict(target=1 if c.status=='present' else 0,
            mask=c.status in {'present','absent_within_assessed_scope'}, slots=c.slots,
            source='model', calibration=None) for c in self.coverage}


def temporal_windows(holds, *, loop, width=3):
    if not holds or any(type(h) is not int or h <= 0 for h in holds) or width < 1:
        raise ValueError('positive authored holds/window required')
    ticks = [0]
    for h in holds: ticks.append(ticks[-1]+h)
    windows = []
    for start in range(len(holds)):
        slots = [(start+i)%len(holds) for i in range(min(width,len(holds)))] if loop else list(range(start,min(len(holds),start+width)))
        windows.append(dict(slots=slots, holds=[holds[s] for s in slots],
            native_tick_ranges=[[ticks[s],ticks[s+1]] for s in slots], loop_boundary=any(b<a for a,b in zip(slots,slots[1:]))))
    return windows


def parse_assessment(raw: bytes, *, binding, holds, canvas):
    if len(raw) > 128*1024:
        raise ValueError('teacher response exceeds bounded schema output')
    result = Assessment.model_validate_json(raw)
    import hashlib
    # raw_sha256 is attached by the trusted adapter, not echoed by the model.
    return result.validate_evidence(binding,holds,canvas)


def abstention(binding, provenance, slots, reason):
    return Assessment(binding=binding,provenance=provenance,coverage=[Coverage(category=c,status='not_assessed',slots=slots,limitations=reason) for c in CATEGORIES])


DIAGNOSIS_RUBRIC = (
    'Inspect actual ordered native frames and authored timing, including loop windows. '
    'Return only the supplied Assessment JSON schema. Requested checks are not observations. '
    'Cover every category explicitly; abstain on unsupported anatomy, occlusion, smears or topology. '
    'Findings need localized observations, expected behavior and legitimate counterexamples. '
    'A format-valid clip is not a semantic pass. Confidence is uncalibrated unless a calibration artifact is supplied.'
)
COMPARISON_RUBRIC = (
    'Independently inspect timed sequences A and B using the frozen creative request. '
    'Neither order nor recency indicates quality. Return A, B, tie or insufficient_evidence. '
    'Judge target improvement and preservation/action regressions separately. '
    'Do not prefer a candidate merely because a diagnosis proposed it.'
)
