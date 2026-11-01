"""Scope/denominator reporting; no invented accuracy for incomplete labels."""
from collections import Counter,defaultdict
import json
from pathlib import Path

from .assessment import CATEGORIES
from .contracts import digest
from .experiment import controls,paired_report
from .ledger import Ledger


def build(root,campaign):
    ledger=Ledger(root);config=ledger.config(campaign);status=ledger.status(campaign)
    from .progression import admitted
    allowed=admitted(ledger,config)
    released=[c for c in config.cases if c.id in allowed]
    stage=config.phase
    if config.schema_version=='2.0':
        with ledger.db() as db:
            stages={r[0].split(':')[0] for r in db.execute('SELECT stage FROM knowledge_releases WHERE campaign=?',(campaign,))}
        stage='final' if 'final' in stages else 'expansion' if 'expansion' in stages else 'pilot' if 'pilot' in stages else 'rehearsal'
    categories={c:Counter() for c in CATEGORIES};strata=defaultdict(Counter);cases=[];control_rows=[];exclusions=[]
    allocation={r['case_id'] for r in controls(config)['cases']}
    for case in released:
        p=ledger.progress(campaign,case.id);result=p['result']
        cases.append(dict(case_id=case.id,family=case.family,state=p['state'],active_seconds=p['active_seconds'],outcome=result.get('outcome',p['state']) if result else None))
        strata[case.treatment+':C'+str(case.level)+':'+case.action][p['state']]+=1
        a=(result or {}).get('after_assessment') or (result or {}).get('assessment')
        coverage={c['category']:c for c in a['coverage']} if a else {}
        for category in CATEGORIES:
            categories[category][coverage.get(category,{}).get('status','not_assessed')]+=1
        if case.id in allocation:
            if result and result.get('control'):control_rows.extend(result['control']['rows'])
            elif result and not result.get('authority_id'):exclusions.append(dict(case_id=case.id,reason='No corroborated actionable target before intervention'))
            else:
                attempted=any(r['case_id']==case.id and r['operation']=='repair' for r in status['requests'])
                if attempted:
                    control_rows.extend(dict(case_id=case.id,family=case.family,arm=arm,outcome='missing') for arm in ('guided_edit','blind_rerun'))
    if config.schema_version=='2.0':
        # The full frozen allocation remains visible even before expansion releases it.
        accounted={r['case_id'] for r in control_rows}|{r['case_id'] for r in exclusions}
        for cid in sorted(allocation-accounted):
            case=next(c for c in config.cases if c.id==cid)
            control_rows.extend(dict(case_id=cid,family=case.family,arm=arm,outcome='missing')
                                for arm in ('guided_edit','blind_rerun'))
    requests=status['requests']
    generation_requests=[r for r in requests if r['operation']=='generate']
    generated={r['case_id'] for r in generation_requests if r['receipt'] and json.loads(r['receipt'])['successful_images']>0}
    unknown={r['case_id'] for r in requests if r['state'] in {'wire_started','provider_pending','unknown_provider_outcome'}}
    return dict(schema_version='animation-campaign-report-1.0',campaign=campaign,config_sha256=digest(config),phase=stage,
        denominators=dict(requested=len(released),generated=len(generated),canonicalized=sum(bool(ledger.progress(campaign,c.id)['data'].get('base_revision')) for c in released),
            assessed=sum(bool((ledger.progress(campaign,c.id)['result'] or {}).get('after_assessment') or (ledger.progress(campaign,c.id)['result'] or {}).get('assessment')) for c in released),
            terminal=sum(c['outcome'] is not None for c in cases),unknown_provider_cases=len(unknown),families=len({c.family for c in released})),
        execution=status,cases=cases,categories={c:dict(v) for c,v in categories.items()},strata={s:dict(v) for s,v in strata.items()},
        controls=paired_report(control_rows),control_exclusions=exclusions,
        control_allocation=dict(allocated=len(allocation),excluded_before_intervention=len(exclusions)),
        accuracy_status='insufficient_support; scoped labels, localization and calibration require explicit evaluation evidence',
        cost_basis='Integer microdollars; unreconciled provider reservations/upper bounds remain identified in receipts',
        label_scope='Model evidence with explicit coverage; no human-ground-truth or hosted-generator fine-tuning claim')
