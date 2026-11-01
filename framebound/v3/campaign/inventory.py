"""Local evidence inventory. Never calls providers or upgrades historical labels."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from .assessment import Assessment, CATEGORIES
from .contracts import canonical, digest, local_path, parse_campaign
from .intelligence import training_labels


def inspect(root, campaign=None):
    from .ledger import Ledger
    ledger = Ledger(root)
    with ledger.db() as db:
        configs = [parse_campaign(json.loads(r['config'])) for r in db.execute('SELECT config FROM campaigns ORDER BY id')]
    if campaign:
        configs = [c for c in configs if c.id == campaign]
        if not configs:
            raise ValueError('unknown campaign')
    reports = []
    for config in configs:
        status = ledger.status(config.id)
        strata = defaultdict(Counter)
        coverage = {c: Counter() for c in CATEGORIES}
        label_sources = Counter()
        defects = Counter()
        usable = set()
        assessment_errors = []
        # Scope means assessed categories, never whole-clip or artistic acceptance.
        for path in sorted(local_path(root, f'campaigns/{config.id}/annotations').glob('*.json')):
            if path.name.endswith(('-quarantine.json', '-normalization.json')):
                continue
            try:
                a = Assessment.model_validate_json(path.read_bytes())
                label_sources[a.provenance.provider] += 1
                for c in a.coverage:
                    coverage[c.category][c.status] += 1
                    if c.status in {'present', 'absent_within_assessed_scope'} and c.slots:
                        usable.add(a.binding.revision_sha256)
                defects.update(f.category for f in a.findings)
            except (ValueError, OSError):
                assessment_errors.append(path.name)
        terminal = Counter()
        intake = Counter()
        evidence_hashes = []
        for case in config.cases:
            p = ledger.progress(config.id, case.id)
            stratum = ':'.join((case.split, getattr(case, 'subject', 'undeclared'), case.treatment, case.action, f'C{case.level}'))
            strata[stratum][p['state']] += 1
            if p['result']:
                terminal[p['result'].get('outcome', p['state'])] += 1
                evidence_hashes.append(digest([case.id, p['result']]))
                for i in p['result'].get('intake', []):
                    intake['eligible' if i['eligible'] else 'rejected'] += 1
        receipt_errors = []
        for r in status['requests']:
            if r['state'] == 'received':
                try:
                    ledger.artifact(r['id'])
                except (ValueError, OSError):
                    receipt_errors.append(r['id'])
        exports = []
        from .export import load
        for manifest in sorted(local_path(root, f'campaigns/{config.id}/training').glob('*/manifest.json')):
            try:
                examples = load(manifest.parent)
                from .leakage import exclusions
                split_exclusions=exclusions(examples,manifest.parent)
                labeled = Counter()
                intake_counts=Counter()
                rights=Counter()
                from ..intake import inspect as inspect_intake
                pixel_families = defaultdict(set)
                for e in examples:
                    eligible=all(inspect_intake(frame)['eligible'] for frame in e['frames'])
                    intake_counts['eligible' if eligible else 'rejected']+=1
                    rights.update(e['metadata'].get('rights',['unknown']))
                    labels, weights = training_labels(e['metadata'])
                    for c in CATEGORIES:
                        if labels[c]['mask']:
                            labeled[c + (':positive' if labels[c]['target'] else ':negative')] += 1
                            if weights[c] < .9:
                                labeled[c + ':weak'] += 1
                    for frame in e['metadata']['frames']:
                        pixel_families[frame['sha256']].add(e['metadata']['split'])
                exports.append(dict(version=manifest.parent.name, valid=True, sequences=len(examples),
                                    families=len({e['metadata']['family'] for e in examples}), labels=dict(labeled),split_exclusions=len(split_exclusions),intake=dict(intake_counts),rights=dict(rights),
                                    exact_pixel_split_conflicts=sum(len(v) > 1 for v in pixel_families.values())))
            except (ValueError, OSError, KeyError):
                exports.append(dict(version=manifest.parent.name, valid=False))
        reports.append(dict(campaign=config.id, config_sha256=digest(config), schema_version=config.schema_version,
            specifications=len(config.cases), families=len({c.family for c in config.cases}),
            released_results=sum(terminal.values()), terminal_outcomes=dict(terminal), strata={k: dict(v) for k, v in strata.items()},
            scoped_assessed_revisions=len(usable), category_coverage={k: dict(v) for k, v in coverage.items()},
            finding_categories=dict(defects), model_label_sources=dict(label_sources), intake=dict(intake),
            assessment_errors=assessment_errors, receipt_errors=receipt_errors, exports=exports,
            budgets=status['budgets'], stopped=status['stopped'],
            unknown_requests=sum(r['state'] in {'wire_started', 'unknown_provider_outcome'} for r in status['requests']),
            evidence_sha256=digest(sorted(evidence_hashes)),
            limitations=['Historical model labels are not independently authenticated ground truth.',
                         'Undeclared subject, rights and quality coverage remain unknown.',
                         'No valid closed export means training support is not established.']))
    report = dict(schema_version='knowledge-inventory-1.0', campaigns=reports, model_calls=0,
                  remote_bytes_transferred=0, human_acceptance=False)
    folder = local_path(root, 'knowledge/inventories')
    folder.mkdir(parents=True, exist_ok=True)
    raw = canonical(report)
    path = folder / (hashlib.sha256(raw).hexdigest() + '.json')
    if not path.exists():
        path.write_bytes(raw)
    return dict(report=report, path=str(path))
