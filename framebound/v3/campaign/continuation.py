"""Fixed, resumable collection batches followed by immutable local evidence closure.

No timer, planning call or support deficit grants spend. A live step needs an
explicit specialist and allocation backed by current account evidence.
"""
import json
from pathlib import Path

from filelock import FileLock
from pydantic import Field, StrictInt

from .contracts import Strict, Identity, canonical, digest, local_path
from .curriculum import protocol
from .ledger import Ledger, Stopped
from .progression import admitted, cohort_evidence, release


class Step(Strict):
    batch: str
    max_cases: StrictInt = Field(default=20,ge=1,le=20)
    allocation_microdollars: StrictInt = Field(ge=0,le=50000000)
    evidence: dict


def folder(root,campaign):
    Identity(id=campaign)
    p=local_path(root,f'campaigns/{campaign}/upskill');p.mkdir(parents=True,exist_ok=True)
    return p


def project(path,value):
    temp=path.with_suffix('.tmp');temp.write_bytes(canonical(value));temp.replace(path)


def latest(root,campaign):
    p=folder(root,campaign)/'latest.json'
    return json.loads(p.read_text()) if p.is_file() else None


def plan(root,campaign):
    ledger=Ledger(root);config=ledger.config(campaign)
    if config.schema_version!='2.0':raise ValueError('upskilling requires the frozen MVP protocol')
    status=ledger.status(campaign);p=protocol(config);allowed=admitted(ledger,config)
    unfinished=[c.id for c in config.cases if c.id in allowed and not ledger.progress(campaign,c.id)['result']]
    unknown=[r['id'] for r in status['requests'] if r['state']=='unknown_provider_outcome'
             or (r['state']=='wire_started' and not r['provider_response_id'])]
    pending=[r['id'] for r in status['requests'] if r['state']=='provider_pending'
             or (r['state']=='wire_started' and r['provider_response_id'])]
    previous=latest(root,campaign)
    studies=(previous or {}).get('studies',{})
    baseline=studies.get('geometry',{}).get('baseline')
    gate=(previous or {}).get('compute_candidate',{}).get('training_gate') or studies.get('geometry',{}).get('training_gate')
    with ledger.db() as db:stages=[r[0] for r in db.execute('SELECT stage FROM knowledge_releases WHERE campaign=?',(campaign,))]
    stage='expansion' if any(s.startswith('expansion:') for s in stages) else 'pilot' if 'pilot' in stages else 'rehearsal'
    reasons=[]
    if 'final' in stages:
        action='final_evaluation_only';reasons.append('Development data and policy are frozen; this controller does not acquire final cases')
    elif status['stopped'] or unknown:
        action='blocked';reasons.append('Stopped campaign or unreconciled acceptance; no paid continuation')
    elif pending:action='retrieve_accepted_response'
    elif unfinished:action='collect_fixed_batch'
    elif stage=='rehearsal':
        gate_evidence=cohort_evidence(ledger,config,p['rehearsal'])
        action='release_pilot' if gate_evidence['passed'] else 'blocked'
        reasons.extend(gate_evidence['reasons'])
    elif stage in {'pilot','expansion'}:
        gate_evidence=cohort_evidence(ledger,config,p['pilot'])
        if not gate_evidence['passed']:action='blocked';reasons.extend(gate_evidence['reasons'])
        elif gate and gate['eligible']:action='local_training_and_compute_review'
        elif baseline and any(c.id not in allowed for c in config.cases if c.stage=='expansion'):action='release_representative_expansion'
        else:action='evidence_review';reasons.append('No admissible unused development cases or saved baseline; inspect support gaps')
    else:action='evidence_review'
    return dict(schema_version='upskill-plan-1.0',campaign=campaign,config_sha256=digest(config),stage=stage,
        next_action=action,reasons=reasons,unfinished=unfinished,unknown_requests=unknown,pending_requests=pending,
        isolated_unknown_requests=status['isolated_unknown_requests'],api_budget=status['api_budget'],
        studies=studies,training_gate=gate,compute_candidate=(previous or {}).get('compute_candidate'),model_promoted=False,
        limitations=['Positive labels require actual independent scoped evidence; support quotas never invent labels.',
            'This planner neither funds nor dispatches providers or Modal. Final data remains sealed.'])


def close(root,campaign,version):
    from .export import export_campaign
    from .features import collect
    from .study import baseline,ablation,profile
    from .knowledge import build,retrieve
    from .learning import eligibility
    from .transfer import inspect_payload
    root=Path(root).resolve()
    exported=export_campaign(root,campaign,version=version)
    result=dict(dataset_version=version,export=exported,studies={},new_modal_jobs=0,model_promoted=False)
    if 'manifest' not in exported:return result
    for name,extractor in (('numeric','native-numeric-v1'),('geometry','native-geometry-v2')):
        feature=collect(root,campaign,version=version+'-'+name,dataset_version=version,extractor=extractor,scoped=True)
        study=dict(features=feature);result['studies'][name]=study
        if 'path' not in feature:continue
        relative=str(Path(feature['path']).relative_to(Path(root)))
        request=dict(feature_file=relative,categories=['temporal','artifacts'])
        study['baseline']=baseline(root,campaign,request)
        shard=inspect_payload(Path(feature['path']).read_bytes())
        study['training_gate']=eligibility(shard,request['categories'])
    studies=result['studies']
    if all('baseline' in s for s in studies.values()):
        result['ablation']=ablation(root,campaign,dict(
            baseline_file=str(Path(studies['numeric']['baseline']['path']).relative_to(Path(root))),
            candidate_file=str(Path(studies['geometry']['baseline']['path']).relative_to(Path(root)))))
        result['ablation_informative']=all(s['baseline']['report']['informative'] for s in studies.values())
    result['knowledge']=build(root,campaign,version=version+'-knowledge',dataset_version=version)
    retrieve(root,campaign,version=version+'-knowledge',categories=['temporal','artifacts'],limit=1)
    result['knowledge_closure_valid']=True
    if result['knowledge']['entries']:
        from .advisory import select
        result['advisory']=select(root,campaign,dict(knowledge_version=version+'-knowledge'))
    geometry=studies.get('geometry',{})
    if 'baseline' in geometry:
        chosen=geometry['baseline']
        feature_file=chosen['report']['feature_file']
        if not chosen['report']['informative']:
            singles={c:baseline(root,campaign,dict(feature_file=feature_file,categories=[c]))
                     for c in ('temporal','artifacts')}
            result['category_baselines']=singles
            chosen=next((b for b in singles.values() if b['report']['informative']),None)
        if chosen and chosen['report']['informative']:
            categories=chosen['report']['categories']
            shard=inspect_payload(local_path(root,feature_file).read_bytes())
            candidate=dict(categories=categories,baseline=chosen,feature_file=feature_file,
                training_gate=eligibility(shard,categories),authority='engineering_only; no automatic promotion')
            try:candidate['local_profile']=profile(root,campaign,dict(feature_file=feature_file,categories=categories))
            except (ImportError,RuntimeError,ValueError) as error:
                candidate['profile_blocker']=type(error).__name__+': '+str(error)
            if candidate['training_gate']['eligible']:
                from .learning import fit
                candidate['local_training']=fit(shard,categories=categories,model='temporal',seed=0)
            result['compute_candidate']=candidate
    return result


def step(root,campaign,request,specialist):
    spec=Step.model_validate(request);Identity(id=spec.batch)
    if specialist is None:raise ValueError('explicit live specialist required')
    ledger=Ledger(root);config=ledger.config(campaign)
    base=folder(root,campaign);batch=base/spec.batch;batch.mkdir(exist_ok=True)
    with FileLock(str(base/'coordinator.lock'),timeout=0):
        frozen=batch/'request.json';projection=batch/'result.json'
        active=base/'active.json'
        if active.is_file():
            active_batch=json.loads(active.read_text())
            if active_batch['status'] in {'collecting','closing','waiting_for_response','funding_required'} and active_batch['batch']!=spec.batch:
                raise Stopped('an unfinished fixed batch must be resumed before selecting another cohort')
        if frozen.exists():
            record=json.loads(frozen.read_text())
            if record['spec']!=spec.model_dump(mode='json'):raise ValueError('batch request is immutable')
            if record['config_sha256']!=digest(config):raise ValueError('batch campaign configuration changed')
            if projection.exists():
                old=json.loads(projection.read_text())
                if old['status'] in {'completed','blocked'}:return old
        else:
            decision=plan(root,campaign)
            action=decision['next_action']
            if action in {'blocked','evidence_review','local_training_and_compute_review','final_evaluation_only'}:
                return dict(status=action,plan=decision,new_modal_jobs=0)
            if action=='release_pilot':release(root,campaign,dict(stage='pilot'))
            elif action=='release_representative_expansion':
                previous=latest(root,campaign)
                baseline=previous['studies']['geometry']['baseline']['path']
                release(root,campaign,dict(stage='expansion',batch=spec.batch,size=80,mode='representative',
                    baseline_file=str(Path(baseline).relative_to(Path(root)))))
            allowed=admitted(ledger,config)
            selected=[c.id for c in config.cases if c.id in allowed and c.split!='test' and not ledger.progress(campaign,c.id)['result']][:spec.max_cases]
            if not selected:return dict(status='evidence_review',plan=plan(root,campaign),new_modal_jobs=0)
            # Allocate once. Restarting retrieval of accepted work never needs
            # fresh funding evidence and cannot reset existing commitments.
            ledger.fund(campaign,'api',spec.allocation_microdollars,evidence=spec.evidence)
            record=dict(spec=spec.model_dump(mode='json'),case_ids=selected,config_sha256=digest(config))
            frozen.write_bytes(canonical(record))
        progress=dict(schema_version='upskill-step-1.0',campaign=campaign,batch=spec.batch,status='collecting',
            case_ids=record['case_ids'],new_modal_jobs=0,model_promoted=False)
        project(projection,progress);project(base/'active.json',progress)
        from .runner import Runner
        outcome=Runner(root,campaign,specialist).run(max_cases=len(record['case_ids']),case_ids=record['case_ids'])
        progress['execution']={k:v for k,v in outcome['status'].items() if k!='requests'}
        pending=[r['id'] for r in outcome['status']['requests'] if r['state']=='provider_pending'
                 or (r['state']=='wire_started' and r['provider_response_id'])]
        if pending and not outcome['status']['stopped']:
            progress.update(status='waiting_for_response',pending_requests=pending)
            project(projection,progress);project(base/'active.json',progress)
            return progress
        terminal=sum(bool(ledger.progress(campaign,cid)['result']) for cid in record['case_ids'])
        if terminal<len(record['case_ids']) and not outcome['status']['stopped'] and any(
                'budget' in reason or 'spending ceiling' in reason for reason in outcome['deferred'].values()):
            progress.update(status='funding_required',terminal_in_batch=terminal,deferred=outcome['deferred'])
            project(projection,progress);project(base/'active.json',progress)
            return progress
        progress.update(status='closing',terminal_in_batch=terminal,deferred=outcome['deferred'])
        project(projection,progress);project(base/'active.json',progress)
        # No concurrent collector may change the dataset during local closure.
        with FileLock(str(local_path(root,f'campaigns/{campaign}/coordinator.lock')),timeout=0):
            progress.update(close(root,campaign,'upskill-'+spec.batch))
        progress['status']='completed' if terminal==len(record['case_ids']) and not outcome['status']['stopped'] else 'blocked'
        progress['batch_evidence']=cohort_evidence(ledger,config,record['case_ids'])
        if progress['status']=='completed' and not progress['batch_evidence']['passed']:
            ledger.stop(campaign);progress['status']='blocked'
        progress['next_action']='Review support and next release; compute requires informative data and explicit measured admission.'
        project(projection,progress);project(base/'active.json',progress);project(base/'latest.json',progress)
        return json.loads(canonical(progress))
