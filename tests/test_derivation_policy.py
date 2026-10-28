import json
from PIL import Image
import pytest
from framebound.v2 import storage as S
from framebound.v2.services import auto_repair as AR,clips,packets
from framebound.v2.services.authz import Actor
from framebound.v2.services.provenance import write_derived,ancestry_in
from framebound.v2.exports import build_snapshot
from framebound.v2 import recorded_run as RR
from test_v2_r5_export import _seed

def test_derivations_keep_unknown_rights_and_conflicting_ids_refuse(tmp_path):
    p=str(tmp_path);_seed(p)
    a=AR.execute_translate(p,'fx-unknown',0,0,'derived',budget_px=2)
    assert a.rights=='unknown'
    assert a.parent_asset_ids==['fx-unknown']
    with pytest.raises(S.ConflictError):AR.execute_translate(p,'fx-unknown',1,0,'derived',budget_px=2)

def test_simulated_ancestry_survives_multiple_operators_and_default_export(tmp_path):
    p=str(tmp_path/'project');_seed(p);con=S.connect(p)
    try:raw=S.blob_path(p,S.get(con,'assets','f0')[0]['byte_sha256']).read_bytes()
    finally:con.close()
    alias=RR._materialize_generated(p,raw,'alias','image/png',64,64,origin='simulated-transport')
    a=AR.execute_translate(p,alias.id,1,0,'moved',budget_px=2)
    b=AR.execute_translate(p,a.id,-1,0,'returned',budget_px=2)
    con=S.connect(p)
    try:assert 'simulated-transport' in ancestry_in(con,b.id)['origins']
    finally:con.close()
    clips.register_candidate(p,'rev-good','derived-rev',{0:b.id},'bounded derivation')
    ev=clips.evaluate(p,'derived-rev');packets.create_packet(p,'pkt','derived-rev',ev.artifacts[0]['id'],'test review')
    packets.record_decision(p,Actor(type='reviewer',id='fixture-reviewer'),{'action':'approve','clip_revision_id':'derived-rev','packet_id':'pkt','expected_evaluation_id':ev.artifacts[0]['id']})
    out=tmp_path/'snapshot';manifest=build_snapshot(p,'selected',['derived-rev'],str(out))
    positives=[json.loads(l) for l in (out/'hf'/'metadata.jsonl').read_text().splitlines()]
    assert b.id not in {r['asset_id'] for r in positives}
    assert manifest['counts']['positives']==7
