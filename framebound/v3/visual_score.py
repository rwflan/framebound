"""Declared, reference-bound animation measurements. No inferred anatomy or approval."""
import numpy as np

VERSION = 'declared-visual-score-v1'


def reference_ids(spec):
    return sorted({aid for item in spec.visual_observations
                   for aid in ([item.reference_asset_id] if item.reference_asset_id else []) + item.competing_asset_ids})


def validate(spec):
    ids = [item.id for item in spec.visual_observations]
    if len(ids) != len(set(ids)):
        raise ValueError('visual observation IDs must be unique')
    for item in spec.visual_observations:
        if item.slot >= len(spec.timing.holds) or item.roi.right > spec.canvas.width or item.roi.bottom > spec.canvas.height:
            raise ValueError('visual observation lies outside authored frames/canvas')
        if item.kind == 'contact_span' and item.minimum_span_px > item.roi.right - item.roi.left:
            raise ValueError('contact span exceeds declared window width')
    bound = {i.asset_id for i in spec.inputs if i.role == 'known_good_animation'}
    for aid in reference_ids(spec):
        if aid not in bound:
            raise ValueError(f'visual reference {aid} needs a known_good_animation input binding')


def _mask(image, roi):
    if image is None or image.size[0] < roi.right or image.size[1] < roi.bottom:
        return None
    return np.asarray(image.convert('RGBA'))[roi.top:roi.bottom, roi.left:roi.right, 3] > 0


def _signature(mask):
    # A coarse occupancy grid preserves large pose changes while reducing pixel jitter.
    y_edges = np.linspace(0, mask.shape[0], 9).astype(int)
    x_edges = np.linspace(0, mask.shape[1], 9).astype(int)
    return np.array([mask[y_edges[y]:y_edges[y+1], x_edges[x]:x_edges[x+1]].mean()
                     if y_edges[y+1] > y_edges[y] and x_edges[x+1] > x_edges[x] else 0
                     for y in range(8) for x in range(8)], dtype=float)


def _similarity(left, right):
    a, b = _signature(left), _signature(right)
    denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b / denominator) if denominator else 0.0


def _span(mask):
    longest = 0
    for row in mask:
        padded = np.pad(row.astype(np.int8), (1, 1))
        edges = np.diff(padded)
        starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
        if len(starts):
            longest = max(longest, int(np.max(ends - starts)))
    return longest


def evaluate(spec, images, references):
    starts = [sum(spec.timing.holds[:i]) for i in range(len(spec.timing.holds))]
    results = []
    for item in spec.visual_observations:
        roi = item.roi.model_dump()
        observed = None
        expected = None
        reason = ''
        if item.visibility == 'occluded':
            outcome = 'not_applicable'
            reason = 'Declared occluded; no visible-pixel quality claim.'
        else:
            candidate = _mask(images[item.slot], item.roi)
            reference = _mask(references.get(item.reference_asset_id), item.roi) if item.reference_asset_id else None
            competitors = [_mask(references.get(aid), item.roi) for aid in item.competing_asset_ids]
            if candidate is None or (item.kind != 'contact_span' and (reference is None or any(x is None for x in competitors))):
                outcome = 'unmeasured'
                reason = 'Native candidate or frozen reference pixels are unavailable.'
            elif item.kind == 'phase' and (not reference.any() or any(not x.any() for x in competitors)):
                outcome = 'unmeasured'
                reason = 'A declared phase reference has no visible alpha in the comparison window.'
            elif item.kind == 'contact_span':
                observed = _span(candidate)
                expected = {'minimum_contiguous_px': item.minimum_span_px}
                outcome = 'pass' if observed >= item.minimum_span_px else 'fail'
                reason = 'Longest contiguous alpha run in a declared visible support window; support identity remains unverified.'
            elif item.kind == 'phase':
                target = _similarity(candidate, reference)
                rivals = {aid: _similarity(candidate, mask) for aid, mask in zip(item.competing_asset_ids, competitors)}
                best_rival = max(rivals.values())
                observed = {'target_similarity': target, 'competing_similarity': rivals, 'margin': target - best_rival}
                expected = {'minimum_similarity': item.minimum_similarity, 'minimum_margin': item.minimum_margin}
                outcome = 'pass' if target >= item.minimum_similarity and target - best_rival >= item.minimum_margin else 'fail'
                reason = 'Coarse alpha occupancy must match the declared phase better than competing phases; semantic action remains unverified.'
            else:
                reference_area = int(reference.sum())
                if reference_area == 0:
                    outcome = 'unmeasured'
                    reason = 'Declared same-pose reference has no foreground in the window.'
                else:
                    ratio = float(candidate.sum() / reference_area)
                    union = np.logical_or(candidate, reference).sum()
                    iou = float(np.logical_and(candidate, reference).sum() / union) if union else 0.0
                    observed = {'area_ratio': ratio, 'alpha_iou': iou}
                    expected = {'area_ratio': [item.minimum_area_ratio, item.maximum_area_ratio],
                                'minimum_similarity': item.minimum_similarity}
                    outcome = 'pass' if item.minimum_area_ratio <= ratio <= item.maximum_area_ratio and iou >= item.minimum_similarity else 'fail'
                    reason = 'Declared same-pose, same-view region area and overlap; changed views or occlusion need a different contract.'
        results.append(dict(id=item.id, family=item.kind, slots=[item.slot],
                            tick_range=[starts[item.slot], starts[item.slot] + spec.timing.holds[item.slot]],
                            outcome=outcome, observed=observed, expected=expected, reason=reason,
                            roi=roi, evidence_method=VERSION, source=item.source, confidence=None,
                            reference_asset_id=item.reference_asset_id, competing_asset_ids=item.competing_asset_ids))
    return results
