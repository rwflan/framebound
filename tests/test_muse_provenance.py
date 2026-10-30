import copy
import json

import pytest
from pydantic import ValidationError

from framebound.v2 import storage as S
from framebound.v2.services.errors import InvalidInput
from framebound.v3 import provenance as P
from framebound.v3.services import loop, tasks
from test_agent_loop import setup, import_frames


def metadata(project, aids, *, model='muse-spark-1.3'):
    con = S.connect(project)
    try:
        hashes = [S.get(con, 'assets', aid)[0]['byte_sha256'] for aid in aids]
    finally:
        con.close()
    return {'provenance': dict(parent=dict(provider='meta', requested_model=model,
        harness='Muse Code', harness_version='1.4.13', contributor_requested='on'),
        generations=[dict(id='base', provider='meta', requested_model='muse-image-1.0',
            outcome='succeeded', prompt_sha256='a'*64, original_output_sha256=hashes,
            output_asset_ids=aids)])}


def test_unknown_history_typed_claims_and_parent_timeline_keep_budget(tmp_path):
    project, _, good = setup(tmp_path)
    bad = import_frames(tmp_path, 'bad', {'kind':'flicker'})
    first = loop.submit(project, 'run', 'old', bad)
    assert first['provenance'] is None
    claim = metadata(project, good)
    loop.submit(project, 'run', 'new', good, parent_revision_id='old', feedback_id=first['id'], generation_metadata=claim)
    revision = loop.revision_get(project, 'new')['revision']
    assert revision['generation_metadata'] == claim
    assert P.parse(claim).parent.contributor_effective == 'unknown'
    assert P.parse(claim).generations[0].observed_model is None
    assert loop.get(project, 'run')['remaining_submissions'] == 6
    con = loop.connect(project)
    events = [json.loads(r['data']) for r in con.execute('SELECT data FROM agent_run_events')]
    con.close()
    assert len([e for e in events if e['event']=='parent_changed']) == 1
    assert loop.revision_get(project, 'old')['revision']['generation_metadata'] is None
    assert loop.revision_get(project, 'new')['feedback']['provenance']['parent']['requested_model'] == 'muse-spark-1.3'


@pytest.mark.parametrize('mutation, match', [
    (lambda p: p['generations'][0].update(evidence_source='provider_response'), 'durable provider job'),
    (lambda p: p['generations'][0].update(original_output_sha256=['f'*64]), 'provenance blob'),
    (lambda p: p['generations'][0].update(edit_parent_event_id='invented'), 'edit parent'),
    (lambda p: p['generations'][0].update(output_asset_ids=['other']), 'bound to this revision'),
])
def test_claim_cannot_invent_local_evidence_or_outputs(tmp_path, mutation, match):
    project, _, good = setup(tmp_path)
    claim = metadata(project, good)
    mutation(claim['provenance'])
    with pytest.raises(InvalidInput, match=match):
        loop.submit(project, 'run', 'rejected', good, generation_metadata=claim)
    assert loop.get(project, 'run')['submission_ids'] == []


def test_research_only_conditioning_and_forged_parent_authority_rejected(tmp_path):
    project, _, good = setup(tmp_path)
    claim = metadata(project, good)
    claim['provenance']['parent']['evidence_source'] = 'provider_response'
    with pytest.raises(ValidationError): P.parse(claim)
    claim = metadata(project, good)
    claim['provenance']['generations'][0]['conditioning'] = [dict(asset_id=good[0], byte_sha256='a'*64,
        role='style', conditioning_eligibility='research_only', eligibility_basis='publisher screenshot')]
    with pytest.raises(ValidationError, match='explicit original or cleared'): P.parse(claim)


def test_frozen_input_hash_and_style_board_binding(tmp_path):
    project, spec, good = setup(tmp_path)
    spec = dict(spec, id='bound', animation_id='bound', inputs=[dict(asset_id=good[0], role='identity',
        provenance='test', designated_by='test', basis='test', byte_sha256='a'*64)])
    with pytest.raises(InvalidInput, match='input hash'): tasks.create(project, spec)
    claim = metadata(project, good)
    claim['provenance']['style_board'] = dict(id='x', name='Not the task board', content_sha256='a'*64)
    with pytest.raises(InvalidInput, match='style board'): loop.submit(project, 'run', 'wrong', good, generation_metadata=claim)
