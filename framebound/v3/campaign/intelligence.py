"""Shared per-category supervision policy. Agreement is scoped model evidence."""
from .assessment import Assessment, CATEGORIES


def training_labels(metadata):
    labels = {c: dict(metadata['labels'][c]) for c in CATEGORIES}
    weights = {c: .5 for c in CATEGORIES}
    assessments = [Assessment.model_validate(a) for a in metadata.get('corroborating_assessments', [])]
    for category in CATEGORIES:
        observed = [(a, a.targets()[category]) for a in assessments]
        # A teacher pair must agree on the category and the actual native scope.
        # Agreement in an unrelated category never upgrades this target's weight.
        votes = [(a, t) for a, t in observed if t['mask']]
        base = labels[category]
        if any(t['target'] != base['target'] or set(t['slots']) != set(base['slots']) for _,t in votes):
            labels[category]['mask'] = False
        independent = [(a,t) for a,t in votes if a.binding == assessments[0].binding] if assessments else []
        if (labels[category]['mask'] and len({a.provenance.execution_id for a,_ in independent})>=2
                and len({a.provenance.rubric_sha256 for a,_ in independent})>=2):
            if not base['target']:
                weights[category]=1.
            else:
                from .corroboration import audit
                if any(any(t['category']==category and t['matched'] for t in audit(a,b)['targets'])
                       for a,_ in independent for b,_ in independent if a is not b):
                    weights[category]=1.
        if labels[category]['target'] == 0 and set(labels[category]['slots']) != set(range(len(metadata['holds']))):
            labels[category]['mask'] = False
    return labels, weights
