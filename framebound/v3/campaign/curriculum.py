"""Versioned isolated-subject curriculum; legacy experiments remain unchanged."""
from collections import Counter
from typing import Literal

from pydantic import Field, model_validator

from .contracts import Campaign, Case, Complexity, digest


class MVPCase(Case):
    action: Literal['locomotion', 'acting', 'interaction', 'turn']
    subject: Literal['character', 'animal', 'figure', 'object']
    exercise: str = Field(min_length=1, max_length=1000)
    legitimate_counterexample: str = Field(min_length=1, max_length=1000)
    target_categories: list[Literal['temporal', 'artifacts', 'identity', 'parts', 'prop', 'contact', 'action_order']] = Field(min_length=1)

    @model_validator(mode='after')
    def isolated(self):
        if self.complexity.entities != 1 or self.complexity.camera != 'fixed' or self.complexity.topology != 'fixed':
            raise ValueError('MVP requires one isolated subject, fixed camera and topology')
        return self


class MVPCampaign(Campaign):
    schema_version: Literal['2.0'] = '2.0'
    dataset_version: Literal['mvp-2'] = 'mvp-2'
    cases: list[MVPCase] = Field(min_length=1, max_length=800)

    @model_validator(mode='after')
    def protocol(self):
        if self.phase != 'pilot':
            raise ValueError('v2 releases advance through the ledger, never by rewriting the campaign')
        if Counter(c.split for c in self.cases) != dict(train=480, validation=160, test=160):
            raise ValueError('MVP protocol freezes 480 train, 160 validation and 160 final specifications')
        if len({c.family for c in self.cases}) != 200:
            raise ValueError('MVP protocol requires 200 independent family specifications')
        if sum(c.stage == 'pilot' for c in self.cases) != 80:
            raise ValueError('MVP pilot requires exactly 80 specifications')
        for family in {c.family for c in self.cases}:
            group = [c for c in self.cases if c.family == family]
            if len(group) != 4 or len({c.subject for c in group}) != 1:
                raise ValueError('each family requires four exercises for one consistent subject')
        return self


def mvp_curriculum(campaign_id='animation-mvp-v2-keyed'):
    cases = []
    actions = ('locomotion', 'acting', 'interaction', 'turn')
    exercises = (
        ('Move through ordered poses with stable support.', 'An authored held drawing is not a missing in-between.', ['temporal', 'contact']),
        ('Anticipate, react and settle while preserving identity.', 'Intentional squash-and-stretch is not identity drift.', ['identity', 'parts']),
        ('Manipulate one held prop without a scene or second actor.', 'Self-occlusion is not a missing part or dropped prop.', ['prop', 'contact']),
        ('Turn and return with consistent parts and loop closure.', 'An intentional smear is not canvas corruption.', ['temporal', 'artifacts']),
    )
    for treatment in range(8):
        for level in range(5):
            for family_index, split in enumerate(('train', 'train', 'train', 'validation', 'test')):
                family = f'mvp2-t{treatment:02}-c{level}-f{family_index}'
                subject = ('character', 'animal', 'figure', 'object')[(treatment + family_index) % 4]
                for index, action in enumerate(actions):
                    exercise, counterexample, categories = exercises[index]
                    pilot = family_index in (0, 3) and index == (treatment + level + family_index) % 4
                    poses = (6, 6, 12, 12, 24)[level]
                    cases.append(MVPCase(
                        id=f'{family}-{action}', family=family, split=split, treatment=f't{treatment:02}',
                        level=level, action=action, subject=subject, exercise=exercise,
                        legitimate_counterexample=counterexample, target_categories=categories,
                        complexity=Complexity(entities=1, occlusion='partial' if level >= 3 else 'none',
                            articulation=('simple' if level < 2 else 'compound' if level < 4 else 'extreme'),
                            interaction='prop' if action == 'interaction' else 'none'),
                        holds=[2] * poses, challenge_negative=index != (treatment + level) % 4,
                        detail=('silhouette', 'moderate', 'dense')[(treatment + level) % 3],
                        request=f'Animate one original isolated 2D {subject}. {exercise} Complexity C{level}. '
                            'Use genuine transparent surroundings, one fixed native canvas and the declared timing. '
                            'No matte, paper background, checkerboard, scenery, captions, effects-only sequence or second actor. '
                            f'Legitimate animation to distinguish from defects: {counterexample} '
                            'DECLARED EXTRACTION KEY: render perfectly uniform pure RGB(255,0,255) magenta surroundings '
                            'including enclosed gaps, with no magenta in the subject, no shadows and generous margins. '
                            'Local declared-key extraction will produce genuine alpha; do not draw a transparency checkerboard.',
                        stage='final' if split == 'test' else 'pilot' if pilot else 'expansion'))
    return MVPCampaign(id=campaign_id, cases=cases)


def protocol(config):
    """Selections depend only on frozen specifications, never observed success."""
    pilot = [c for c in config.cases if c.stage == 'pilot']
    simple = sorted((c for c in pilot if len(c.holds) == 6), key=lambda c: digest([config.seed, 'rehearsal', c.id]))
    # Round-robin across treatments to avoid a rehearsal concentrated in one style.
    rehearsal = []
    for round_index in range(2):
        for treatment in sorted(config.treatments):
            group = [c for c in simple if c.treatment == treatment]
            if len(group) > round_index and len(rehearsal) < 12:
                rehearsal.append(group[round_index].id)
    return dict(schema_version='mvp-protocol-2.0', config_sha256=digest(config),
                rehearsal=rehearsal, pilot=[c.id for c in pilot],
                expansion=[c.id for c in config.cases if c.stage == 'expansion'],
                final=[c.id for c in config.cases if c.split == 'test'],
                initial_categories=['temporal', 'artifacts'],
                knowledge_mode='advisory; no automatic repair or acceptance authority')
