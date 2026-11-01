"""Local baselines, actual workload profiles, ablations and final policy freeze."""
import hashlib
import json
import time
from pathlib import Path

from .assessment import CATEGORIES
from .contracts import canonical, digest, local_path
from .learning import calibrate, category_weight, eligibility, fit, recipe, sequence_id, train_temporal_torch
from .transfer import inspect_payload


def read_features(root,relative):
    raw=local_path(root,relative).read_bytes()
    shard=inspect_payload(raw)
    if any(r.split=='test' for r in shard.rows):
        raise ValueError('sealed final-test features cannot enter development studies')
    return shard


def save(root,campaign,kind,value):
    raw=canonical(value)
    path=local_path(root,f'campaigns/{campaign}/studies/{kind}-{hashlib.sha256(raw).hexdigest()}.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():path.write_bytes(raw)
    return dict(path=str(path),sha256=digest(value),report=value)


def baseline(root,campaign,request):
    shard=read_features(root,request['feature_file']);categories=request['categories']
    eligibility(shard,categories)  # Also validates the advertised category names.
    training=[r for r in shard.rows if r.split=='train']
    validation=[r for r in shard.rows if r.split=='validation']
    support={}
    for category in categories:
        i=CATEGORIES.index(category)
        support[category]={split:{str(target):len({sequence_id(r) for r in rows if r.assessed[i] and r.targets[i]==target})
            for target in (0,1)} for split,rows in (('train',training),('validation',validation))}
    informative=bool(categories and len({r.family_id for r in training})>=10 and len({r.family_id for r in validation})>=5
        and all(min(s['train'].values())>=10 and min(s['validation'].values())>=5 for s in support.values()))
    results=[]
    if informative:
        for model in ('linear','temporal'):
            for seed in (0,1,2):
                started=time.monotonic()
                result=fit(shard,categories=categories,model=model,seed=seed,engineering=True)
                results.append(dict(model=model,seed=seed,artifact=result['checkpoint'],
                    calibration=calibrate(result['checkpoint'],shard),seconds=time.monotonic()-started))
    report=dict(schema_version='local-baseline-1.0',campaign=campaign,feature_file=request['feature_file'],
        data_sha256=digest(shard),recipe_sha256=digest(recipe(shard.extractor)),extractor=shard.extractor,
        categories=categories,support=support,informative=informative,results=results,promoted=False,
        limitation='Exploratory engineering baselines do not bypass supported-training or promotion gates.')
    return save(root,campaign,'baseline',report)


def verify_baseline(root,campaign,relative):
    path=local_path(root,relative);report=json.loads(path.read_text())
    shard=read_features(root,report['feature_file'])
    if report.get('schema_version')!='local-baseline-1.0' or report['campaign']!=campaign:
        raise ValueError('baseline belongs to another study')
    if report['data_sha256']!=digest(shard) or report['recipe_sha256']!=digest(recipe(shard.extractor)):
        raise ValueError('baseline data or recipe changed')
    # Recompute deterministic support rather than trusting an editable informative flag.
    training=[r for r in shard.rows if r.split=='train'];validation=[r for r in shard.rows if r.split=='validation']
    informative=bool(report['categories'] and len({r.family_id for r in training})>=10 and len({r.family_id for r in validation})>=5)
    for c in report['categories']:
        index=CATEGORIES.index(c)
        for rows,minimum in ((training,10),(validation,5)):
            informative &= all(len({sequence_id(r) for r in rows if r.assessed[index] and r.targets[index]==t})>=minimum for t in (0,1))
    if bool(report['informative'])!=informative or (informative and len(report['results'])!=6):
        raise ValueError('baseline support/results mismatch')
    return report


def ablation(root,campaign,request):
    left=verify_baseline(root,campaign,request['baseline_file'])
    right=verify_baseline(root,campaign,request['candidate_file'])
    a=read_features(root,left['feature_file']);b=read_features(root,right['feature_file'])
    def supervision(shard):
        return sorted((r.case_id,r.family_id,r.split,r.targets,r.assessed,[category_weight(r,i) for i in range(9)]) for r in shard.rows)
    if supervision(a)!=supervision(b) or left['categories']!=right['categories']:
        raise ValueError('ablation requires identical sequence/split/supervision coverage')
    return save(root,campaign,'ablation',dict(schema_version='representation-ablation-1.0',
        baseline_sha256=digest(left),candidate_sha256=digest(right),baseline_results=left['results'],
        candidate_results=right['results'],promoted=False,meaning='Matched local validation results; repair utility remains separately unproven.'))


def profile(root,campaign,request):
    shard=read_features(root,request['feature_file']);categories=request['categories']
    rows=[r for r in shard.rows if r.split=='train']
    eligibility(shard,categories)
    if len({sequence_id(r) for r in rows})<20:raise ValueError('profile requires 20 representative training sequences')
    if not any(r.assessed[CATEGORIES.index(c)] for r in rows for c in categories):
        raise ValueError('profile needs actual assessed targets for the proposed workload')
    import torch
    devices=['cpu']+(['mps'] if torch.backends.mps.is_available() else [])
    profiles=[];failures=[];artifacts={}
    for device in devices:
        started=time.monotonic()
        try:
            result=train_temporal_torch(shard,categories=categories,device=device,profile_only=True)
            artifacts[device]=result['checkpoint']
            profiles.append(dict(device=device,wall_seconds=time.monotonic()-started,
                                 training_seconds=result['checkpoint']['seconds']))
        except RuntimeError as exc:
            failures.append(dict(device=device,reason=str(exc)))
    if not profiles:raise ValueError('no local device completed the proposed workload')
    best=min(profiles,key=lambda p:p['wall_seconds']);artifact=artifacts[best['device']]
    report=dict(schema_version='local-workload-profile-1.0',campaign=campaign,
        feature_file=request['feature_file'],data_sha256=digest(shard),recipe_sha256=digest(recipe(shard.extractor)),
        categories=categories,steps=artifact['steps'],wall_seconds=best['wall_seconds'],device=best['device'],
        training_seconds=best['training_seconds'],device_profiles=profiles,device_failures=failures,
        sequences=len(rows),families=len({r.family_id for r in rows}),torch_version=artifact['torch_version'],promoted=False,
        scope='Actual temporal forward/backward/optimizer workload; fastest successful local CPU/MPS device, no quality claim.')
    return save(root,campaign,'profile',report)


def execution_sources():
    folder=Path(__file__).resolve().parent
    return {name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in
        ('learning.py','features.py','runner.py','assessment.py','specialists.py','advisory.py','knowledge.py')}


def final_evidence(root,campaign,request):
    from .experiment import freeze_final,promotion
    from .ledger import Ledger,Stopped
    from .report import build
    ledger=Ledger(root);config=ledger.config(campaign)
    shard=read_features(root,request['feature_file'])
    model_raw=local_path(root,request['model_file']).read_bytes()
    model=json.loads(model_raw)
    if model.get('engineering_only',True) or model.get('extractor')!=shard.extractor:
        raise Stopped('final policy requires a supported model with matching representation')
    if model['data_sha256']!=digest(shard) or model['recipe']!=recipe(shard.extractor):
        raise Stopped('model training data/recipe binding differs')
    gate=eligibility(shard,model['categories'])
    if not gate['eligible']:raise Stopped('; '.join(gate['reasons']))
    calibration=calibrate(model,shard)
    comparison=build(root,campaign)['controls']
    previous_recall=None
    if request.get('previous_model_file'):
        previous=json.loads(local_path(root,request['previous_model_file']).read_text())
        previous_calibration=calibrate(previous,shard)
        previous_recall={c:m['selected']['recall'] for c,m in previous_calibration['categories'].items() if m['selected']}
    decision=promotion(calibration,comparison,previous_recall=previous_recall)
    if not decision['promoted']:raise Stopped('; '.join(decision['reasons']))
    hashes={key:hashlib.sha256(local_path(root,request[key+'_file']).read_bytes()).hexdigest()
        for key in ('model','policy','prompts','preprocessing')}
    if hashes['model']!=hashlib.sha256(model_raw).hexdigest():raise Stopped('model changed while freezing final policy')
    frozen=freeze_final(config,detector_sha256=hashes['model'],policy_sha256=hashes['policy'],
        prompts_sha256=hashes['prompts'],preprocessing_sha256=hashes['preprocessing'],evidence=dict(promotion_passed=True))
    knowledge_version=request.get('knowledge_version')
    knowledge_sha256=None
    if knowledge_version:
        from .knowledge import retrieve
        retrieve(root,campaign,version=knowledge_version,categories=model['categories'])
        knowledge_sha256=hashlib.sha256(local_path(root,f'campaigns/{campaign}/knowledge/{knowledge_version}.json').read_bytes()).hexdigest()
    return dict(frozen=frozen,execution_sources=execution_sources(),feature_data_sha256=digest(shard),calibration=calibration,comparison=comparison,decision=decision,
        artifact_files={key:request[key+'_file'] for key in hashes},artifact_hashes=hashes,
        knowledge_version=knowledge_version,knowledge_sha256=knowledge_sha256)


def verify_frozen(root,campaign):
    from .ledger import Ledger
    ledger=Ledger(root)
    with ledger.db() as db:
        row=db.execute("SELECT evidence FROM knowledge_releases WHERE campaign=? AND stage='final'",(campaign,)).fetchone()
    if not row:raise ValueError('final evaluation is not released')
    release=json.loads(row[0]);detail=release['detail']
    if release['config_sha256']!=digest(ledger.config(campaign)):raise ValueError('frozen final task configuration changed')
    if detail.get('execution_sources')!=execution_sources():raise ValueError('frozen final execution sources changed')
    for key,relative in detail['artifact_files'].items():
        if hashlib.sha256(local_path(root,relative).read_bytes()).hexdigest()!=detail['artifact_hashes'][key]:
            raise ValueError('frozen final policy artifact changed')
    if detail['knowledge_version']:
        path=local_path(root,f"campaigns/{campaign}/knowledge/{detail['knowledge_version']}.json")
        if hashlib.sha256(path.read_bytes()).hexdigest()!=detail['knowledge_sha256']:
            raise ValueError('frozen final knowledge changed')
    return detail


def final_report(root,campaign,request):
    from .ledger import Ledger,Stopped
    from .curriculum import protocol
    ledger=Ledger(root);config=ledger.config(campaign)
    detail=verify_frozen(root,campaign)
    model=json.loads(local_path(root,detail['artifact_files']['model']).read_text())
    shard=inspect_payload(local_path(root,request['feature_file']).read_bytes())
    expected={digest(c) for c in protocol(config)['final']}
    original_ids=set();exclusions=[]
    for cid in protocol(config)['final']:
        progress=ledger.progress(campaign,cid);result=progress['result']
        if not result:raise Stopped('final report requires all 160 frozen final outcomes')
        if result.get('intake') and any(not i['eligible'] for i in result['intake']):
            exclusions.append(dict(sequence_id=digest(cid),reason='intake_failed',result_sha256=digest(result)))
        else:
            if not result.get('base_revision_id'):raise Stopped('final sequence baseline evidence missing')
            original_ids.add(digest(result['base_revision_id']))
    rows={sequence_id(r):r for r in shard.rows if r.split=='test' and r.case_id in original_ids}
    if set(rows)|{e['sequence_id'] for e in exclusions}!=expected:
        raise Stopped('final features must cover every nonexcluded original sequence')
    metrics={}
    from .learning import predict,family_precision_interval
    predictions={key:predict(model,r)['scores'] for key,r in rows.items()}
    for category in model['categories']:
        i=CATEGORIES.index(category);threshold=detail['calibration']['categories'][category]['selected']['threshold']
        assessed=[(key,r) for key,r in rows.items() if r.assessed[i]]
        tp=sum(r.targets[i] and predictions[key][category]>=threshold for key,r in assessed)
        fp=sum(not r.targets[i] and predictions[key][category]>=threshold for key,r in assessed)
        fn=sum(r.targets[i] and predictions[key][category]<threshold for key,r in assessed)
        metrics[category]=dict(threshold=threshold,true_positive=tp,false_positive=fp,false_negative=fn,
            precision=tp/(tp+fp) if tp+fp else None,
            precision_interval=family_precision_interval([(r,predictions[key][category]) for key,r in assessed],i,threshold),
            recall=tp/(tp+fn) if tp+fn else None,
            assessed=len(assessed),unassessed=len(rows)-len(assessed))
    return save(root,campaign,'final',dict(schema_version='frozen-final-report-1.0',frozen=detail['frozen'],
        data_sha256=digest(shard),metrics=metrics,sequences=len(rows),allocated=160,exclusions=exclusions,promoted=False,
        authority='advisory_only',label_source='scoped_model_assessments',
        frame_localization=None,region_localization=None,localization_limitation='Sequence targets do not establish frame or spatial localization accuracy',
        limitation='No anatomy, spatial localization, human acceptance or general animation-quality claim.'))


def compute_plan(root,campaign,request):
    """Run the real admission policy without reserving money or contacting Modal."""
    from .compute_gate import admit
    from .ledger import Ledger
    from .remote import Job
    shard=read_features(root,request['feature_file'])
    raw=canonical(shard)
    job=Job(payload_sha256=hashlib.sha256(raw).hexdigest(),recipe_sha256=digest(recipe(shard.extractor)),
        image_digest=request['image_digest'],purpose=request.get('purpose','profile'),categories=request['categories'],
        seconds=request.get('seconds',600),startup_seconds=request.get('startup_seconds',120),
        replay_seconds=request.get('replay_seconds',600),gpu=request.get('gpu','L4'))
    reasons=[];evidence=None
    if job.purpose!='profile':reasons.extend(eligibility(shard,job.categories)['reasons'])
    ledger=Ledger(root)
    try:evidence=admit(ledger,campaign,raw,job,request.get('study'))
    except (ValueError,KeyError,OSError) as exc:reasons.append(str(exc))
    status=ledger.status(campaign)
    with ledger.db() as db:
        funding=db.execute('SELECT modal_funding FROM campaigns WHERE id=?',(campaign,)).fetchone()[0]
    budget=status['budgets']['modal']
    if job.quote()+budget['incurred']+budget['reserved']>funding:reasons.append('Modal allocation is unfunded or exhausted')
    if status['stopped']:reasons.append('campaign stopped')
    return dict(schema_version='compute-plan-1.0',job=job.model_dump(mode='json'),quote_microdollars=job.quote(),
                admitted=not reasons,reasons=reasons,evidence=evidence,reserved_microdollars=0,remote_bytes_transferred=0,
                limitation='Funding, lifetime wall allowance and concurrent requests are rechecked atomically at dispatch.')
