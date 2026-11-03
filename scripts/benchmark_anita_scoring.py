"""Benchmark reference-bound phase scoring against base raw-output acceptance."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from framebound.v3 import evaluate as base_evaluate
from framebound.v3 import visual_score
from framebound.v3.campaign.anita import (
    FRAME_COUNT,
    _load_window,
    _normalize,
    _split,
    _starts,
    _usable,
    discover,
)
from framebound.v3.campaign.contracts import canonical
from framebound.v3.domain import TaskSpec

TEMPORAL_ORDERS = (
    ('middle-swap', (0, 2, 1, 3, 4, 5)),
    ('delayed-interior', (0, 2, 3, 4, 1, 5)),
    ('reversed', (5, 4, 3, 2, 1, 0)),
)


def _windows(root, split, native_size):
    output = []
    for scene in _split(discover(root)):
        if scene['split'] != split:
            continue
        for layer, frames in scene['series'].items():
            for start in _starts(dict(scene, frames=frames), 10):
                images = _load_window(scene, layer, start)
                if images is None:
                    continue
                images = _normalize(images, native_size)
                if images is None or not _usable(images):
                    continue
                output.append(dict(
                    family=scene['family'],
                    layer=layer,
                    start=start,
                    images=images,
                ))
    return output


def _spec(images, *, similarity, margin):
    asset_ids = [f'phase-{index}' for index in range(FRAME_COUNT)]
    observations = [
        dict(
            id=f'phase-{index}',
            kind='phase',
            slot=index,
            roi=dict(left=0, top=0, right=images[0].width, bottom=images[0].height),
            reference_asset_id=asset_ids[index],
            competing_asset_ids=[item for item in asset_ids if item != asset_ids[index]],
            minimum_similarity=similarity,
            minimum_margin=margin,
            provenance='Actual source phase from the same animation window',
            source='procedural',
        )
        for index in range(FRAME_COUNT)
    ]
    return TaskSpec.model_validate(dict(
        id='anita-phase-order',
        project_id='anita-benchmark',
        animation_id='anita-phase-order',
        intent='Retain the source-bound order of six actual animation phases.',
        subjects='One isolated hand-authored source subject per scene.',
        canvas=dict(width=images[0].width, height=images[0].height),
        timing=dict(ticks_per_second=10, holds=[1] * FRAME_COUNT),
        inputs=[
            dict(
                asset_id=asset_id,
                role='known_good_animation',
                provenance='Actual source phase',
                designated_by='frozen Anita benchmark window',
                basis='Original scene-layer phase at this slot',
            )
            for asset_id in asset_ids
        ],
        visual_observations=observations,
    ))


def _detected(results):
    return any(result['outcome'] == 'fail' for result in results)


def _evaluate_window(window, *, similarity, margin):
    images = window['images']
    spec = _spec(images, similarity=similarity, margin=margin)
    asset_ids = [f'phase-{index}' for index in range(FRAME_COUNT)]
    references = dict(zip(asset_ids, images))
    clean_visual = _detected(visual_score.evaluate(spec, images, references))
    base_clean, _, _ = base_evaluate.evaluate(
        spec,
        images,
        [{}] * FRAME_COUNT,
        spec.timing.holds,
    )
    variants = {}
    for name, order in TEMPORAL_ORDERS:
        candidate = [images[index] for index in order]
        base, _, _ = base_evaluate.evaluate(
            spec,
            candidate,
            [{}] * FRAME_COUNT,
            spec.timing.holds,
        )
        variants[name] = dict(
            visual=_detected(visual_score.evaluate(spec, candidate, references)),
            base=_detected(base),
        )
    return dict(
        visual_false_positive=clean_visual,
        base_false_positive=_detected(base_clean),
        variants=variants,
    )


def _metrics(results):
    clean = len(results)
    positives = clean * len(TEMPORAL_ORDERS)
    visual_false_positives = sum(item['visual_false_positive'] for item in results)
    base_false_positives = sum(item['base_false_positive'] for item in results)
    visual_true_positives = sum(
        variant['visual']
        for item in results
        for variant in item['variants'].values()
    )
    base_true_positives = sum(
        variant['base']
        for item in results
        for variant in item['variants'].values()
    )
    return dict(
        clean_cases=clean,
        corruption_variants=positives,
        base=dict(
            false_positives=base_false_positives,
            true_positives=base_true_positives,
            false_positive_rate=base_false_positives / clean if clean else None,
            recall=base_true_positives / positives if positives else None,
            balanced_accuracy=(
                (clean - base_false_positives) / clean
                + base_true_positives / positives
            ) / 2 if clean and positives else None,
        ),
        visual_score=dict(
            false_positives=visual_false_positives,
            true_positives=visual_true_positives,
            false_positive_rate=visual_false_positives / clean if clean else None,
            recall=visual_true_positives / positives if positives else None,
            balanced_accuracy=(
                (clean - visual_false_positives) / clean
                + visual_true_positives / positives
            ) / 2 if clean and positives else None,
        ),
        by_variant={
            name: dict(
                base_detected=sum(item['variants'][name]['base'] for item in results),
                visual_detected=sum(item['variants'][name]['visual'] for item in results),
                cases=clean,
            )
            for name, _ in TEMPORAL_ORDERS
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--native-size', type=int, default=128)
    args = parser.parse_args()
    validation = _windows(args.source, 'validation', args.native_size)
    test = _windows(args.source, 'test', args.native_size)
    grid = []
    for margin in (0.001, 0.005, 0.01):
        measured = _metrics([
            _evaluate_window(window, similarity=0.75, margin=margin)
            for window in validation
        ])
        grid.append(dict(similarity=0.75, margin=margin, validation=measured))
    selected = max(
        grid,
        key=lambda item: item['validation']['visual_score']['balanced_accuracy'],
    )
    test_results = [
        _evaluate_window(
            window,
            similarity=selected['similarity'],
            margin=selected['margin'],
        )
        for window in test
    ]
    report = dict(
        schema_version='anita-reference-score-benchmark-v1',
        source='https://github.com/zhenglinpan/AnitaDataset',
        split='validation-selected config; untouched scene-family test arm',
        native_size=args.native_size,
        selected=dict(
            similarity=selected['similarity'],
            margin=selected['margin'],
            validation=selected['validation'],
        ),
        validation_grid=grid,
        test=_metrics(test_results),
        methodology=(
            'Actual transparent color/sketch layers, frozen six-phase windows, '
            'and three deterministic order corruptions. Base evaluation accepts '
            'the raw sequence without phase references. Reference-bound scoring '
            'uses the original six phase pixels as known-good animation inputs.'
        ),
        limitation=(
            'This is an engineering phase-order benchmark. It does not establish '
            'artistic quality, anatomical correctness, or human acceptance.'
        ),
    )
    path = Path(args.output).resolve()
    repository = Path(__file__).resolve().parents[1]
    if path.is_relative_to(repository):
        raise ValueError('benchmark output must stay outside the repository')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(report))
    print(json.dumps(dict(path=str(path), selected=report['selected'], test=report['test']), indent=2))


if __name__ == '__main__':
    main()
