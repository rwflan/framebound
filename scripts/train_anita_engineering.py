"""Train and evaluate bounded engineering detectors on the Anita feature shard."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from framebound.v3.campaign.assessment import CATEGORIES
from framebound.v3.campaign.contracts import canonical
from framebound.v3.campaign.learning import eligibility, experiment, predict
from framebound.v3.campaign.transfer import inspect_payload


def _score_one(artifact, rows, category):
    index = CATEGORIES.index(category)
    return [
        (predict(artifact, row)['scores'][category], row.targets[index])
        for row in rows
        if row.assessed[index]
    ]


def _metrics(scored, threshold):
    tp = sum(score >= threshold and target == 1 for score, target in scored)
    fp = sum(score >= threshold and target == 0 for score, target in scored)
    fn = sum(score < threshold and target == 1 for score, target in scored)
    tn = sum(score < threshold and target == 0 for score, target in scored)
    positives = tp + fn
    negatives = fp + tn
    return dict(
        threshold=threshold,
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        true_negatives=tn,
        precision=tp / (tp + fp) if tp + fp else None,
        recall=tp / positives if positives else None,
        false_positive_rate=fp / negatives if negatives else None,
        balanced_accuracy=((tp / positives if positives else 0.0) +
                           (tn / negatives if negatives else 0.0)) / 2,
    )


def _auroc(scored):
    positives = [score for score, target in scored if target == 1]
    negatives = [score for score, target in scored if target == 0]
    if not positives or not negatives:
        return None
    wins = 0.0
    for positive in positives:
        wins += sum(positive > negative for negative in negatives)
        wins += 0.5 * sum(positive == negative for negative in negatives)
    return wins / (len(positives) * len(negatives))


def _best_threshold(scored):
    thresholds = sorted({0.0, 1.0, *(score for score, _ in scored)})
    candidates = [_metrics(scored, threshold) for threshold in thresholds]
    return max(
        candidates,
        key=lambda item: (
            item['balanced_accuracy'],
            item['recall'] or 0,
            item['precision'] or 0,
            -item['threshold'],
        ),
    )


def evaluate(card, model_dir, shard):
    validation = [row for row in shard.rows if row.split == 'validation']
    test = [row for row in shard.rows if row.split == 'test']
    candidates = []
    for result in card['results']:
        path = model_dir / f"{result['model']}-{result['seed']}.json"
        artifact = json.loads(path.read_text())
        evaluation = {}
        validation_balanced = []
        test_balanced = []
        for category in artifact['categories']:
            selected = _best_threshold(_score_one(artifact, validation, category))
            scored = _score_one(artifact, test, category)
            measured = _metrics(scored, selected['threshold'])
            evaluation[category] = dict(
                validation=selected,
                test=dict(measured, auroc=_auroc(scored)),
            )
            validation_balanced.append(selected['balanced_accuracy'])
            test_balanced.append(measured['balanced_accuracy'])
        candidates.append(dict(
            model=result['model'],
            seed=result['seed'],
            checkpoint=str(path),
            checkpoint_sha256=result['sha256'],
            mean_validation_balanced_accuracy=float(np.mean(validation_balanced)),
            mean_test_balanced_accuracy=float(np.mean(test_balanced)),
            categories=evaluation,
        ))
    chosen = max(candidates, key=lambda item: item['mean_validation_balanced_accuracy'])
    control = {}
    for category in chosen['categories']:
        index = CATEGORIES.index(category)
        scored = [
            (0.0, row.targets[index])
            for row in test
            if row.assessed[index]
        ]
        control[category] = dict(
            policy='accept every provider output without detection',
            test=dict(_metrics(scored, 0.5), auroc=_auroc(scored)),
        )
    return dict(
        schema_version='anita-engineering-benchmark-v1',
        split='scene-family grouped; thresholds selected on validation only',
        selected=chosen,
        candidates=candidates,
        control=control,
        conclusion=(
            'Framework is better on this controlled engineering benchmark when '
            'mean test balanced accuracy exceeds the pass-all control. This is '
            'not evidence of arbitrary artistic quality or human acceptance.'
        ),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--features', required=True)
    parser.add_argument('--private-root', required=True)
    parser.add_argument('--version', required=True)
    args = parser.parse_args()
    shard = inspect_payload(Path(args.features).read_bytes())
    categories = ['artifacts']
    gate = eligibility(shard, categories)
    if not gate['eligible']:
        raise SystemExit(json.dumps(gate, indent=2))
    result = experiment(
        args.private_root,
        'anita-engineering',
        shard,
        categories=categories,
    )
    model_dir = Path(result['path'])
    benchmark = evaluate(result['card'], model_dir, shard)
    benchmark['version'] = args.version
    report_path = model_dir / 'benchmark.json'
    report_path.write_bytes(canonical(benchmark))
    print(json.dumps(dict(
        gate=gate,
        model_card=str(model_dir / 'model-card.json'),
        benchmark=str(report_path),
        selected=benchmark['selected'],
        control=benchmark['control'],
    ), indent=2))


if __name__ == '__main__':
    main()
