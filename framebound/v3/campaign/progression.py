"""Evidence-backed acquisition releases. Frozen specifications and spend survive."""
import json
import math

from .assessment import Assessment
from .contracts import canonical, digest, local_path
from .curriculum import protocol
from .ledger import Ledger, Stopped


def admitted(ledger, config, db=None):
    if config.schema_version != '2.0':
        return {c.id for c in config.cases if c.stage == config.phase}
    def read(connection):
        rows=connection.execute('SELECT cases FROM knowledge_releases WHERE campaign=?',(config.id,)).fetchall()
        return set(protocol(config)['rehearsal']).union(*(set(json.loads(r[0])) for r in rows))
    if db is not None:
        return read(db)
    with ledger.db() as connection:
        return read(connection)


def cohort_evidence(ledger,config,ids):
    rows=[];assessed=0;intake_failed=0
    for cid in ids:
        p=ledger.progress(config.id,cid)
        result=p['result']
        a=(result or {}).get('after_assessment') or (result or {}).get('assessment')
        if a:
            parsed=Assessment.model_validate(a)
            if any(c.status in {'present','absent_within_assessed_scope'} and c.slots for c in parsed.coverage):
                assessed+=1
        if (result or {}).get('intake'):
            intake_failed+=int(any(not i['eligible'] for i in result['intake']))
        rows.append(dict(case_id=cid,terminal=bool(result),result_sha256=digest(result)))
    status=ledger.status(config.id)
    unknown=[r['id'] for r in status['requests'] if r['state'] in {'wire_started','unknown_provider_outcome'}]
    received=[r for r in status['requests'] if r['case_id'] in ids and r['state']=='received']
    errors=[]
    for r in received:
        try:ledger.artifact(r['id'])
        except (ValueError,OSError):errors.append(r['id'])
    reasons=[]
    if any(not r['terminal'] for r in rows):reasons.append('cohort has unfinished cases')
    if assessed < math.ceil(len(ids)*.75):reasons.append('fewer than 75% of allocated cases have usable scoped assessments')
    if intake_failed > len(ids)*.25:reasons.append('more than 25% of allocated cases failed intake')
    if unknown:reasons.append('provider outcomes need reconciliation')
    if errors:reasons.append('receipt closure is missing or changed')
    if not received:reasons.append('cohort has no actual provider receipts')
    return dict(passed=not reasons,reasons=reasons,allocated=len(ids),scoped_assessed=assessed,
                intake_failed=intake_failed,results=rows,request_ids=[r['id'] for r in received],receipt_errors=errors)


def release(root,campaign,request):
    ledger=Ledger(root);config=ledger.config(campaign)
    if config.schema_version!='2.0':raise ValueError('versioned release workflow requires an MVP v2 campaign')
    stage=request['stage'];plan=protocol(config)
    stage_key=stage
    if stage=='expansion':
        from .contracts import Identity
        stage_key+=':'+Identity(id=request['batch']).id
    with ledger.db() as db:
        previous=db.execute('SELECT * FROM knowledge_releases WHERE campaign=? AND stage=?',(campaign,stage_key)).fetchone()
    if previous:
        if previous['request'] != canonical(request).decode():raise ValueError('release is immutable; original request must be replayed')
        return json.loads(previous['evidence'])
    if stage not in {'pilot','expansion','final'}:raise ValueError('supported release stage required')
    predecessor='rehearsal' if stage=='pilot' else 'pilot'
    evidence=cohort_evidence(ledger,config,plan[predecessor])
    if not evidence['passed']:raise Stopped('; '.join(evidence['reasons']))
    selected=plan[stage]
    detail={}
    if stage=='expansion':
        from .study import verify_baseline
        from .experiment import adaptive
        baseline=verify_baseline(root,campaign,request['baseline_file'])
        mode=request.get('mode','representative')
        if mode=='adaptive':
            if not baseline['informative']:raise Stopped('adaptive expansion requires an informative evaluated local baseline')
            candidates=request['candidates']
            selection=adaptive(config,candidates,size=request['size'],evidence=dict(pilot_gate_passed=True,detector_evaluated=True,
                baseline_sha256=digest(baseline),cohort_sha256=digest(evidence)))
        elif mode=='representative':
            # Outcome-blind collection fills support gaps before a detector is trainable.
            size=request['size']
            if type(size) is not int or not 1<=size<=80:raise ValueError('representative tranche size must be 1..80')
            already=admitted(ledger,config)
            available=[cid for cid in plan['expansion'] if cid not in already]
            ordered=sorted(available,key=lambda cid:digest([config.seed,request['batch'],'representative-expansion',cid]))
            count=min(size,len(ordered))
            selection=dict(selected=[dict(case_id=cid,selection_probability=count/len(available),eligible_pool=len(available))
                for cid in ordered[:count]],requested=size,shortfall=size-count,policy='outcome-blind representative support collection',
                config_sha256=digest(config),baseline_sha256=digest(baseline))
        else:raise ValueError('expansion mode must be representative or adaptive')
        selected=[s['case_id'] for s in selection['selected']]
        with ledger.db() as db:
            already=admitted(ledger,config,db)
        if any(cid in already for cid in selected):raise Stopped('expansion cannot replenish an already released case')
        detail=dict(mode=mode,selection=selection,baseline_sha256=digest(baseline))
    elif stage=='final':
        from .study import final_evidence
        detail=final_evidence(root,campaign,request)
    if not selected:raise Stopped('release selected no cases')
    value=dict(schema_version='knowledge-release-1.0',campaign=campaign,stage=stage,config_sha256=digest(config),
               case_ids=selected,evidence=evidence,detail=detail)
    with ledger.db() as db:
        db.execute('BEGIN IMMEDIATE')
        if stage=='expansion' and db.execute("SELECT 1 FROM knowledge_releases WHERE campaign=? AND stage='final'",(campaign,)).fetchone():
            raise Stopped('development acquisition is frozen for final evaluation')
        if stage=='expansion' and any(cid in admitted(ledger,config,db) for cid in selected):
            raise Stopped('concurrent expansion already released a selected case')
        # Recheck provider stops atomically with the new release.
        if db.execute('SELECT stopped FROM campaigns WHERE id=?',(campaign,)).fetchone()[0]:raise Stopped('campaign stopped')
        if db.execute("SELECT 1 FROM requests WHERE campaign=? AND state IN ('wire_started','unknown_provider_outcome')",(campaign,)).fetchone():
            raise Stopped('provider outcomes need reconciliation')
        db.execute('INSERT INTO knowledge_releases(campaign,stage,cases,evidence,request) VALUES(?,?,?,?,?)',
            (campaign,stage_key,canonical(selected).decode(),canonical(value).decode(),canonical(request).decode()))
        ledger._event(db,None,'knowledge_release',dict(campaign=campaign,stage=stage,evidence_sha256=digest(value)))
    return value


def readiness(root,campaign):
    ledger=Ledger(root);config=ledger.config(campaign)
    plan=protocol(config) if config.schema_version=='2.0' else None
    with ledger.db() as db:
        releases=[dict(r) for r in db.execute('SELECT stage,evidence FROM knowledge_releases WHERE campaign=?',(campaign,))]
        funding=dict(db.execute('SELECT api_funding,modal_funding FROM campaigns WHERE id=?',(campaign,)).fetchone())
    status=ledger.status(campaign)
    feature_gates=[]
    from .transfer import inspect_payload
    from .learning import eligibility
    for path in sorted(local_path(root,f'campaigns/{campaign}/features').glob('*/features.json')):
        shard=inspect_payload(path.read_bytes())
        feature_gates.append(dict(version=path.parent.name,extractor=shard.extractor,
            gate=eligibility(shard,plan['initial_categories'] if plan else ['temporal','artifacts'])))
    return dict(schema_version='knowledge-readiness-1.0',campaign=campaign,protocol=plan,
                admitted_cases=len(admitted(ledger,config)),releases=[r['stage'] for r in releases],
                rehearsal=cohort_evidence(ledger,config,plan['rehearsal']) if plan else None,
                pilot=cohort_evidence(ledger,config,plan['pilot']) if plan else None,
                funding_microdollars=funding,budgets=status['budgets'],feature_gates=feature_gates,model_calls=0,
                next_action='Complete rehearsal before pilot; run local baseline before targeted expansion; profile before Modal training.',
                limitations=['Planning and release never allocate funding.', 'Readiness does not certify creative quality or credit eligibility.'])


def quarantine(root,campaign,request):
    """Close a known unsuitable acquisition; never infer nonacceptance or resend."""
    ledger=Ledger(root);config=ledger.config(campaign);cid=request['case_id']
    if cid not in admitted(ledger,config):raise ValueError('quarantine must target an admitted case')
    folder=local_path(root,f'campaigns/{campaign}/reports')
    report_path=local_path(root,request['failure_report'])
    if report_path.parent!=folder or not report_path.name.startswith('failure-'):
        raise ValueError('quarantine requires this campaign\'s actual saved acquisition failure')
    report=json.loads(report_path.read_text())
    if report['case_id']!=cid or report['error']!='ValueError':
        raise ValueError('failure report does not identify a known unsuitable acquisition')
    permitted=('declared flat magenta key','wrong-size sheet','No substantial declared magenta surround',
               'Background or clipped subject','Opaque background','matte versus subject')
    if not any(text in report['detail'] for text in permitted):
        raise ValueError('execution/schema failures are not artistic or intake rejections')
    if ledger.progress(campaign,cid)['data'].get('base_revision'):
        raise ValueError('initial acquisition quarantine cannot relabel a failure after candidate assessment')
    status=ledger.status(campaign)
    requests=[r for r in status['requests'] if r['case_id']==cid]
    if not requests or any(r['state'] not in {'received','cancelled'} for r in requests):
        raise Stopped('quarantine cannot resolve a pending or unknown provider outcome')
    for r in requests:
        if r['state']=='received':ledger.artifact(r['id'])
    from ..intake import VERSION
    result=dict(outcome='rejected',reason='Unsuitable acquisition rejected before semantic assessment',
        failure_sha256=digest(report),request_ids=[r['id'] for r in requests],
        intake=[dict(policy=VERSION,eligible=False,reasons=[report['detail']],
            semantic_scope='Source acquisition/layout/extraction evidence; no semantic or artistic assessment')])
    ledger.finish_case(campaign,cid,'rejected',result)
    return dict(result=result,stopped=ledger.status(campaign)['stopped'],
        next_action='Inspect the saved source; explicit resume may continue other admitted cases without resending this case.')
