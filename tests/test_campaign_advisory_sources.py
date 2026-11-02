"""Private pooled advice stays source-bound, scoped and outside final freeze."""
import hashlib
import json

from PIL import Image, ImageDraw
import pytest

from framebound.v3.campaign import advisory, export, knowledge, study
from framebound.v3.campaign.assessment import Binding, Provenance, abstention
from framebound.v3.campaign.contracts import canonical, digest


def library(root, campaign='source', *, ancestry=()):
    image=Image.new('RGBA',(64,64));ImageDraw.Draw(image).ellipse((20,12,42,50),fill='red');image.save(root/'frame.png')
    (root/'request.json').write_text('{}')
    assessment=abstention(Binding(**{k:'a'*64 for k in Binding.model_fields}),
        Provenance(provider='engineering',requested_model='test',rubric_sha256='b'*64,raw_sha256='c'*64,execution_id='test'),[0],'Synthetic scoped fixture').model_dump(mode='json')
    assessment['coverage'][0].update(status='absent_within_assessed_scope',slots=[0])
    example=dict(id='revision',family='source-family',ancestry=list(ancestry),split='train',rights=['original'],frames=['frame.png'],holds=[2],loop=True,
        request_file='request.json',conditioning_files=[],provenance={'source':'engineering fixture'},assessment=assessment)
    export.build(root,campaign,[example],version='closed')
    result=knowledge.build(root,campaign,version='library',dataset_version='closed')
    return __import__('pathlib').Path(result['path'])


def test_cross_source_is_explicit_bound_and_retrievable(tmp_path):
    path=library(tmp_path)
    selected=advisory.select(tmp_path,'target',dict(knowledge_campaign='source',knowledge_version='library'))
    value=advisory.get_selection(tmp_path,'target')
    assert value['knowledge_campaign']=='source'
    assert value['knowledge_sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    result=advisory.query(tmp_path,'target',[],[],loop=False,family='new-family',categories=['identity'])
    assert len(result['entries'])==1 and result['authority']=='advisory_only'
    assert result['selection_sha256']==digest(selected['report'])
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError,match='bytes changed'):
        advisory.query(tmp_path,'target',[],[],loop=False,family='new-family',categories=['identity'])


def test_omitted_source_keeps_legacy_selection_bytes(tmp_path):
    path=library(tmp_path,'own')
    advisory.select(tmp_path,'own',dict(knowledge_version='library'))
    expected=dict(schema_version='animation-advisory-1.0',campaign='own',knowledge_version='library',model_file=None,
        model_sha256=None,knowledge_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),calibration=None,authority='advisory_only',promoted=False)
    assert (tmp_path/'campaigns/own/advisory/current.json').read_bytes()==canonical(expected)


@pytest.mark.parametrize('ancestry,target,isolated', [(['shared'],['shared'],set()), (['blocked'],[],{'blocked'}), ([],['source-family'],set())])
def test_cross_source_excludes_source_target_and_unknown_ancestry(tmp_path,monkeypatch,ancestry,target,isolated):
    library(tmp_path,ancestry=ancestry)
    advisory.select(tmp_path,'target',dict(knowledge_campaign='source',knowledge_version='library'))
    monkeypatch.setattr(advisory,'_isolated_lineage',lambda _:isolated)
    result=advisory.query(tmp_path,'target',[],[],loop=False,family='different',ancestry=target,categories=['identity'])
    assert result['entries']==[]


def test_cross_source_cannot_silently_enter_old_final_schema(tmp_path):
    library(tmp_path)
    advisory.select(tmp_path,'target',dict(knowledge_campaign='source',knowledge_version='library'))
    with pytest.raises(ValueError,match='before final freeze'):
        study.final_evidence(tmp_path,'target',{})
    with pytest.raises(ValueError,match='before final freeze'):
        advisory.get_selection(tmp_path,'target',final=True)
    with pytest.raises(ValueError,match='before final freeze'):
        study.final_evidence(tmp_path,'other',{'knowledge_campaign':'source'})


def test_cross_source_rejects_rehashed_fabricated_observation(tmp_path):
    path=library(tmp_path);value=json.loads(path.read_text());entry=value['entries'][0]
    entry['observed']='Fabricated defect';entry['id']=digest({k:v for k,v in entry.items() if k!='id'});path.write_bytes(canonical(value))
    with pytest.raises(ValueError,match='beyond its scope'):
        advisory.select(tmp_path,'target',dict(knowledge_campaign='source',knowledge_version='library'))


def test_cross_source_rejects_rehashed_approval_claim(tmp_path):
    path=library(tmp_path);value=json.loads(path.read_text());entry=value['entries'][0]
    entry['actual_outcome']='accepted';entry['id']=digest({k:v for k,v in entry.items() if k!='id'});path.write_bytes(canonical(value))
    with pytest.raises(ValueError,match='actual experience'):
        advisory.select(tmp_path,'target',dict(knowledge_campaign='source',knowledge_version='library'))


def test_source_without_library_is_not_a_selection(tmp_path):
    with pytest.raises(ValueError,match='requires knowledge_version'):
        advisory.select(tmp_path,'target',dict(knowledge_campaign='source'))
