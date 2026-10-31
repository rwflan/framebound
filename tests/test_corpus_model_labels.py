import json

import pytest

from framebound.v3.benchmark import run
from test_tracked_scene import scene_task


def case(tmp_path, name, **changes):
    folder=tmp_path/name;folder.mkdir()
    _,spec,frames=scene_task(folder)
    return dict(id=name,spec=spec,assets={aid:f'{name}/{aid}.png' for aid in frames},frame_asset_ids=frames,
        expected_defects=[],complete_labels=True,origin='image_generated',label_source='model_review',
        label_provenance='Simulated model-label declaration for an engineering test, not actual artwork evidence.',
        generation_provenance='Procedural fixture testing model label semantics only.',split='held_out',
        board_id='board-a',identity_family='family-a',**changes)


def test_model_labels_are_measured_without_a_human_gate(tmp_path):
    manifest=tmp_path/'corpus.json'
    manifest.write_text(json.dumps(dict(id='fixture',cases=[case(tmp_path,'base')],methodology='Engineering fixture; automated label handling.')))
    report=run(manifest)
    assert report['summary']['model_reviewed_generated_held_out_cases']==1
    assert report['summary']['independent_reviewed_generated_held_out_cases']==0
    assert report['missing_evidence']==[]
    assert report['per_board']['board-a']['false_alarms']==0
    assert report['label_authority'].startswith('Corpus label provenance is imported evidence')


def test_identity_family_split_leakage_rejected_before_evaluation(tmp_path):
    first=case(tmp_path,'first');second=case(tmp_path,'second');second['split']='development'
    manifest=tmp_path/'corpus.json'
    manifest.write_text(json.dumps(dict(id='fixture',cases=[first,second],methodology='Engineering split fixture.')))
    with pytest.raises(ValueError,match='straddles frozen splits'):run(manifest)
