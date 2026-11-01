"""Opt-in measured advice for generation/correction, never for teacher labeling."""
import hashlib
import json

from .assessment import CATEGORIES
from .contracts import canonical, digest, local_path
from .features import extract
from .learning import calibrate, eligibility, predict, recipe
from .study import read_features, save, verify_frozen
from .transfer import FeatureRow, FeatureRowV2


def select(root,campaign,request):
    version=request.get('knowledge_version');model_file=request.get('model_file')
    if not version and not model_file:raise ValueError('select a knowledge library or supported model')
    from .ledger import Ledger,Stopped
    ledger=Ledger(root)
    with ledger.db() as db:
        if db.execute("SELECT 1 FROM knowledge_releases WHERE campaign=? AND stage='final'",(campaign,)).fetchone():
            raise Stopped('advice is frozen for final evaluation')
    selection=dict(schema_version='animation-advisory-1.0',campaign=campaign,knowledge_version=version,
        model_file=model_file,model_sha256=None,knowledge_sha256=None,calibration=None,authority='advisory_only',promoted=False)
    if version:
        from .knowledge import retrieve
        retrieve(root,campaign,version=version,categories=list(CATEGORIES))
        path=local_path(root,f'campaigns/{campaign}/knowledge/{version}.json')
        selection['knowledge_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
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
        frozen=verify_frozen(root,campaign)
        return dict(model_file=frozen['artifact_files']['model'],model_sha256=frozen['artifact_hashes']['model'],
                    knowledge_version=frozen['knowledge_version'],knowledge_sha256=frozen['knowledge_sha256'],
                    calibration=frozen['calibration'])
    pointer=local_path(root,f'campaigns/{campaign}/advisory/current.json')
    return json.loads(pointer.read_text()) if pointer.exists() else None


def query(root,campaign,frames,holds,*,loop,family,categories,final=False):
    selection=get_selection(root,campaign,final=final)
    if not selection:return dict(authority='advisory_only',entries=[],scores={},reason='No advice selected')
    result=dict(authority='advisory_only',entries=[],scores={},selection_sha256=digest(selection),
        limitation='Advice cannot create findings, expand edit scope, approve art or close reviewer feedback.')
    if selection['knowledge_version']:
        from .knowledge import retrieve
        version=selection['knowledge_version']
        path=local_path(root,f'campaigns/{campaign}/knowledge/{version}.json')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=selection['knowledge_sha256']:
            raise ValueError('selected knowledge bytes changed')
        result['entries']=retrieve(root,campaign,version=version,categories=categories,exclude_families=[family])['entries']
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
