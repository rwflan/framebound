"""Localized declared-region checks. No inferred anatomy, action or human judgment."""
import hashlib
import json
import math
import platform
from pathlib import Path
import PIL

import numpy as np

VERSION = 'declared-regions-v2'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def validate_observations(spec):
    regions = {r.id: r for r in spec.region_observations}
    ids = [r.id for r in spec.region_observations] + [r.id for r in spec.temporal_observations]
    if len(ids) != len(set(ids)):
        raise ValueError('observation IDs must be unique')
    n = len(spec.timing.holds)
    for r in regions.values():
        if r.slot >= n or r.roi.right > spec.canvas.width or r.roi.bottom > spec.canvas.height:
            raise ValueError('observation lies outside authored frames/canvas')
    for t in spec.temporal_observations:
        if max(t.left_slot, t.right_slot) >= n or t.left_slot == t.right_slot:
            raise ValueError('temporal observation needs two valid distinct slots')
        if t.family in {'continuity', 'loop'}:
            if t.left_region_id not in regions or t.right_region_id not in regions:
                raise ValueError('temporal localization needs stored region observations')
            if regions[t.left_region_id].slot != t.left_slot or regions[t.right_region_id].slot != t.right_slot:
                raise ValueError('temporal region/slot mismatch')
        if t.family == 'loop' and (not spec.loop or (t.left_slot, t.right_slot) != (n - 1, 0)):
            raise ValueError('loop observation must bind last to first in a looped task')


def supported_families(spec):
    families = {r.family for r in spec.region_observations if r.visibility == 'visible'}
    families.update(t.family for t in spec.temporal_observations)
    return families


def evaluate(spec, images, asset_manifest, presented_holds):
    results = []
    starts = [sum(spec.timing.holds[:i]) for i in range(len(spec.timing.holds))]

    def result(rid, family, slots, outcome, observed, expected, reason, roi=None, source='deterministic'):
        slots = sorted(set(slots))
        results.append(dict(id=rid, family=family, slots=slots,
                            tick_range=[starts[slots[0]], starts[slots[-1]] + spec.timing.holds[slots[-1]]],
                            outcome=outcome, observed=observed, expected=expected, reason=reason,
                            roi=roi, evidence_method=VERSION, source=source, confidence=None))

    arrays = []
    for i, image in enumerate(images):
        if image is None:
            arrays.append(None)
            result(f'media-{i}', 'media', [i], 'error', None, [spec.canvas.width, spec.canvas.height],
                   'Asset is missing, corrupt or unreadable. Re-import the media; do not redraw based on a tool error.')
            continue
        a = np.asarray(image.convert('RGBA'))
        valid = image.size == (spec.canvas.width, spec.canvas.height)
        nonempty = bool(np.any(a[:, :, 3] > 0))
        arrays.append(a if valid and nonempty else None)
        result(f'media-{i}', 'media', [i], 'fail' if not valid else 'pass' if nonempty else 'error',
               {'dimensions': list(image.size), 'foreground_present': nonempty},
               {'dimensions': [spec.canvas.width, spec.canvas.height], 'foreground_present': True},
               'Dimensions must match the native task canvas and visible foreground must be present.')
    result('timing', 'timing', list(range(len(images))),
           'pass' if presented_holds == spec.timing.holds else 'fail', presented_holds, spec.timing.holds,
           'Preserve exact authored frame holds; timing changes require a new task specification.')
    measurements = {}
    for r in spec.region_observations:
        roi = r.roi.model_dump()
        if r.visibility == 'occluded':
            measurements[r.id] = None
            result(r.id, r.family, [r.slot], 'not_applicable', None, [r.minimum, r.maximum],
                   'Task declares this feature occluded; no visible-feature claim is made.', roi, r.source)
            continue
        a = arrays[r.slot]
        if a is None:
            measurements[r.id] = None
            result(r.id, r.family, [r.slot], 'unmeasured', None, [r.minimum, r.maximum],
                   'Native pixels unavailable for this region measurement.', roi, r.source)
            continue
        mask = np.all(a[r.roi.top:r.roi.bottom, r.roi.left:r.roi.right] == r.rgba, axis=2)
        ys, xs = np.nonzero(mask)
        count = len(xs)
        measurements[r.id] = ((float(xs.mean()) + r.roi.left, float(ys.mean()) + r.roi.top) if count else None)
        result(r.id, r.family, [r.slot], 'pass' if r.minimum <= count <= r.maximum else 'fail',
               count, [r.minimum, r.maximum],
               'Exact declared-color pixel count within the task-authored region. This does not establish anatomy or identity outside that region.', roi, r.source)
    for t in spec.temporal_observations:
        slots = [t.left_slot, t.right_slot]
        if any(arrays[s] is None for s in slots):
            outcome, observed = 'unmeasured', None
        elif t.family == 'moving':
            observed = bool(np.array_equal(arrays[t.left_slot], arrays[t.right_slot]))
            outcome = 'fail' if observed else 'pass'
        else:
            points = [measurements.get(t.left_region_id), measurements.get(t.right_region_id)]
            observed = math.dist(*points) if all(p is not None for p in points) else None
            outcome = 'unmeasured' if observed is None else ('pass' if observed <= t.max_distance_px else 'fail')
        result(t.id, t.family, slots, outcome, observed,
               'different drawings' if t.family == 'moving' else [0, t.max_distance_px],
               ('Only this explicitly declared moving interval rejects identical drawings; intentional holds are exempt.'
                if t.family == 'moving' else 'Declared feature-centroid displacement bound; intended motion and camera changes must be encoded in the task regions and bounds.'),
               source=t.source)
    manifest = dict(evaluator=VERSION, evaluator_identity=dict(version=VERSION, source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                    dependencies=dict(python=platform.python_version(),numpy=np.__version__,Pillow=PIL.__version__)), spec=spec.model_dump(mode='json', exclude_unset=True), assets=asset_manifest,
                    presented_holds=presented_holds, results=results)
    return results, manifest, digest(manifest)
