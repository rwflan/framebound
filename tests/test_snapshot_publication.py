"""Independent crash, closure, policy and decoded-batch export receipts."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pytest
from framebound.v2 import storage as S,domain as D
from framebound.v2.exports import build_snapshot,validate_snapshot
from framebound.v2.exports.dpo_adapter import decoded_batch
from framebound.v2.services import packets
from framebound.v2.services.authz import Actor
from test_v2_r5_export import _seed
from test_v2_s6_gates import _fix_flow


def approved_seed(project):
    info=_seed(str(project))
    packets.create_packet(str(project),'test-approval','rev-good',info['ev_good'].artifacts[0]['id'],'test input only')
    packets.record_decision(str(project),Actor(type='reviewer',id='test-reviewer'),
        {'action':'approve','clip_revision_id':'rev-good','packet_id':'test-approval'})
    return info


def test_unrelated_provider_note_never_enters_selected_closure(tmp_path):
    project=tmp_path/'project';approved_seed(project)
    secret=b'unrelated private provider note: never publish this'
    con=S.connect(project)
    try:
        sha=S.store_blob(project,secret)
        S.insert(con,D.Job(id='unrelated',kind='generation',idempotency_key='unrelated',request_brief={},payload_sha256='0'*64,request_artifact=sha))
    finally:con.close()
    out=tmp_path/'snapshot';build_snapshot(str(project),'selected',['rev-good'],str(out))
    assert not (out/'closure'/'blobs'/sha).exists()
    assert all(secret not in path.read_bytes() for path in out.rglob('*') if path.is_file())
    assert (out/'closure'/'jobs.jsonl').read_text()==''


@pytest.mark.parametrize('barrier',['pinned','staged','published','recorded'])
def test_process_death_recovers_immutable_snapshot_and_db_record(tmp_path,barrier):
    project=tmp_path/'project';approved_seed(project);out=tmp_path/'snapshot'
    script="""import os,sys
from framebound.v2.exports import publication as P,build_snapshot
def crash(stage):
 if stage==sys.argv[3]:os._exit(77)
P._checkpoint=crash
build_snapshot(sys.argv[1],'crash',['rev-good'],sys.argv[2],{})
"""
    child=subprocess.run([sys.executable,'-c',script,str(project),str(out),barrier],capture_output=True,text=True)
    assert child.returncode==77,child.stderr
    if barrier in ('pinned','staged'):assert not out.exists()
    else:assert validate_snapshot(str(out))['ok']
    # The source decision changes after the frozen pin. Recovery must preserve
    # the old snapshot, never rebuild under that historical identity.
    packets.record_decision(str(project),Actor(type='reviewer',id='test-reviewer'),
        {'action':'reject','clip_revision_id':'rev-good','note':'post-pin test input'})
    manifest=build_snapshot(str(project),'crash',['rev-good'],str(out))
    assert validate_snapshot(str(out))['ok']
    assert manifest['counts']['positives']==8
    con=S.connect(project)
    try:assert con.execute('SELECT count(*) FROM export_snapshots').fetchone()[0]==1
    finally:con.close()
    assert build_snapshot(str(project),'crash',['rev-good'],str(out))==manifest


@pytest.mark.parametrize('damage',['marker','pixels'])
def test_matching_manifest_cannot_replay_corrupt_or_incomplete_output(tmp_path,damage):
    project=tmp_path/'project';approved_seed(project);out=tmp_path/'snapshot'
    build_snapshot(str(project),'immutable',['rev-good'],str(out))
    if damage=='marker':(out/'COMPLETE').unlink()
    else:next((out/'hf'/'data').glob('*.png')).write_bytes(b'corrupt art')
    with pytest.raises(Exception):build_snapshot(str(project),'immutable',['rev-good'],str(out))
    assert (out/'manifest.json').is_file()  # corrupted evidence is retained


def rehash(out,relative):
    manifest=json.loads((out/'manifest.json').read_text())
    manifest['files'][relative]=hashlib.sha256((out/relative).read_bytes()).hexdigest()
    (out/'manifest.json').write_text(json.dumps(manifest))
    marker=json.loads((out/'COMPLETE').read_text());marker['manifest_sha256']=hashlib.sha256((out/'manifest.json').read_bytes()).hexdigest()
    (out/'COMPLETE').write_text(json.dumps(marker))


def test_moved_provenance_validator_rejects_policy_tamper_even_with_new_file_hashes(tmp_path):
    project=tmp_path/'project';approved_seed(project);out=tmp_path/'snapshot'
    build_snapshot(str(project),'policy',['rev-good'],str(out));out.rename(tmp_path/'moved');out=tmp_path/'moved'
    shutil.move(project,tmp_path/'unavailable-source')
    relative='closure/assets.jsonl';rows=[json.loads(line) for line in (out/relative).read_text().splitlines()]
    next(row for row in rows if row['id']=='f0')['rights']='unknown'
    (out/relative).write_text('\n'.join(json.dumps(r) for r in rows)+'\n');rehash(out,relative)
    verdict=validate_snapshot(str(out))
    assert not verdict['ok'] and any('rights' in issue for issue in verdict['issues']),verdict


def test_moved_snapshot_yields_actual_nonempty_decoded_preference_batch(tmp_path):
    project=tmp_path/'project';approved_seed(project);_fix_flow(str(project));out=tmp_path/'snapshot'
    build_snapshot(str(project),'batch',['rev-good','rev-bad','rev-fix'],str(out),{'include_procedural_positives':True})
    out.rename(tmp_path/'moved');out=tmp_path/'moved';shutil.move(project,tmp_path/'unavailable-source')
    assert validate_snapshot(str(out))['ok']
    batch=decoded_batch(out)
    assert batch['format']=='framebound-preference-v1'
    assert batch['chosen'][0] and batch['rejected'][0]
    assert batch['chosen'][0][0].shape==(64,64,4) and batch['chosen'][0][0].dtype==np.uint8
    assert batch['conditioning'][0]['contract']['canvas']['width']==64
    assert batch['conditioning'][0]['images']['id-art'].shape==(64,64,4)
    pair=json.loads((out/'preferences.jsonl').read_text().splitlines()[0])
    reference=out/pair['chosen'][0]['file'];reference.write_bytes(b'bad')
    with pytest.raises(ValueError,match='hash mismatch'):decoded_batch(out)
