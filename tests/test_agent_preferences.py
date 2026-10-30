import json

import pytest
from framebound.v2.services.authz import Actor
from framebound.v2.services.errors import AuthorizationError,InvalidInput
from framebound.v2.exports import build_snapshot,validate_snapshot
from framebound.v2.exports.agent_reader import load_preferences
from framebound.v3.services import loop,interventions as I
from test_agent_loop import setup,import_frames


def test_explicit_human_preference_is_portable_and_never_inferred_from_revision_order(tmp_path):
    project,_,good=setup(tmp_path);bad=import_frames(tmp_path,'bad',{'kind':'flicker'})
    failed=loop.submit(project,'run','bad',bad)
    loop.submit(project,'run','fixed',good,parent_revision_id='bad',feedback_id=failed['id'])
    body=dict(id='prefer-fixed',revision_id='fixed',evaluation_id='evaluation:fixed',action='approve',
              comparison_revision_id='bad',comparison_evaluation_id='evaluation:bad',note='Explicitly preferred clear costume to flicker.')
    with pytest.raises(AuthorizationError):I.decision(project,Actor(type='orchestrator',id='agent'),'run',body)
    human=Actor(type='reviewer',id='human');decision=I.decision(project,human,'run',body)
    assert I.decision(project,human,'run',body)==decision
    out=tmp_path/'snapshot';manifest=build_snapshot(project,'preference',['fixed'],str(out),{'include_procedural_positives':True})
    assert manifest['counts']['preferences']==1
    pairs=load_preferences(out)
    assert len(pairs)==1 and len(pairs[0]['chosen'])==len(pairs[0]['rejected'])==3
    assert pairs[0]['metadata']['source']=='human_comparison'
    assert pairs[0]['metadata']['chosen_revision_id']=='fixed'
    assert pairs[0]['task']['id']=='task'
    assert validate_snapshot(str(out))['ok']
    # A newer ordinary decision supersedes preference eligibility rather than fabricating a new comparison.
    I.decision(project,human,'run',dict(id='later-needs-changes',revision_id='fixed',evaluation_id='evaluation:fixed',action='needs_changes'))
    newer=build_snapshot(project,'withheld-preference',['fixed'],str(tmp_path/'newer'),{'include_procedural_positives':True})
    assert newer['counts']['preferences']==newer['counts']['positives']==0


def test_comparison_cannot_bind_the_wrong_evaluation_or_same_revision(tmp_path):
    project,_,good=setup(tmp_path);bad=import_frames(tmp_path,'bad',{'kind':'flicker'})
    failed=loop.submit(project,'run','bad',bad);loop.submit(project,'run','fixed',good,parent_revision_id='bad',feedback_id=failed['id'])
    human=Actor(type='reviewer',id='human')
    with pytest.raises(InvalidInput):I.decision(project,human,'run',dict(id='invalid',revision_id='fixed',evaluation_id='evaluation:fixed',action='approve',comparison_revision_id='bad',comparison_evaluation_id='evaluation:fixed'))
    con=loop.connect(project)
    assert con.execute('SELECT count(*) FROM agent_preferences').fetchone()[0]==0
    assert not I.approved_in(con,'run','fixed','evaluation:fixed')
    con.close()
