from framebound.v3.campaign.assessment import Finding,Assessment,Binding,Provenance,abstention
from framebound.v3.campaign.corroboration import compare,audit


def finding(**updates):
    d=dict(id='one',category='parts',slots=[0],tick_range=[0,2],subject='Actor A',part='left hand',severity='material',visibility='supported',
        observed='Visible detached hand',expected='Connected hand',counterexamples='Occlusion excluded',roi=[0,0,4,4])
    d.update(updates);return Finding(**d)


def test_formatting_normalization_preserves_identity_and_scope():
    a=finding()
    assert compare(a,finding(subject=' actor   A '))['matched']
    for updates,reason in [({'subject':'Actor B'},'subject_identity_unresolved'),({'part':'right hand'},'part_identity_differs'),
        ({'slots':[0,1]},'slot_scope_differs'),({'roi':[0,0,5,5]},'spatial_scope_differs'),({'tick_range':[2,4]},'time_scope_disjoint')]:
        assert reason in compare(a,finding(**updates))['reasons']


def test_later_corroborated_target_is_not_hidden_by_first_disagreement():
    binding=Binding(**{k:'a'*64 for k in Binding.model_fields})
    p=Provenance(provider='engineering',requested_model='test',rubric_sha256='b'*64,raw_sha256='c'*64,execution_id='one')
    a=abstention(binding,p,[0],'Synthetic test').model_dump()
    a['coverage'][1].update(status='present',slots=[0]);a['findings']=[finding(id='first',subject='Other actor').model_dump(),finding(id='second').model_dump()]
    a=Assessment.model_validate(a)
    b=a.model_copy(update={'findings':[finding(id='independent')], 'provenance':p.model_copy(update={'execution_id':'two','rubric_sha256':'d'*64})})
    assert audit(a,b)['eligible_finding_ids']==['second']
    assert not audit(a,b.model_copy(update={'binding':binding.model_copy(update={'request_sha256':'e'*64})}))['eligible_finding_ids']


def test_explicit_canvas_identity_handles_names_without_aliasing_actors():
    a=finding(category='artifacts',subject='frame',subject_id='scene_canvas',part=None)
    b=finding(category='artifacts',subject='whole composition',subject_id='scene_canvas',part=None)
    assert compare(a,b)['matched']
    assert not compare(a,b.model_copy(update={'subject_id':None}))['matched']
    assert not compare(a,b.model_copy(update={'slots':[1]}))['matched']
