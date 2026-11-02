"""Immutable, globally quarantined reuse of already-paid campaign evidence.

Pooling never releases a failed campaign, changes an assessment, moves a split,
creates provider work or counts frame crops as independent sequences.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile

from PIL import Image

from .assessment import CATEGORIES
from .contracts import Identity, canonical, digest, local_path
from .export import validate
from .leakage import exclusions, POLICY

LANES = ('detection', 'editing', 'preference', 'sequence', 'failure', 'acquisition')


def _rows(path, lane):
    file = path / (lane + '.jsonl')
    return [json.loads(line) for line in file.read_text().splitlines()] if file.exists() else []


def _artifacts(row):
    return [*row['frames'], *row['conditioning'], row['request'],
            *row.get('baseline_frames', []), *row.get('provenance_artifacts', [])]


def _ledger_evidence(root, campaigns):
    """Read only indexed control fields; never load inline request payloads."""
    path = Path(root).resolve() / 'campaigns/lifetime.sqlite3'
    con = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    received = {}; isolated = set()
    try:
        for campaign in campaigns:
            rows = con.execute('SELECT id,campaign,state,receipt FROM requests WHERE campaign=?', (campaign,))
            for rid, name, state, raw in rows:
                if state != 'received' or not raw:
                    continue
                receipt = json.loads(raw)
                original = local_path(root, f"campaigns/{name}/originals/{receipt['sha256']}")
                if not original.is_file() or hashlib.sha256(original.read_bytes()).hexdigest() != receipt['sha256']:
                    raise ValueError('paid source receipt closure differs')
                received[rid] = receipt
        # Include all unknown ancestral identities, not merely their direct family.
        for name, cid, raw in con.execute('SELECT r.campaign,r.case_id,c.config FROM unknown_isolations i JOIN requests r ON r.id=i.request_id JOIN campaigns c ON c.id=r.campaign'):
            case = next(c for c in json.loads(raw)['cases'] if c['id'] == cid)
            isolated.update([case['family'], *case.get('ancestry', [])])
    finally:
        con.close()
    return received, isolated


def _authentic(row, received):
    events = (row.get('provenance', {}).get('provenance') or {}).get('generations', [])
    if not events:
        return False
    for event in events:
        receipt = received.get(event.get('request_id'))
        if event.get('outcome') != 'succeeded' or event.get('provider') != 'meta' or not receipt:
            return False
        provider = receipt.get('provider', {})
        if not isinstance(provider, dict):
            return False
        attribution = ' '.join(str(event.get(k, '')) for k in ('response_id', 'requested_model', 'observed_model')).lower()
        if any(marker in attribution for marker in ('test-only', 'engineering', 'synthetic')):
            return False
        if not event.get('response_id') or event['response_id'] != provider.get('response_id'):
            return False
        if receipt['sha256'] not in event.get('receipt_sha256', []):
            return False
    assessments = [a for a in [row.get('assessment'), *row.get('corroborating_assessments', [])] if a]
    for assessment in assessments:
        provenance = assessment['provenance']
        receipt = received.get(provenance['execution_id'])
        if provenance['provider'] != 'meta' or not receipt or receipt['sha256'] != provenance['raw_sha256']:
            return False
        model = receipt.get('provider', {}).get('requested_model')
        if model and model != provenance['requested_model']:
            return False
    return True


def build(root, sources, *, campaign, version):
    """Freeze explicit campaign/dataset_version/manifest_sha256 sources.

    The source list is an admission manifest, not a mutable 'latest' alias. All
    accepted source receipts must exist in the local lifetime ledger. Returns an
    auditable quarantine/dedup report alongside a standard validated export.
    """
    Identity(id=campaign); Identity(id=version)
    if not sources or len({s['campaign'] for s in sources}) != len(sources):
        raise ValueError('one explicit closed snapshot per source campaign required')
    sources = sorted(sources, key=lambda s: s['campaign'])
    destination = local_path(root, f'campaigns/{campaign}/training/{version}')
    admission = dict(policy='paid-evidence-pool-v1', sources=sources)
    if destination.exists():
        validate(destination)
        report_raw = (destination / 'pool-report.json').read_bytes()
        manifest = json.loads((destination / 'manifest.json').read_text())
        if hashlib.sha256(report_raw).hexdigest() != manifest.get('pool_report_sha256'):
            raise ValueError('pooled audit report hash differs')
        report = json.loads(report_raw)
        if report['admission'] != admission:
            raise ValueError('pooled dataset version is immutable')
        return dict(path=str(destination), report=report)
    received, isolated = _ledger_evidence(root, [s['campaign'] for s in sources])
    destination.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix='.pool-', dir=destination.parent))
    try:
        (work / 'blobs').mkdir()
        lanes = {lane: [] for lane in LANES}; candidates = []; rejected = {}; source_counts = {}
        def copy(artifact, path):
            original = local_path(path, artifact['file'])
            sha = artifact['sha256']
            output = work / 'blobs' / sha; output.parent.mkdir(exist_ok=True)
            if not output.exists():
                raw = original.read_bytes()
                if hashlib.sha256(raw).hexdigest() != sha:
                    raise ValueError('source artifact changed during pooling')
                output.write_bytes(raw)
            return dict(file='blobs/' + sha, sha256=sha)
        for source in sources:
            name = source['campaign']; Identity(id=name); Identity(id=source['dataset_version'])
            path = local_path(root, f"campaigns/{name}/training/{source['dataset_version']}")
            validate(path)
            if hashlib.sha256((path / 'manifest.json').read_bytes()).hexdigest() != source['manifest_sha256']:
                raise ValueError('frozen source manifest differs')
            detection = _rows(path, 'detection'); source_counts[name] = len(detection)
            for lane in LANES:
                for original in _rows(path, lane):
                    row = dict(original); row['id'] = digest([name, original['id']])
                    row['pool_source'] = dict(campaign=name, dataset_version=source['dataset_version'], revision_id=original['id'], manifest_sha256=source['manifest_sha256'])
                    if row.get('baseline_revision_id'):
                        row['baseline_revision_id'] = digest([name, row['baseline_revision_id']])
                    # Keep original sequence identity across campaigns. A second
                    # snapshot or copied specimen never creates new support.
                    row['sequence_id'] = original.get('sequence_id', original['id'])
                    for key in ('frames', 'conditioning', 'baseline_frames', 'provenance_artifacts'):
                        if key in row:
                            row[key] = [copy(a, path) for a in row[key]]
                    row['request'] = copy(row['request'], path)
                    lanes[lane].append(row)
                    if lane == 'detection':
                        reasons = []
                        if isolated.intersection([row['family'], *row.get('ancestry', [])]): reasons.append('isolated unknown family or ancestry')
                        if not _authentic(row, received): reasons.append('no matching received paid generation/assessment closure')
                        if not row.get('rights') or any(r != 'original' for r in row['rights']): reasons.append('non-original or unknown rights')
                        from ..intake import inspect
                        for artifact in row['frames']:
                            with Image.open(work / artifact['file']) as frame:
                                if not inspect(frame)['eligible']:
                                    reasons.append('current strict alpha intake failed'); break
                        if reasons: rejected[row['id']] = reasons
                        candidates.append(dict(metadata=row))
            # Recheck source freeze after copying, catching concurrent replacement.
            if hashlib.sha256((path / 'manifest.json').read_bytes()).hexdigest() != source['manifest_sha256']:
                raise ValueError('source changed during pooling')
        # Quarantine across ALL source rows before removing an invalid member;
        # otherwise removing it could hide its connected split ancestry.
        visual_evidence = []
        cross_split = exclusions(candidates, work, evidence=visual_evidence)
        for rid, reasons in cross_split.items(): rejected.setdefault(rid, []).extend(reasons)
        # Compare decoded RGBA, not only file encodings. Equal timed sequences
        # cannot inflate support; disagreeing scoped labels remain quarantined.
        groups = defaultdict(list)
        for example in candidates:
            row = example['metadata']; pixels = []
            for artifact in row['frames']:
                with Image.open(work / artifact['file']) as frame:
                    rgba = frame.convert('RGBA'); pixels.append([rgba.size, hashlib.sha256(rgba.tobytes()).hexdigest()])
            groups[digest([pixels, row['holds'], row['loop']])].append(row)
        duplicates = {}; conflicts = []
        for members in groups.values():
            if len(members) < 2: continue
            disagreements = any(len({r['labels'][cat]['target'] for r in members if r['labels'][cat]['mask']}) > 1 for cat in CATEGORIES)
            if disagreements:
                ids = sorted(r['id'] for r in members); conflicts.append(ids)
                for rid in ids: rejected.setdefault(rid, []).append('identical timed pixels have conflicting assessed targets')
            else:
                eligible = sorted((r for r in members if r['id'] not in rejected),
                                  key=lambda r: (-sum(label['mask'] for label in r['labels'].values()), r['id']))
                for row in eligible[1:]:
                    duplicates[row['id']] = eligible[0]['id']
                    rejected.setdefault(row['id'], []).append('duplicate decoded timed sequence')
        kept = {e['metadata']['id'] for e in candidates} - rejected.keys()
        # Acquisition failures stay archived in their source snapshot and report;
        # they must never appear as semantic negative examples in this pool.
        lanes['acquisition'] = []
        for lane in LANES:
            lanes[lane] = [r for r in lanes[lane] if r['id'] in kept]
        files = {}
        for lane, rows in lanes.items():
            raw = b''.join(canonical(r) + b'\n' for r in sorted(rows, key=lambda r: r['id']))
            (work / (lane + '.jsonl')).write_bytes(raw); files[lane + '.jsonl'] = hashlib.sha256(raw).hexdigest()
        report = dict(admission=admission, source_rows=source_counts, candidate_records=len(candidates), retained_records=len(kept),
                      excluded_records=rejected, duplicate_representatives=duplicates, conflicting_sequences=conflicts,
                      isolated_identities=sorted(isolated), split_quarantine_policy=POLICY,
                      confirmed_visual_links=[v for v in visual_evidence if v['confirmed']],
                      authority='advisory_only; no stage release, training readiness or artistic acceptance inferred')
        manifest = dict(schema_version='animation-training-2.0', dataset_version=version, files=files,
                        counts={lane: len(rows) for lane, rows in lanes.items()}, categories=CATEGORIES,
                        generator_training_status='pooled paid evidence; actual support gates still required', pooling_admission_sha256=digest(admission),
                        pool_report_sha256=hashlib.sha256(canonical(report)).hexdigest())
        (work / 'manifest.json').write_bytes(canonical(manifest)); (work / 'pool-report.json').write_bytes(canonical(report))
        validate(work)
        # Copy only referenced closure into the final dataset; excluded raw
        # artifacts remain preserved in their immutable source snapshots.
        used = {a['sha256'] for rows in lanes.values() for row in rows for a in _artifacts(row)}
        for blob in (work / 'blobs').iterdir():
            if blob.name not in used: blob.unlink()
        work.rename(destination)
        return dict(path=str(destination), report=report)
    finally:
        if work.exists(): shutil.rmtree(work)
