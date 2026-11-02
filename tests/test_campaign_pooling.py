"""Pooling reuses closed evidence without changing its labels or split gates."""
import hashlib
import json

from PIL import Image, ImageDraw
import pytest

from framebound.v3.campaign import pooling
from framebound.v3.campaign.contracts import canonical
from framebound.v3.campaign.export import build, validate


def source(root, name, *, family=None, split='train', color='red', shape='circle', ancestry=()):
    image = Image.new('RGBA', (64, 64)); draw = ImageDraw.Draw(image)
    if shape == 'circle': draw.ellipse((18, 12, 43, 50), fill=color)
    else: draw.rectangle((20, 12, 39, 50), fill=color)
    image.save(root / (name + '.png')); (root / (name + '.request')).write_bytes(b'actual frozen request')
    event = dict(provider='meta', outcome='succeeded', request_id=name, response_id='resp-' + name, receipt_sha256=[name + '-sha'])
    example = dict(id='revision', family=family or name, ancestry=list(ancestry), split=split, frames=[name + '.png'],
                   holds=[2], loop=True, request_file=name + '.request', conditioning_files=[], rights=['original'],
                   provenance={'provenance': {'generations': [event]}}, sequence_id='case-' + name)
    result = build(root, name, [example], version='closed')
    path = __import__('pathlib').Path(result['path'])
    return dict(campaign=name, dataset_version='closed', manifest_sha256=hashlib.sha256((path / 'manifest.json').read_bytes()).hexdigest())


def receipts(*names):
    return {n: dict(sha256=n + '-sha', provider={'response_id': 'resp-' + n}) for n in names}


def test_pool_deduplicates_decoded_sequences_and_replays_immutably(tmp_path, monkeypatch):
    sources = [source(tmp_path, n) for n in ('a', 'b')]
    before = [(tmp_path / 'campaigns' / s['campaign'] / 'training/closed/manifest.json').read_bytes() for s in sources]
    monkeypatch.setattr(pooling, '_ledger_evidence', lambda *_: (receipts('a', 'b'), set()))
    result = pooling.build(tmp_path, sources, campaign='combined', version='one')
    assert result['report']['retained_records'] == 1
    assert len(result['report']['duplicate_representatives']) == 1
    assert validate(result['path'])['counts']['detection'] == 1
    assert pooling.build(tmp_path, sources, campaign='combined', version='one') == result
    for s, original in zip(sources, before):
        assert (tmp_path / 'campaigns' / s['campaign'] / 'training/closed/manifest.json').read_bytes() == original
    with pytest.raises(ValueError, match='immutable'):
        pooling.build(tmp_path, sources[:1], campaign='combined', version='one')


@pytest.mark.parametrize('basis', ['same_pixels', 'family', 'ancestry'])
def test_pool_quarantines_global_split_connections(tmp_path, monkeypatch, basis):
    a = source(tmp_path, 'a')
    b = source(tmp_path, 'b', split='validation', family='a' if basis == 'family' else 'b',
               ancestry=['a'] if basis == 'ancestry' else [], color='red' if basis == 'same_pixels' else 'blue',
               shape='circle' if basis == 'same_pixels' else 'square')
    monkeypatch.setattr(pooling, '_ledger_evidence', lambda *_: (receipts('a', 'b'), set()))
    result = pooling.build(tmp_path, [a, b], campaign='combined', version='one')
    assert result['report']['retained_records'] == 0
    assert len(result['report']['excluded_records']) == 2
    assert validate(result['path'])['ok']


def test_pool_excludes_unknown_ancestry_and_unreceived_artifacts(tmp_path, monkeypatch):
    sources = [source(tmp_path, 'a', ancestry=['unknown']), source(tmp_path, 'b', color='blue', shape='square')]
    monkeypatch.setattr(pooling, '_ledger_evidence', lambda *_: (receipts('a'), {'unknown'}))
    result = pooling.build(tmp_path, sources, campaign='combined', version='one')
    reasons = list(result['report']['excluded_records'].values())
    assert any('isolated unknown family or ancestry' in r for r in reasons)
    assert any('no matching received paid generation/assessment closure' in r for r in reasons)
    assert result['report']['retained_records'] == 0


def test_pool_rejects_changed_source_freeze(tmp_path, monkeypatch):
    frozen = source(tmp_path, 'a'); frozen['manifest_sha256'] = '0' * 64
    monkeypatch.setattr(pooling, '_ledger_evidence', lambda *_: (receipts('a'), set()))
    with pytest.raises(ValueError, match='frozen source manifest'):
        pooling.build(tmp_path, [frozen], campaign='combined', version='one')
    assert not (tmp_path / 'campaigns/combined/training/one').exists()


def test_pool_audit_report_is_hash_bound(tmp_path, monkeypatch):
    frozen = source(tmp_path, 'a')
    monkeypatch.setattr(pooling, '_ledger_evidence', lambda *_: (receipts('a'), set()))
    result = pooling.build(tmp_path, [frozen], campaign='combined', version='one')
    path = __import__('pathlib').Path(result['path']) / 'pool-report.json'
    report = json.loads(path.read_text()); report['retained_records'] = 999; path.write_bytes(canonical(report))
    with pytest.raises(ValueError, match='report hash'):
        pooling.build(tmp_path, [frozen], campaign='combined', version='one')


def test_matching_assessment_requires_its_own_received_execution():
    row = dict(provenance={'provenance': {'generations': [dict(provider='meta', outcome='succeeded', request_id='image', response_id='resp-image', receipt_sha256=['image-sha'])]}},
               assessment={'provenance': dict(provider='meta', execution_id='teacher', raw_sha256='teacher-sha', requested_model='muse-spark-1.3')})
    received = receipts('image')
    assert not pooling._authentic(row, received)
    received['teacher'] = dict(sha256='teacher-sha', provider={'requested_model': 'muse-spark-1.3'})
    assert pooling._authentic(row, received)
    received['teacher']['provider']['requested_model'] = 'synthetic-test-model'
    assert not pooling._authentic(row, received)


def test_conflicting_assessed_targets_are_quarantined_not_selected(tmp_path, monkeypatch):
    from framebound.v3.campaign.assessment import Assessment, Binding, Provenance, abstention
    sources = []
    received = receipts('a', 'b')
    for name, positive in [('a', True), ('b', False)]:
        frozen = source(tmp_path, name)
        folder = tmp_path / 'campaigns' / name / 'training/closed'
        row = json.loads((folder / 'detection.jsonl').read_text())
        provenance = Provenance(provider='meta', requested_model='muse-spark-1.3', rubric_sha256='b' * 64,
                                raw_sha256=('c' if positive else 'd') * 64, execution_id='teacher-' + name)
        assessment = abstention(Binding(**{k: 'a' * 64 for k in Binding.model_fields}), provenance, [0], 'Scoped test fixture').model_dump(mode='json')
        assessment['coverage'][0].update(status='present' if positive else 'absent_within_assessed_scope', slots=[0])
        if positive:
            assessment['findings'] = [dict(id='identity', category='identity', slots=[0], tick_range=[0, 2], subject='Actor',
                severity='material', visibility='supported', observed='Different identity', expected='Frozen identity', counterexamples='Motion excluded')]
        assessment = Assessment.model_validate(assessment)
        row.update(assessment=assessment.model_dump(mode='json'), labels=assessment.targets())
        raw = canonical(row) + b'\n'; (folder / 'detection.jsonl').write_bytes(raw)
        manifest = json.loads((folder / 'manifest.json').read_text()); manifest['files']['detection.jsonl'] = hashlib.sha256(raw).hexdigest()
        (folder / 'manifest.json').write_bytes(canonical(manifest)); frozen['manifest_sha256'] = hashlib.sha256(canonical(manifest)).hexdigest()
        sources.append(frozen)
        received['teacher-' + name] = dict(sha256=provenance.raw_sha256, provider={'requested_model': 'muse-spark-1.3'})
    monkeypatch.setattr(pooling, '_ledger_evidence', lambda *_: (received, set()))
    result = pooling.build(tmp_path, sources, campaign='combined', version='one')
    assert result['report']['retained_records'] == 0
    assert len(result['report']['conflicting_sequences']) == 1
    assert not result['report']['duplicate_representatives']


def test_ledger_audit_is_read_only_and_excludes_unknown_ancestry(tmp_path):
    import sqlite3
    campaigns = tmp_path / 'campaigns'; originals = campaigns / 'paid/originals'; originals.mkdir(parents=True)
    raw = b'actual retained provider bytes'; sha = hashlib.sha256(raw).hexdigest(); (originals / sha).write_bytes(raw)
    path = campaigns / 'lifetime.sqlite3'; con = sqlite3.connect(path)
    con.executescript('CREATE TABLE requests(id TEXT,campaign TEXT,case_id TEXT,state TEXT,receipt TEXT); CREATE TABLE campaigns(id TEXT,config TEXT); CREATE TABLE unknown_isolations(request_id TEXT);')
    receipt = dict(sha256=sha, provider={'response_id': 'resp-real'})
    con.execute('INSERT INTO requests VALUES(?,?,?,?,?)', ('received', 'paid', 'one', 'received', json.dumps(receipt)))
    con.execute('INSERT INTO requests VALUES(?,?,?,?,?)', ('unknown', 'other', 'two', 'unknown', None))
    con.execute('INSERT INTO campaigns VALUES(?,?)', ('other', json.dumps(dict(cases=[dict(id='two', family='excluded', ancestry=['parent'])]))))
    con.execute('INSERT INTO unknown_isolations VALUES(?)', ('unknown',)); con.commit(); con.close()
    before = path.read_bytes()
    received, isolated = pooling._ledger_evidence(tmp_path, ['paid'])
    assert received == {'received': receipt}
    assert isolated == {'excluded', 'parent'}
    assert path.read_bytes() == before
    (originals / sha).write_bytes(b'altered')
    with pytest.raises(ValueError, match='receipt closure'):
        pooling._ledger_evidence(tmp_path, ['paid'])


def test_empty_closed_snapshot_stays_empty_not_negative_supervision(tmp_path, monkeypatch):
    result = build(tmp_path, 'empty', [], version='closed')
    path = __import__('pathlib').Path(result['path'])
    frozen = dict(campaign='empty', dataset_version='closed', manifest_sha256=hashlib.sha256((path/'manifest.json').read_bytes()).hexdigest())
    monkeypatch.setattr(pooling, '_ledger_evidence', lambda *_: ({}, set()))
    pooled = pooling.build(tmp_path, [frozen], campaign='combined', version='one')
    assert pooled['report']['retained_records'] == pooled['report']['candidate_records'] == 0
    assert all(n == 0 for n in validate(pooled['path'])['counts'].values())
