"""Offline, versioned quality benchmark runner with explicit label provenance.

A procedural success is engineering evidence only. Imported label declarations
never become Framebound reviewer decisions or human training acceptance.
"""
from pathlib import Path
import json
import hashlib
import tempfile
from typing import Literal

from pydantic import Field

from ..v2.domain import Strict, Roi
from ..v2.services.projects import create_project
from ..v2.services.assets import import_asset
from .services import tasks,loop
from .evaluate import digest


class DefectLabel(Strict):
    check_id: str
    slots: list[int] = Field(min_length=1)
    roi: Roi | None = None


class Case(Strict):
    id: str = Field(min_length=1,max_length=64)
    spec: dict
    assets: dict[str,str]
    frame_asset_ids: list[str] = Field(min_length=1,max_length=512)
    expected_defects: list[DefectLabel] = Field(default_factory=list)
    complete_labels: bool
    origin: Literal['procedural','image_generated','human_authored']
    label_source: Literal['procedural','independent_human_review','model_review','unreviewed']
    label_provenance: str = Field(min_length=1,max_length=4000)
    generation_provenance: str = Field(min_length=1,max_length=4000)
    split: Literal['development','held_out']
    repair_of: str | None = None
    board_id: str | None = Field(default=None, min_length=1, max_length=128)
    identity_family: str | None = Field(default=None, min_length=1, max_length=128)
    generation_metadata: dict | None = None
    provenance_blobs: dict[str,str] = Field(default_factory=dict)


class Corpus(Strict):
    schema_version: Literal['1.0'] = '1.0'
    id: str = Field(min_length=1,max_length=128)
    cases: list[Case] = Field(min_length=1,max_length=1000)
    methodology: str = Field(min_length=1,max_length=8000)


def _iou(a,b):
    if a is None or b is None:return None
    intersection=max(0,min(a.right,b['right'])-max(a.left,b['left']))*max(0,min(a.bottom,b['bottom'])-max(a.top,b['top']))
    union=(a.right-a.left)*(a.bottom-a.top)+(b['right']-b['left'])*(b['bottom']-b['top'])-intersection
    return intersection/union if union else 0


def run(manifest_path):
    path=Path(manifest_path).resolve();root=path.parent
    raw=json.loads(path.read_text());corpus=Corpus.model_validate(raw)
    if len({case.id for case in corpus.cases})!=len(corpus.cases):raise ValueError('benchmark case IDs must be unique')
    splits={}
    cases_by_id={case.id:case for case in corpus.cases}
    for case in corpus.cases:
        for key in [('board',case.board_id),('identity',case.identity_family)]:
            if key[1]:
                if key in splits and splits[key]!=case.split: raise ValueError('corpus identity/reference family straddles frozen splits')
                splits[key]=case.split
        if case.repair_of:
            parent=cases_by_id.get(case.repair_of)
            if not parent or parent.split!=case.split: raise ValueError('repair ancestry must retain its frozen split')
        if len({d.check_id for d in case.expected_defects})!=len(case.expected_defects): raise ValueError('duplicate defect label identity')
    reports=[];case_map={}
    for case in corpus.cases:
        with tempfile.TemporaryDirectory(prefix='framebound-quality-case-') as temporary:
            project=Path(temporary);create_project(str(project),{'id':'benchmark'})
            from ..v2 import storage as S
            for sha,relative in case.provenance_blobs.items():
                blob=(root/relative).resolve()
                if not blob.is_relative_to(root) or not blob.is_file(): raise ValueError('provenance blob is missing or outside corpus')
                if hashlib.sha256(blob.read_bytes()).hexdigest()!=sha: raise ValueError('provenance blob hash differs')
                S.store_blob(project,blob.read_bytes())
            asset_hashes={}
            for aid,relative in case.assets.items():
                asset=(root/relative).resolve()
                if not asset.is_relative_to(root) or not asset.is_file():raise ValueError(f'benchmark asset missing or outside corpus: {relative}')
                import_asset(str(project),str(asset),aid,source_kind='procedural' if case.origin=='procedural' else 'imported',rights='unknown')
                asset_hashes[aid]=hashlib.sha256(asset.read_bytes()).hexdigest()
            spec=dict(case.spec,project_id='benchmark',id=case.id,animation_id=case.id)
            spec.pop('supersedes',None);spec.pop('change_reason',None)
            tasks.create(str(project),spec);loop.start(str(project),case.id,'run')
            from . import provenance as P
            ancestors=[];cursor=case;seen=set()
            while cursor.repair_of:
                if cursor.id in seen: raise ValueError('cyclic benchmark repair ancestry')
                seen.add(cursor.id);cursor=cases_by_id[cursor.repair_of]
                ancestors.insert(0,dict(generation_metadata=cursor.generation_metadata))
            con=S.connect(project)
            try:P.validate_in(con,project,P.parse(case.generation_metadata),case.frame_asset_ids,ancestors)
            finally:con.close()
            # This temporary project measures pixels; source attribution remains in the report.
            feedback=loop.submit(str(project),'run','candidate',case.frame_asset_ids)
            evaluation=loop.revision_get(str(project),'candidate')['evaluation']
            predicted={r['id']:r for r in evaluation['results'] if r['outcome']=='fail'}
            expected={d.check_id:d for d in case.expected_defects}
            matched=sorted(set(expected)&set(predicted));misses=sorted(set(expected)-set(predicted))
            false_alarms=sorted(set(predicted)-set(expected)) if case.complete_labels else None
            localization=[]
            for cid in matched:
                want=set(expected[cid].slots);actual=set(predicted[cid]['slots'])
                localization.append(dict(check_id=cid,expected_slots=sorted(want),actual_slots=sorted(actual),
                    exact_frames=want==actual,frame_iou=len(want&actual)/len(want|actual),
                    region_iou=_iou(expected[cid].roi,predicted[cid]['roi'])))
            report=dict(id=case.id,source_spec_sha256=digest(case.spec),generation_metadata=case.generation_metadata,board_id=case.board_id,identity_family=case.identity_family,origin=case.origin,label_source=case.label_source,label_provenance=case.label_provenance,
                generation_provenance=case.generation_provenance,split=case.split,repair_of=case.repair_of,
                task_digest=tasks.get(str(project),case.id)['spec_sha256'],asset_hashes=asset_hashes,
                evaluation=evaluation,technical_status=feedback['technical_status'],
                true_positives=len(matched),false_negatives=len(misses),false_positives=len(false_alarms) if false_alarms is not None else None,
                missed_defects=misses,false_alarms=false_alarms,localization=localization,
                required_unmeasured_or_errors=[r['id'] for r in evaluation['results'] if r['required'] and r['outcome'] in {'unmeasured','error'}],
                unmeasured_or_errors=[r['id'] for r in evaluation['results'] if r['outcome'] in {'unmeasured','error'}])
            reports.append(report);case_map[case.id]=report
    repairs=[]
    for case in corpus.cases:
        if not case.repair_of:continue
        if case.repair_of not in case_map:raise ValueError('repair case references an unknown benchmark baseline')
        before=case_map[case.repair_of];after=case_map[case.id]
        old={r['id']:r for r in before['evaluation']['results']};new={r['id']:r for r in after['evaluation']['results']}
        model_labels = (cases_by_id[before['id']].label_source=='model_review' and case.label_source=='model_review')
        old_labels={d.check_id for d in cases_by_id[before['id']].expected_defects};new_labels={d.check_id for d in case.expected_defects}
        repairs.append(dict(baseline=before['id'],repair=after['id'],
            model_label_changes=(dict(no_longer_labeled=sorted(old_labels-new_labels),newly_labeled=sorted(new_labels-old_labels),
                authority='Model annotations with incomplete coverage; absence of a label is not proof of correction.') if model_labels else None),
            baseline_failed_checks=[k for k,r in old.items() if r['outcome']=='fail'],
            improved_checks=[k for k,r in old.items() if r['outcome']=='fail' and new.get(k,{}).get('outcome')=='pass'],remaining_failed_checks=[k for k,r in new.items() if r['outcome']=='fail'],
            regressions=[k for k,r in old.items() if r['outcome']=='pass' and new.get(k,{}).get('outcome') not in {'pass','not_applicable'}],
            overall_outcome=after['technical_status']))
    tp=sum(r['true_positives'] for r in reports);fn=sum(r['false_negatives'] for r in reports)
    comparable=[r for r in reports if r['false_positives'] is not None];fp=sum(r['false_positives'] for r in comparable)
    reviewed_generated=[r for r in reports if r['origin']=='image_generated' and r['label_source']=='independent_human_review' and r['split']=='held_out']
    model_reviewed=[r for r in reports if r['origin']=='image_generated' and r['label_source']=='model_review' and r['split']=='held_out']
    boards={}
    for bid in {r['board_id'] for r in reports if r['board_id']}:
        members=[r for r in reports if r['board_id']==bid]
        boards[bid]=dict(cases=len(members),true_positives=sum(r['true_positives'] for r in members),
            misses=sum(r['false_negatives'] for r in members),
            false_alarms=(sum(r['false_positives'] for r in members if r['false_positives'] is not None) if any(r['false_positives'] is not None for r in members) else None),
            incomplete_label_cases=sum(r['false_positives'] is None for r in members),
            localization=[x for r in members for x in r['localization']],
            unmeasured=[dict(case_id=r['id'],checks=r['unmeasured_or_errors']) for r in members if r['unmeasured_or_errors']],
            repairs=[r for r in repairs if case_map[r['repair']]['board_id']==bid])
    return dict(schema_version='1.0',per_board=boards,corpus_id=corpus.id,corpus_digest=digest(raw),methodology=corpus.methodology,
        cases=reports,repairs=repairs,summary=dict(cases=len(reports),true_positives=tp,false_negatives=fn,false_positives=fp if comparable else None,
            precision=(sum(r['true_positives'] for r in comparable)/(sum(r['true_positives'] for r in comparable)+fp) if comparable and sum(r['true_positives'] for r in comparable)+fp else None),
            recall=tp/(tp+fn) if tp+fn else None,
            exact_frame_localizations=sum(x['exact_frames'] for r in reports for x in r['localization']),
            independent_reviewed_generated_held_out_cases=len(reviewed_generated),
            model_reviewed_generated_held_out_cases=len(model_reviewed)),
        quality_claim='Benchmark-specific measurements only; no arbitrary complex-animation reliability or human acceptance is inferred.',
        label_authority='Corpus label provenance is imported evidence, not an authenticated Framebound reviewer decision.',
        missing_evidence=[] if reviewed_generated or model_reviewed else ['No model-labeled or human-labeled held-out generated-animation cases were supplied. Automated model labels are the default; human oversight is optional.'])
