"""Frozen experiment contracts. Currency is integer microdollars throughout."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, frozen=True)


class Identity(Strict):
    id: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$')


class Complexity(Strict):
    entities: StrictInt = Field(ge=0, le=16)
    occlusion: Literal['none', 'partial', 'full'] = 'none'
    articulation: Literal['simple', 'compound', 'extreme'] = 'simple'
    camera: Literal['fixed', 'moving', 'depth'] = 'fixed'
    topology: Literal['fixed', 'changing'] = 'fixed'
    interaction: Literal['none', 'prop', 'contact', 'multiple'] = 'none'


class Case(Identity):
    family: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$')
    split: Literal['train', 'validation', 'test']
    treatment: str = Field(pattern=r'^t[0-9]{2}$')
    level: StrictInt = Field(ge=0, le=4)
    action: Literal['locomotion', 'acting', 'interaction', 'effects']
    complexity: Complexity
    holds: list[StrictInt] = Field(min_length=1, max_length=24)
    ticks_per_second: StrictInt = Field(default=12, ge=1, le=120)
    loop: bool = True
    challenge_negative: bool = False
    detail: Literal['silhouette', 'moderate', 'dense'] = 'silhouette'
    ancestry: list[str] = Field(default_factory=list)
    request: str = Field(min_length=1, max_length=8000)
    stage: Literal['pilot', 'expansion', 'final']

    @model_validator(mode='after')
    def timing(self):
        if any(h <= 0 for h in self.holds) or sum(self.holds) > 2880:
            raise ValueError('positive bounded authored holds required')
        if self.split == 'test' and self.stage != 'final':
            raise ValueError('test media stays sealed until final evaluation')
        return self


class Limits(Strict):
    successful_images: StrictInt = Field(default=10000, ge=0, le=10000)
    dispatch_attempts: StrictInt = Field(default=10500, ge=0, le=10500)
    repairs: StrictInt = Field(default=2, ge=0, le=2)
    sheets: StrictInt = Field(default=4, ge=1, le=4)
    active_seconds: StrictInt = Field(default=2700, ge=1, le=2700)
    request_timeout: StrictInt = Field(default=180, ge=1, le=180)
    disk_bytes: StrictInt = Field(default=100 * 1024**3, ge=1)
    generation_workers: StrictInt = Field(default=2, ge=1, le=2)
    assessment_workers: StrictInt = Field(default=2, ge=1, le=2)
    modal_workers: StrictInt = Field(default=1, ge=1, le=1)
    modal_seconds: StrictInt = Field(default=3600, ge=1, le=3600)


class Prices(Strict):
    verified_at: str | None = None
    image_microdollars: StrictInt = Field(default=10000, ge=0)
    # Planning rates are never enough to authorize a live request.
    source: str = 'planning-only; verify before funding'


class Campaign(Identity):
    schema_version: Literal['1.0'] = '1.0'
    dataset_version: str = Field(min_length=1)
    phase: Literal['pilot', 'expansion', 'final'] = 'pilot'
    limits: Limits = Field(default_factory=Limits)
    prices: Prices = Field(default_factory=Prices)
    api_ceiling: StrictInt = Field(default=15000000, ge=0, le=125000000)
    modal_ceiling: StrictInt = Field(default=10000000, ge=0, le=100000000)
    seed: StrictInt = 0
    treatments: dict[str,str] = Field(default_factory=lambda: {
        't00':'Flat geometric shapes, restrained palette, clear contour.',
        't01':'Expressive hand ink, bold variable lines, flat color fills.',
        't02':'Soft watercolor surfaces, controlled edge variation.',
        't03':'Crisp pixel drawing, limited palette, readable silhouettes.',
        't04':'Textured fabric and costume detail with stable material identity.',
        't05':'Clean cel shading, compact highlights, consistent palette.',
        't06':'Graphite-like linework with restrained warm color.',
        't07':'Layered cut-paper shapes with stable material texture.'})
    cases: list[Case] = Field(min_length=1, max_length=800)
    frozen_policy_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def splits(self):
        ids = [c.id for c in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError('duplicate case IDs')
        registry = {}
        for c in self.cases:
            if c.treatment not in self.treatments or not self.treatments[c.treatment].strip():
                raise ValueError('case needs a frozen generic style treatment')
            for identity in [c.family, *c.ancestry]:
                if identity in registry and registry[identity] != c.split:
                    raise ValueError('family/reference ancestry crosses splits')
                registry[identity] = c.split
        if self.phase == 'pilot' and sum(c.stage == 'pilot' for c in self.cases) > 80:
            raise ValueError('pilot release exceeds 80 cases')
        if self.phase == 'final' and not self.frozen_policy_sha256:
            raise ValueError('final evaluation requires a frozen policy')
        return self


def canonical(value) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode='json')
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def curriculum(campaign_id='animation-v1') -> Campaign:
    cases = []
    actions = ['locomotion', 'acting', 'interaction', 'effects']
    for treatment in range(8):
        for level in range(5):
            for family_index in range(5):
                split = ['train', 'train', 'train', 'validation', 'test'][family_index]
                family = f't{treatment:02}-c{level}-f{family_index}'
                for action_index, action in enumerate(actions):
                    pilot = family_index in (0, 3) and action_index == (treatment + level + family_index) % 4
                    poses = [6, 6, 12, 12, 24][level]
                    cases.append(Case(id=f'{family}-{action}', family=family, split=split,
                        treatment=f't{treatment:02}', level=level, action=action,
                        complexity=Complexity(entities=2 if level >= 3 else 1,
                            occlusion='partial' if level >= 3 else 'none',
                            articulation='extreme' if level == 4 else 'simple',
                            interaction='prop' if level == 2 else 'contact' if level >= 3 else 'none',
                            topology='changing' if action == 'effects' else 'fixed'),
                        holds=[2] * poses, challenge_negative=(treatment + level + family_index + action_index) % 5 == 0,
                        detail=['silhouette', 'moderate', 'dense'][(treatment + level) % 3],
                        request=f'Create an original isolated {action} sequence, complexity C{level}, treatment t{treatment:02}. '
                                'Respect the declared entity graph, ordered poses and authored timing. No captions or decorative background.',
                        stage='final' if split == 'test' else 'pilot' if pilot else 'expansion'))
    return Campaign(id=campaign_id, dataset_version='1', cases=cases)


def local_path(root: str | Path, relative: str | Path, *, repository: Path | None = None) -> Path:
    root = Path(root).resolve()
    repository = (repository or Path(__file__).resolve().parents[3]).resolve()
    if root == repository or root.is_relative_to(repository):
        raise ValueError('campaign data must be outside the repository')
    path = root / relative
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('path escapes authorized local root (including symlinks)')
    return resolved


def freeze(root, config: Campaign):
    path = local_path(root, f'campaigns/{config.id}/campaign.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(config)
    if path.exists() and path.read_bytes() != raw:
        raise ValueError('campaign config is immutable; use a new dataset/campaign version')
    if not path.exists():
        with path.open('xb') as stream:
            stream.write(raw)
    return {'campaign': config.id, 'sha256': hashlib.sha256(raw).hexdigest(), 'path': str(path)}
