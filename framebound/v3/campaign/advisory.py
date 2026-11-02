"""Opt-in measured advice for generation/correction, never for teacher labeling."""
import hashlib
import json

from .assessment import CATEGORIES
from .contracts import Identity, canonical, digest, local_path
from .features import extract
from .learning import calibrate, eligibility, predict, recipe
from .study import read_features, save, verify_frozen
from .transfer import FeatureRow, FeatureRowV2


def _library(root, campaign, version):
    """Validate a private library against its actual train-only source rows."""
    Identity(id=campaign); Identity(id=version)
    from .knowledge import retrieve
    retrieve(root,campaign,version=version,categories=list(CATEGORIES))
    path=local_path(root,f'campaigns/{campaign}/knowledge/{version}.json')
    raw=path.read_bytes();library=json.loads(raw)
    if library.get('authority')!='advisory_only' or library.get('schema_version')!='animation-knowledge-2.0':
        raise ValueError('cross-campaign advice requires a scoped advisory-only library')
    Identity(id=library['dataset_version'])
    dataset=local_path(root,f"campaigns/{campaign}/training/{library['dataset_version']}")
    rows={r['id']:r for r in (json.loads(line) for line in (dataset/'detection.jsonl').read_text().splitlines())}
    manifest_sha=digest(json.loads((dataset/'manifest.json').read_text()))
    experiences={}
    for lane in ('editing','preference','failure'):
        for line in (dataset/(lane+'.jsonl')).read_text().splitlines():
            row=json.loads(line)
            if row['split']!='train' or not row.get('comparison'):continue
            experience=dict(candidate_revision_id=row['id'],outcome=row.get('outcome','unassessed'),
                instruction=row.get('edit_instruction'),scope=row.get('scope'),comparison=row['comparison'])
            for rid in {row['id'],row.get('baseline_revision_id')}:
                linked=experiences.setdefault(rid,[])
                if experience not in linked:linked.append(experience)
    for entry in library['entries']:
        row=rows.get(entry['revision_id'])
        if not row or row['split']!='train' or not row.get('rights') or any(r!='original' for r in row['rights']):
            raise ValueError('knowledge entry is not original train-only evidence')
        assessment=row.get('assessment')
        if (not assessment or entry['family']!=row['family'] or entry['evidence_files']!=row['frames']
                or entry['dataset_sha256']!=manifest_sha or entry['assessment_sha256']!=digest(assessment)
                or entry['provenance']!=assessment['provenance'] or entry.get('sequence_id')!=row.get('sequence_id',row['id'])
                or entry.get('human_acceptance') is not False
                or entry.get('label_source')!='model' or entry['id']!=digest({k:v for k,v in entry.items() if k!='id'})):
            raise ValueError('knowledge entry differs from its actual scoped evidence')
        linked=experiences.get(row['id'],[])
        last=linked[-1] if linked else {}
        if (entry.get('experiences')!=linked or entry.get('proposed_correction')!=last.get('instruction')
                or entry.get('preservation_requirements')!=last.get('scope')
                or entry.get('actual_outcome')!=last.get('outcome','unlinked')
                or entry.get('comparison')!=last.get('comparison')):
            raise ValueError('knowledge correction outcome differs from its actual experience')
        if entry['record_kind']=='observed_finding':
            fields=('category','subject','part','slots','tick_range','roi','observed','expected','counterexamples','visibility','severity')
            if not any(all(entry.get(k)==finding.get(k) for k in fields) for finding in assessment['findings']):
                raise ValueError('knowledge finding differs from its assessment')
        elif entry['record_kind']=='assessed_negative':
            ticks=[0]
            for hold in row['holds']:ticks.append(ticks[-1]+hold)
            if (entry.get('observed')!='No defect reported within this explicitly assessed scope'
                    or entry.get('visibility')!='assessed_scope' or entry.get('expected') is not None
                    or entry.get('tick_ranges')!=[[ticks[slot],ticks[slot+1]] for slot in sorted(entry['slots'])]):
                raise ValueError('knowledge negative invents evidence beyond its scope')
            if not any(c['category']==entry['category'] and c['status']=='absent_within_assessed_scope'
                       and c['slots']==entry['slots'] and c['limitations']==entry['counterexamples'] for c in assessment['coverage']):
                raise ValueError('knowledge negative differs from its assessed scope')
        else:raise ValueError('unsupported knowledge record kind')
    if path.read_bytes()!=raw:raise ValueError('knowledge changed during selection')
    return path,raw,library,rows


def _isolated_lineage(root):
    from .ledger import Ledger
    ledger=Ledger(root);identities=ledger.isolated_families()
    with ledger.db() as db:
        for cid,raw in db.execute('SELECT r.case_id,c.config FROM unknown_isolations i JOIN requests r ON r.id=i.request_id JOIN campaigns c ON c.id=r.campaign'):
            case=next(c for c in json.loads(raw)['cases'] if c['id']==cid)
            identities.update(case.get('ancestry',[]))
    return identities


def _target_lineage(root,campaign,family,ancestry):
    result={family,*ancestry}
    from .ledger import Ledger
    with Ledger(root).db() as db:
        record=db.execute('SELECT config FROM campaigns WHERE id=?',(campaign,)).fetchone()
    if record:
        for case in json.loads(record[0])['cases']:
            if case['family']==family:result.update(case.get('ancestry',[]))
    return result


def require_own_final_knowledge(root,campaign,request):
    """The existing final schema cannot silently substitute a source library."""
    selection=get_selection(root,campaign)
    if request.get('knowledge_campaign',campaign)!=campaign or (selection and selection.get('knowledge_campaign',campaign)!=campaign):
        raise ValueError('cross-campaign knowledge must be deselected before final freeze; source namespace is not supported by the frozen schema')


def select(root,campaign,request):
    version=request.get('knowledge_version');model_file=request.get('model_file')
    source=request.get('knowledge_campaign',campaign)
    Identity(id=campaign);Identity(id=source)
    if 'knowledge_campaign' in request and not version:raise ValueError('knowledge_campaign requires knowledge_version')
    if not version and not model_file:raise ValueError('select a knowledge library or supported model')
    from .ledger import Ledger,Stopped
    ledger=Ledger(root)
    with ledger.db() as db:
        if db.execute("SELECT 1 FROM knowledge_releases WHERE campaign=? AND stage='final'",(campaign,)).fetchone():
            raise Stopped('advice is frozen for final evaluation')
    selection=dict(schema_version='animation-advisory-1.0',campaign=campaign,knowledge_version=version,
        model_file=model_file,model_sha256=None,knowledge_sha256=None,calibration=None,authority='advisory_only',promoted=False)
    if version:
        if 'knowledge_campaign' in request:
            selection['knowledge_campaign']=source
            path,raw,_,_=_library(root,source,version)
        else:
            from .knowledge import retrieve
            retrieve(root,campaign,version=version,categories=list(CATEGORIES))
            path=local_path(root,f'campaigns/{campaign}/knowledge/{version}.json')
            raw=path.read_bytes()
        selection['knowledge_sha256']=hashlib.sha256(raw).hexdigest()
    if model_file:
        shard=read_features(root,request['feature_file']);path=local_path(root,model_file)
        model=json.loads(path.read_text())
        if model.get('engineering_only',True) or model['data_sha256']!=digest(shard) or model['recipe']!=recipe(shard.extractor):
            raise ValueError('advice requires a supported model bound to current development data/recipe')
        gate=eligibility(shard,model['categories'])
        calibration=calibrate(model,shard)
        if not gate['eligible'] or any(m['selected'] is None for m in calibration['categories'].values()):
            raise ValueError('advisory model needs training support and selected validation thresholds')
        selection.update(model_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),calibration=calibration)
    result=save(root,campaign,'advisory',selection)
    pointer=local_path(root,f'campaigns/{campaign}/advisory/current.json')
    pointer.parent.mkdir(parents=True,exist_ok=True)
    from filelock import FileLock
    with FileLock(str(pointer)+'.lock'):
        import os,secrets
        temporary=pointer.parent/('.selection-'+secrets.token_hex(8))
        try:
            temporary.write_bytes(canonical(selection));os.replace(temporary,pointer)
        finally:temporary.unlink(missing_ok=True)
    return result


def get_selection(root,campaign,*,final=False):
    if final:
        require_own_final_knowledge(root,campaign,{})
        frozen=verify_frozen(root,campaign)
        return dict(model_file=frozen['artifact_files']['model'],model_sha256=frozen['artifact_hashes']['model'],
                    knowledge_version=frozen['knowledge_version'],knowledge_sha256=frozen['knowledge_sha256'],
                    calibration=frozen['calibration'])
    pointer=local_path(root,f'campaigns/{campaign}/advisory/current.json')
    return json.loads(pointer.read_text()) if pointer.exists() else None


def query(root,campaign,frames,holds,*,loop,family,categories,final=False,ancestry=()):
    selection=get_selection(root,campaign,final=final)
    if not selection:return dict(authority='advisory_only',entries=[],scores={},reason='No advice selected')
    result=dict(authority='advisory_only',entries=[],scores={},selection_sha256=digest(selection),
        limitation='Advice cannot create findings, expand edit scope, approve art or close reviewer feedback.')
    if selection['knowledge_version']:
        from .knowledge import retrieve
        version=selection['knowledge_version']
        source=selection.get('knowledge_campaign',campaign)
        path=local_path(root,f'campaigns/{source}/knowledge/{version}.json')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=selection['knowledge_sha256']:
            raise ValueError('selected knowledge bytes changed')
        excluded=_target_lineage(root,campaign,family,ancestry)|_isolated_lineage(root)
        if 'knowledge_campaign' in selection:
            _,raw,library,rows=_library(root,source,version)
            if hashlib.sha256(raw).hexdigest()!=selection['knowledge_sha256']:raise ValueError('selected knowledge bytes changed')
            if not categories or any(c not in CATEGORIES for c in categories):raise ValueError('supported categories required')
            entries=[e for e in library['entries'] if e['category'] in categories
                and not excluded.intersection([e['family'],*rows[e['revision_id']].get('ancestry',[])])]
            entries.sort(key=lambda e:(e['visibility']!='supported',e['actual_outcome']!='accepted',e['id']))
            result['entries']=entries[:3]
        else:
            result['entries']=retrieve(root,source,version=version,categories=categories,exclude_families=excluded)['entries']
    if frames and selection['model_file']:
        from ..intake import inspect
        if not all(inspect(f)['eligible'] for f in frames):
            return dict(result,reason='Intake failed; learned animation advice withheld')
        path=local_path(root,selection['model_file'])
        if hashlib.sha256(path.read_bytes()).hexdigest()!=selection['model_sha256']:raise ValueError('selected model bytes changed')
        model=json.loads(path.read_text())
        measured=extract(frames,holds,loop=loop,extractor=model['extractor'])
        data=dict(case_id=digest('advisory-query'),family_id=digest(family),split='validation',
            features=measured['features'].tolist(),targets=[0]*9,assessed=[False]*9)
        if model['extractor']=='native-geometry-v2':
            row=FeatureRowV2(**data,sequence_id=data['case_id'],category_weights=[.5]*9)
        else:row=FeatureRow(**data)
        scores=predict(model,row)['scores']
        for category in categories:
            metric=selection['calibration']['categories'].get(category)
            selected=metric['selected'] if metric else None
            score=scores.get(category)
            result['scores'][category]=dict(score=score,threshold=selected['threshold'] if selected else None,
                state='suspected' if selected and score is not None and score>=selected['threshold'] else 'abstained')
    return result
