"""Explicit, private, resumable model-learning journeys over the campaign engine.

Saving settings or preparing a journey never sends provider requests. Each start
uses the saved fixed cohort, existing receipt recovery and unchanged support gates.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from urllib.request import Request, urlopen

from filelock import FileLock, Timeout
from pydantic import Field, SecretStr
from ...v2.domain import Strict
from ...v2.services.authz import require_reviewer
from ..campaign.contracts import canonical, digest

class Providers(Strict):
    meta_api_key: SecretStr | None = None
    modal_token_id: SecretStr | None = None
    modal_token_secret: SecretStr | None = None

class Setup(Strict):
    id: str = Field(pattern=r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$')
    name: str = Field(min_length=1,max_length=100)
    focus: Literal['balanced','motion','identity'] = 'balanced'
    budget_dollars: Decimal = Field(gt=0,le=50,decimal_places=2)

class Start(Strict):
    confirm_spend: Literal[True]
    # The start confirmation presents these documented standard rates. Account
    # access is checked independently; a quote is not inferred from key presence.
    confirm_standard_rates: Literal[True]


def home(project):
    base=Path(os.environ.get('FRAMEBOUND_TRAINING_HOME',str(Path.home()/'.config/framebound/training'))).expanduser().absolute()
    if base.resolve().is_relative_to(Path(__file__).resolve().parents[3]):
        raise ValueError('Training credentials and experiments must remain outside the repository')
    target=base/hashlib.sha256(str(Path(project).resolve()).encode()).hexdigest()[:24]
    target.mkdir(parents=True,exist_ok=True,mode=0o700)
    if target.is_symlink():raise ValueError('Private training directory cannot be a symlink')
    os.chmod(target,0o700)
    return target


def write(path,value):
    if path.is_symlink():raise ValueError('Private settings cannot be a symlink')
    tmp=path.parent/('.private-'+secrets.token_hex(12))
    fd=os.open(tmp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,'wb') as f:f.write(canonical(value));f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:tmp.unlink(missing_ok=True)


def read(path,default=None):
    if not path.exists():return default
    if path.is_symlink() or path.stat().st_mode & 0o077:raise ValueError('Private settings require mode 0600')
    return json.loads(path.read_text())


def secrets_for(project):return read(home(project)/'providers.json',{})


def providers(project):
    values=secrets_for(project)
    return dict(meta=dict(configured=bool(values.get('meta_api_key'))),
        modal=dict(configured=bool(values.get('modal_token_id') and values.get('modal_token_secret'))),
        storage='private_local')


def configure(project,actor,payload):
    require_reviewer(actor,'configure_training_credentials')
    spec=Providers.model_validate(payload)
    with FileLock(str(home(project)/'settings.lock')):
        values=secrets_for(project)
        for key in spec.model_fields_set:
            field=getattr(spec,key);value=field.get_secret_value() if field is not None else ''
            if value and (not 8<=len(value)<=4096 or any(c.isspace() for c in value)):
                raise ValueError('Enter complete credentials without whitespace')
            if value:values[key]=value
            else:values.pop(key,None)
        if bool(values.get('modal_token_id'))!=bool(values.get('modal_token_secret')):
            raise ValueError('Modal requires both token ID and token secret')
        write(home(project)/'providers.json',values)
    return providers(project)


def path_for(project,identifier):
    from ..campaign.contracts import Identity
    Identity(id=identifier)
    return home(project)/('journey-'+identifier+'.json')


def create(project,actor,payload):
    require_reviewer(actor,'create_training')
    spec=Setup.model_validate(payload)
    if spec.id=='worker-image':raise ValueError('Choose a different journey ID; this identifier is reserved')
    path=path_for(project,spec.id)
    row=dict(spec.model_dump(mode='json'),status='ready',stage='setup',terminal=0,total=12,
        spent_dollars=0,reserved_dollars=0,knowledge_entries=0,training_eligible=False,
        model_promoted=False,blocker=None,updated_at=datetime.now(timezone.utc).isoformat())
    row['budget_dollars']=float(spec.budget_dollars)
    with FileLock(str(home(project)/'settings.lock')):
        old=read(path)
        if old:
            if any(old[k]!=row[k] for k in ('id','name','focus','budget_dollars')):raise ValueError('Journey ID already has different settings')
            return snapshot(project,spec.id)
        write(path,row)
    return row


def snapshot(project,identifier):
    row=read(path_for(project,identifier))
    if row is None:raise ValueError('Unknown training journey')
    root=home(project)/'data';database=root/'campaigns/lifetime.sqlite3'
    if database.is_file():
        import sqlite3
        con=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)
        try:
            campaign='learn-'+identifier
            totals=con.execute("SELECT SUM(CASE WHEN incurred IS NOT NULL THEN incurred ELSE 0 END),SUM(CASE WHEN incurred IS NULL THEN reserved ELSE 0 END) FROM requests WHERE campaign=? AND subsystem='api'",(campaign,)).fetchone()
            row['spent_dollars']=(totals[0] or 0)/1e6;row['reserved_dollars']=(totals[1] or 0)/1e6
            compute=con.execute("SELECT COALESCE(SUM(incurred),0),COALESCE(SUM(CASE WHEN incurred IS NULL THEN reserved ELSE 0 END),0) FROM requests WHERE campaign=? AND subsystem='modal'",(campaign,)).fetchone()
            row['modal_spent_dollars']=compute[0]/1e6;row['modal_reserved_dollars']=compute[1]/1e6
            committed=con.execute("SELECT COALESCE(SUM(COALESCE(incurred,reserved)),0) FROM requests WHERE subsystem='api'").fetchone()[0]
            cap=con.execute('SELECT ceiling FROM api_budget_authorizations ORDER BY id DESC LIMIT 1').fetchone()
            row['workspace_budget_dollars']=(cap[0] if cap else 0)/1e6
            row['workspace_committed_dollars']=committed/1e6
            row['terminal']=con.execute('SELECT COUNT(*) FROM cases WHERE campaign=? AND result IS NOT NULL',(campaign,)).fetchone()[0]
        finally:con.close()
    active=home(project)/'data'/'campaigns'/('learn-'+identifier)/'upskill/active.json'
    if active.is_file() and row['status'] in {'setting_up','collecting','closing'}:
        current=json.loads(active.read_text())
        if current.get('status')=='closing':row['status']='closing'
        row['batch']=current.get('batch')
        row['pending_responses']=len(current.get('pending_requests',[]))
    return row


def listing(project):
    return dict(runs=[snapshot(project,p.stem.removeprefix('journey-')) for p in sorted(home(project).glob('journey-*.json'))],credentials=providers(project))


def update(project,identifier,**changes):
    with FileLock(str(home(project)/'settings.lock')):
        path=path_for(project,identifier);row=read(path)
        if row is None:raise ValueError('Unknown training journey')
        row.update(changes,updated_at=datetime.now(timezone.utc).isoformat());write(path,row)
    return row


def account_evidence(key):
    # Read-only account access, not a billable probe or an invented balance check.
    req=Request('https://api.meta.ai/v1/models',headers={'Authorization':'Bearer '+key})
    with urlopen(req,timeout=20) as response:
        if response.status!=200:raise ValueError('Meta account verification failed')
        raw=response.read(2*1024**2+1)
    body=json.loads(raw)
    if not isinstance(body,dict) or not isinstance(body.get('data'),list):raise ValueError('Unrecognized Meta account response')
    models={m.get('id') for m in body['data'] if isinstance(m,dict)}
    if not {'muse-image-1.0','muse-spark-1.3','sam-3.1'}.issubset(models):raise ValueError('Required Meta image, assessment or segmentation model unavailable')
    return dict(verified_at=datetime.now(timezone.utc).isoformat(),source='https://dev.meta.ai/docs/pricing-rate-limits; operator-confirmed displayed standard quote',
        account_access='Read-only authenticated models GET succeeded; required image, assessment and segmentation models are listed',
        account_response_sha256=hashlib.sha256(raw).hexdigest(),image_microdollars=10000,segmentation_microdollars=2500)


def start(project,actor,identifier,payload):
    require_reviewer(actor,'start_training');Start.model_validate(payload)
    row=snapshot(project,identifier);credentials=providers(project)
    if not credentials['meta']['configured'] or not credentials['modal']['configured']:
        raise ValueError('Set the Meta key and both Modal credentials in Settings first')
    if row['status'] in {'support_review','completed'}:raise ValueError('Inspect the completed support and compute evidence before continuing')
    if row['status']=='blocked':
        from ..campaign.ledger import Ledger
        root=home(project)/'data'
        if (root/'campaigns/lifetime.sqlite3').is_file():
            ledger=Ledger(root)
            with ledger.db() as db:
                stopped=db.execute('SELECT stopped FROM campaigns WHERE id=?',('learn-'+identifier,)).fetchone()
                unknown=db.execute("SELECT 1 FROM requests WHERE campaign=? AND state IN ('unknown_provider_outcome','wire_started')",('learn-'+identifier,)).fetchone()
            if (stopped and stopped[0]) or unknown:
                raise ValueError('Inspect the saved blocker first; failed cohorts and unknown acceptance cannot be restarted')
    if row['status'] not in {'ready','paused','collecting','closing','setting_up','blocked'}:raise ValueError('Journey cannot start in this state')
    # No secret in the projection, thread name or exception text.
    update(project,identifier,status='setting_up',pause_requested=False,blocker=None)
    launch(project,identifier)
    return snapshot(project,identifier)


def pause(project,actor,identifier):
    require_reviewer(actor,'pause_training')
    row=snapshot(project,identifier)
    if row['status'] not in {'collecting','closing','setting_up'}:return row
    # Drain the admitted fixed batch; never kill an in-flight paid request.
    return update(project,identifier,pause_requested=True,blocker='Pausing after the current fixed batch; accepted work will finish safely.')


def launch(project,identifier):
    threading.Thread(target=run,args=(str(project),identifier),daemon=True,name='framebound-learning').start()


def run(project,identifier):
    from ..campaign.ledger import Ledger
    from ..campaign.curriculum import upskill_curriculum
    from ..campaign.service import operate
    from ..campaign.specialists import MuseResponses
    root=home(project)/'data';campaign='learn-'+identifier
    try:
        with FileLock(str(home(project)/('worker-'+identifier+'.lock')),timeout=0):
            credentials=secrets_for(project);row=snapshot(project,identifier)
            evidence=account_evidence(credentials['meta_api_key'])
            ledger=Ledger(root);ceiling=int(Decimal(str(row['budget_dollars']))*1000000)
            try:ledger.config(campaign)
            except ValueError:
                config=upskill_curriculum(campaign,source_policy='sam-whitespace-sheet-v9',transport='stream-all-v2')
                config=config.model_copy(update={'api_ceiling':ceiling})
                with FileLock(str(home(project)/'budget.lock')):
                    with ledger.db() as db:
                        previous=db.execute('SELECT config FROM campaigns').fetchall()
                    total=ceiling+sum(json.loads(r[0])['api_ceiling'] for r in previous)
                    if total>125000000:
                        raise ValueError('Combined journey authorizations exceed the 125 dollar workspace hard cap; existing budgets and spend are preserved')
                    ledger.plan(config)
                    ledger.authorize_api_budget(campaign,total,evidence=dict(source='Explicit local training journey start',reason='Add this explicitly authorized journey budget to all prior frozen journey budgets; preserve every historical cost and reservation',authorized_at=datetime.now(timezone.utc).isoformat()))
            specialist=MuseResponses(key=credentials['meta_api_key'])
            for index in range(1,33):
                row=snapshot(project,identifier)
                if row.get('pause_requested'):
                    update(project,identifier,status='paused',blocker=None);return
                decision=operate(root,'upskill-plan',campaign=campaign)
                if decision['next_action'] in {'blocked','evidence_review','local_training_and_compute_review','final_evaluation_only'}:
                    review_support(project,identifier)
                    current=snapshot(project,identifier)
                    candidate=decision.get('compute_candidate') or {}
                    update(project,identifier,status='blocked' if decision['next_action']=='blocked' else 'support_review',stage=decision['stage'],
                        training_eligible=current.get('training_eligible',False),
                        blocker='; '.join(decision['reasons']) or ('Local model trained and evaluated. Download the model or configure the capped, credit-only compute experiment.' if current.get('training_eligible') else 'Collection closed without sufficient support for the selected categories. Review the category support table; no model was fabricated.'),total=800)
                    return
                batch=f'b{index:03}';directory=root/'campaigns'/campaign/'upskill';saved=directory/batch/'journey-step.json'
                if saved.is_file():request=read(saved)
                else:
                    allocation=min(ceiling,1500000 if decision['stage']=='rehearsal' else 6000000 if decision['stage']=='pilot' else 16000000)
                    with ledger.db() as db:
                        funded=db.execute('SELECT api_funding FROM campaigns WHERE id=?',(campaign,)).fetchone()[0]
                    allocation=max(allocation,funded)
                    request=dict(batch=batch,max_cases=12 if index==1 else 20,allocation_microdollars=allocation,evidence=evidence)
                    saved.parent.mkdir(parents=True,exist_ok=True);write(saved,request)
                update(project,identifier,status='collecting',stage=decision['stage'],total=12 if decision['stage']=='rehearsal' else 92 if decision['stage']=='pilot' else 800)
                while True:
                    result=operate(root,'upskill-step',campaign=campaign,request=request,specialist=specialist)
                    if result['status']=='waiting_for_response':
                        # Accepted retrieval uses the exact frozen step on restart.
                        import time
                        time.sleep(5);continue
                    if result['status']=='funding_required':
                        current=ledger.status(campaign)
                        with ledger.db() as db:funded=db.execute('SELECT api_funding FROM campaigns WHERE id=?',(campaign,)).fetchone()[0]
                        increase=min(ceiling,funded+2000000)
                        if increase<=funded:
                            update(project,identifier,status='blocked',blocker='Budget exhausted; all incurred costs and pending reservations are preserved.');return
                        ledger.fund(campaign,'api',increase,evidence=evidence);continue
                    break
                update(project,identifier,knowledge_entries=result.get('knowledge',{}).get('entries',0),training_eligible=bool(result.get('compute_candidate',{}).get('training_gate',{}).get('eligible')))
                if result['status']=='completed':
                    supported=review_support(project,identifier,result) or {}
                    if supported.get('training_eligible'):
                        update(project,identifier,status='support_review',stage='training',
                            blocker='Supported categories have trained, evaluated local checkpoints. Download the model or configure a capped credit-only compute comparison; unsupported categories remain explicitly untrained.')
                        return
                if result['status']!='completed':
                    update(project,identifier,status='blocked',blocker='Saved cohort did not pass its execution or evidence gate. Inspect retained evidence before any further collection.');return
            update(project,identifier,status='paused',blocker='Bounded invocation finished; resume the same saved steps to continue.')
    except Timeout:
        return # Existing worker owns the saved fixed cohort.
    except Exception as error:
        # Provider exception strings can contain URLs or headers. Never echo them.
        message=str(error)
        for secret in secrets_for(project).values():message=message.replace(secret,'[redacted]')
        write(home(project)/('error-'+identifier+'.json'),dict(type=type(error).__name__,message=message[:4000],at=datetime.now(timezone.utc).isoformat()))
        update(project,identifier,status='blocked',blocker='Training stopped safely ('+type(error).__name__+'). Original requests, receipts and reservations are retained.')


def resume_saved(project):
    """Resume interrupted healthy work after app restart; never stopped cohorts."""
    for row in listing(project)['runs']:
        if row['status'] in {'collecting','closing','setting_up'}:launch(project,row['id'])
        elif row['status']=='training':threading.Thread(target=run_compute,args=(str(project),row['id']),daemon=True,name='framebound-compute').start()

FOCUS_CATEGORIES={
    'balanced':['identity','parts','prop','entities','contact','temporal','action_order','artifacts','extraction'],
    'motion':['temporal','contact','action_order'],
    'identity':['identity','parts','prop','artifacts'],
}


def review_support(project,identifier,result=None):
    """Study the requested categories without changing observations or quotas."""
    from ..campaign import continuation,study,learning
    from ..campaign.transfer import inspect_payload
    root=home(project)/'data';campaign='learn-'+identifier;row=snapshot(project,identifier)
    result=result or continuation.latest(root,campaign)
    if not result or 'geometry' not in result.get('studies',{}):
        return update(project,identifier,actions=['resume'],blocker='Finish an admitted evidence batch before reviewing model support.')
    feature=result['studies']['geometry'].get('features',{}).get('path')
    if not feature:return update(project,identifier,actions=['inspect_evidence'],blocker='No valid numeric feature artifact exists in the last closed batch.')
    relative=str(Path(feature).relative_to(root));shard=inspect_payload(Path(feature).read_bytes())
    reports={};eligible=[]
    for category in FOCUS_CATEGORIES[row['focus']]:
        baseline=study.baseline(root,campaign,dict(feature_file=relative,categories=[category]))
        gate=learning.eligibility(shard,[category])
        reports[category]=dict(gate=gate,informative=baseline['report']['informative'])
        if baseline['report']['informative'] and gate['eligible']:eligible.append(category)
    artifact=None;candidate=None
    if eligible:
        baseline=study.baseline(root,campaign,dict(feature_file=relative,categories=eligible))
        profile=study.profile(root,campaign,dict(feature_file=relative,categories=eligible))
        artifact=learning.experiment(root,campaign,shard,categories=eligible)
        candidate=dict(feature_file=relative,categories=eligible,baseline_file=str(Path(baseline['path']).relative_to(root)),
            local_profile_file=str(Path(profile['path']).relative_to(root)),local_training=artifact)
        write(home(project)/('candidate-'+identifier+'.json'),candidate)
    # Public artifact references are identifiers, not unrestricted paths.
    model=dict(status=artifact['card']['status'],checkpoint_count=len(artifact['card']['results']),categories=eligible,
        promoted=False,artifact_id=digest(artifact['card'])) if artifact else dict(status='insufficient_support',checkpoint_count=0,categories=[],promoted=False)
    return update(project,identifier,support=reports,training_eligible=bool(eligible),model=model,
        actions=['configure_compute','download_model'] if artifact else ['review_support','inspect_evidence'],
        compute_status='credit_evidence_required' if artifact else 'not_supported')


class ComputeSetup(Strict):
    available_credit_dollars: Decimal = Field(gt=0,le=100000,decimal_places=2)
    workspace_remaining_dollars: Decimal = Field(gt=0,le=100000,decimal_places=2)
    expires_at: datetime
    source: str = Field(min_length=8,max_length=2000)
    image_digest: str = Field(pattern=r'^sha256:[0-9a-f]{64}$')
    confirm_compute: Literal[True]
    confirm_standard_rates: Literal[True]


def configure_compute(project,actor,identifier,payload):
    """Explicit capped credit-only experiment, using a pinned worker image."""
    require_reviewer(actor,'start_training_compute');spec=ComputeSetup.model_validate(payload)
    if snapshot(project,identifier)['status'] not in {'support_review','completed','paused'}:
        raise ValueError('Finish the active fixed collection batch before starting the compute experiment')
    if not snapshot(project,identifier).get('training_eligible') or not read(home(project)/('candidate-'+identifier+'.json')):
        raise ValueError('Supported local training and a measured workload are required before compute')
    from ..campaign.compute_gate import CreditEvidence
    now=datetime.now(timezone.utc)
    evidence=CreditEvidence(verified_at=now,expires_at=spec.expires_at,source=spec.source,
        restrictions='Operator-confirmed applicable credit; zero uncovered cash; numeric features only',
        available_microdollars=int(spec.available_credit_dollars*1000000),
        workspace_remaining_microdollars=int(spec.workspace_remaining_dollars*1000000),net_spend_remaining_microdollars=0,
        pricing_source='https://modal.com/pricing; operator-confirmed standard rates',
        l4_microdollars_per_second=222,l40s_microdollars_per_second=542,cpu_microdollars_per_core_second=13.1,ram_microdollars_per_gib_second=2.22)
    base=home(project)/'data'/'campaigns'/('learn-'+identifier)/'journey-compute';base.mkdir(parents=True,exist_ok=True)
    frozen=base/'setup.json'
    with FileLock(str(home(project)/('compute-'+identifier+'.lock')),timeout=0), FileLock(str(home(project)/'settings.lock')):
        old=read(frozen)
        setup=dict(image_digest=spec.image_digest,credit=evidence.model_dump(mode='json'))
        if old:
            # Once dispatched, replay the original credit/quote rather than rewriting it.
            if old['image_digest']!=setup['image_digest']:raise ValueError('Compute image is already frozen')
        write(frozen,setup) # Refresh only account evidence, preserving the pinned job image.
    update(project,identifier,status='training',stage='compute',compute_status='checking_evidence',blocker=None)
    threading.Thread(target=run_compute,args=(str(project),identifier),daemon=True,name='framebound-compute').start()
    return snapshot(project,identifier)


def run_compute(project,identifier):
    from ..campaign import study,remote
    from ..campaign.ledger import Ledger
    from ..campaign.compute_gate import CreditEvidence,credit_capacity
    from ..campaign.modal_worker import ModalTransport
    root=home(project)/'data';campaign='learn-'+identifier;base=root/'campaigns'/campaign/'journey-compute'
    try:
        with FileLock(str(home(project)/('compute-'+identifier+'.lock')),timeout=0):
            setup=read(base/'setup.json');candidate=read(home(project)/('candidate-'+identifier+'.json'))
            credit=CreditEvidence.model_validate(setup['credit']);write(base/'credit.json',credit.model_dump(mode='json'))
            write(base/'hypothesis.json',dict(question='Does remote training reduce this exact supported feature workload runtime?',
                success_measure='At least 25 percent measured end-to-end speedup and reproducible matching workload',
                stop_condition='Retain local compute on insufficient speedup; stop on unknown acceptance, credit expiry or any transfer/support gate failure'))
            ledger=Ledger(root)
            with ledger.db() as db:
                unknown=db.execute("SELECT 1 FROM requests WHERE campaign=? AND subsystem='modal' AND state IN ('wire_started','unknown_provider_outcome','provider_pending')",(campaign,)).fetchone()
            if unknown:raise ValueError('Existing remote acceptance is unresolved; no retry is allowed')
            credentials=secrets_for(project)
            import modal
            client=modal.Client.from_credentials(credentials['modal_token_id'],credentials['modal_token_secret'])
            client.hello() # Authenticate without launching a billable container.
            transport=ModalTransport(client=client)
            with ledger.db() as db:
                committed=db.execute("SELECT COALESCE(SUM(COALESCE(incurred,reserved)),0) FROM requests WHERE campaign=? AND subsystem='modal'",(campaign,)).fetchone()[0]
            allocation=min(6000000,committed+credit_capacity(credit))
            ledger.fund(campaign,'modal',allocation,evidence=dict(verified_at=credit.verified_at.isoformat(),source=credit.pricing_source,account_access='Configured Modal credentials authenticated; operator-provided dashboard credit evidence',credit=credit.model_dump(mode='json')))
            evidence=dict(local_profile_file=candidate['local_profile_file'],baseline_file=candidate['baseline_file'],
                credit_file=str((base/'credit.json').relative_to(root)),hypothesis_file=str((base/'hypothesis.json').relative_to(root)))
            from ..campaign.progression import admitted
            case_id=next(iter(sorted(admitted(ledger,ledger.config(campaign)))))
            history=[]
            for purpose in ('profile','train','reproduce'):
                request=dict(feature_file=candidate['feature_file'],categories=candidate['categories'],image_digest=setup['image_digest'],
                    purpose=purpose,seconds=300,startup_seconds=120,replay_seconds=300,study=evidence)
                plan=study.compute_plan(root,campaign,request)
                write(base/(purpose+'-plan.json'),plan)
                if not plan['admitted']:
                    reasons='; '.join(plan['reasons'])
                    local_better='at least 25%' in reasons
                    update(project,identifier,status='completed' if local_better else 'support_review',stage='training',
                        compute_status='local_preferred' if local_better else 'blocked',blocker=reasons,
                        actions=['download_model','review_support'],compute_history=history);return
                job=remote.Job.model_validate(plan['job'])
                update(project,identifier,compute_status=purpose)
                result=remote.submit(ledger,campaign,case_id,(root/candidate['feature_file']).read_bytes(),job,transport,study=evidence)
                write(base/(purpose+'-result.json'),result)
                attempt={'profile':0,'train':1,'reproduce':2}[purpose]
                with ledger.db() as db:
                    rid=db.execute("SELECT id FROM requests WHERE campaign=? AND case_id=? AND operation='train' AND json_extract(request,'$.attempt')=?",(campaign,case_id,attempt)).fetchone()[0]
                history.append(dict(purpose=purpose,request_id=rid,status='received'))
                if purpose=='profile':evidence['remote_profile_request_id']=rid
                elif purpose=='train':evidence['training_request_id']=rid
            trained=read(base/'train-result.json')['result']['result']['temporal']['checkpoint']
            reproduced=read(base/'reproduce-result.json')['result']['result']['temporal']['checkpoint']
            fields=('weights','mean','scale','categories','seed','steps','data_sha256','recipe_sha256','extractor')
            matched=all(trained.get(field)==reproduced.get(field) for field in fields)
            write(base/'reproduction-check.json',dict(matched=matched,fields=list(fields),training_sha256=digest(trained),reproduction_sha256=digest(reproduced),promoted=False))
            if not matched:
                update(project,identifier,status='support_review',stage='training',compute_status='reproduction_mismatch',compute_history=history,
                    blocker='Received reproduction differs from the frozen training checkpoint; no promotion or additional remote sends.',actions=['download_model','review_support']);return
            update(project,identifier,status='completed',stage='training',compute_status='reproduced',compute_history=history,
                blocker=None,actions=['download_model','review_support'])
    except Timeout:return
    except Exception as error:
        update(project,identifier,status='support_review',compute_status='blocked',blocker='Compute stopped safely ('+type(error).__name__+'); inspect preserved plans, credit and acceptance evidence before resuming.',actions=['configure_compute','download_model'])


def model_artifact(project,identifier):
    """Export only the actual local model/card, never corpus or account files."""
    import io,zipfile
    candidate=read(home(project)/('candidate-'+identifier+'.json'))
    if not candidate:raise ValueError('No supported trained model artifact exists yet')
    folder=Path(candidate['local_training']['path']);allowed=home(project)/'data'/'campaigns'/('learn-'+identifier)/'checkpoints'
    if not folder.resolve().is_relative_to(allowed.resolve()):raise ValueError('Model artifact escapes its checkpoint directory')
    result=io.BytesIO()
    with zipfile.ZipFile(result,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in ['model-card.json']+[f'{model}-{seed}.json' for model in ('linear','temporal') for seed in (0,1,2)]:
            path=folder/name
            if path.is_symlink() or not path.is_file():raise ValueError('Incomplete model checkpoint closure')
            archive.writestr(name,path.read_bytes())
    return result.getvalue()


def worker_image():
    """Resolve the public base image to immutable bytes, without any paid job."""
    from urllib.parse import urlencode
    from re import fullmatch
    url='https://auth.docker.io/token?'+urlencode(dict(service='registry.docker.io',scope='repository:library/python:pull'))
    with urlopen(Request(url),timeout=20) as response:
        token=json.loads(response.read(65536))['token']
    request=Request('https://registry-1.docker.io/v2/library/python/manifests/3.11-slim',method='HEAD',headers={
        'Authorization':'Bearer '+token,'Accept':'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json'})
    with urlopen(request,timeout=20) as response:digest_value=response.headers.get('Docker-Content-Digest','')
    if not fullmatch(r'sha256:[0-9a-f]{64}',digest_value):raise ValueError('Registry did not return a pinned image digest')
    return dict(image='python:3.11-slim',image_digest=digest_value,source='https://hub.docker.com/_/python',verified_at=datetime.now(timezone.utc).isoformat())
