"""Outcome-blind controls, bounded adaptive selection and honest family metrics."""
from __future__ import annotations

from collections import defaultdict
import random

import numpy as np

from .contracts import Campaign, canonical, digest


def controls(config: Campaign):
    """Two of four actions per validation treatment/level: 80 cases, 40 families."""
    strata=defaultdict(list)
    for c in config.cases:
        if c.split=='validation': strata[(c.treatment,c.level)].append(c)
    rows=[]
    for key,group in sorted(strata.items()):
        ordered=sorted(group,key=lambda c:digest([config.seed,'controls',c.id]))
        for case in ordered[:2]:
            rows.append(dict(case_id=case.id,family=case.family,arms=['guided_edit','blind_rerun','baseline'],
                selection_probability=2/len(group),stratum=list(key),intent_to_treat=True))
    return dict(schema_version='paired-controls-1.0',config_sha256=digest(config),cases=rows,
        primary_outcome='target improved without material assessed regressions per allocated attempt',
        analysis_unit='identity_family',failed_generation_counts_as_improvement=False)


def adaptive(config: Campaign, candidates, *, size, evidence):
    if not evidence.get('pilot_gate_passed') or not evidence.get('detector_evaluated'):
        raise ValueError('adaptive expansion requires repair and detector evidence')
    if type(size) is not int or size<1 or size>720: raise ValueError('bounded expansion size required')
    specs={c.id:c for c in config.cases if c.split!='test' and c.stage=='expansion'}
    if len({c['id'] for c in candidates})!=len(candidates): raise ValueError('duplicate adaptive candidates')
    groups=defaultdict(list)
    for c in candidates:
        if c['id'] not in specs: raise ValueError('adaptive collection cannot use test or previously released cases')
        bucket='challenge' if specs[c['id']].challenge_negative else 'disagreement' if c.get('uncertain') else 'recurring' if c.get('supported_failure') else 'random'
        groups[bucket].append(c['id'])
    quota={'recurring':int(size*.4),'disagreement':int(size*.3),'challenge':int(size*.2)}
    quota['random']=size-sum(quota.values())
    selected=[];shortfalls={}
    for bucket,count in quota.items():
        pool=sorted(groups[bucket]);rng=random.Random(digest([config.seed,bucket,size,digest(evidence)]));rng.shuffle(pool)
        n=min(count,len(pool));shortfalls[bucket]=count-n
        selected.extend(dict(case_id=cid,bucket=bucket,selection_probability=n/len(pool),eligible_pool=len(pool)) for cid in pool[:n])
    return dict(config_sha256=digest(config),evidence_sha256=digest(evidence),selected=selected,requested=size,
        quota=quota,shortfalls=shortfalls,representative_evaluation=False)


def representative_cohort(config: Campaign, *, size=80):
    candidates=[c for c in config.cases if c.split=='validation']
    ordered=sorted(candidates,key=lambda c:digest([config.seed,'representative',c.id]))
    count=min(size,len(ordered))
    return dict(cases=[c.id for c in ordered[:count]],selection_probability=count/len(candidates),
                policy='fixed before observing defects; keep separate from adaptive rates')


def paired_report(rows, *, seed=0, samples=2000):
    """All allocated attempts stay in denominators, including failures/unknowns."""
    by_case={}
    allowed={'improved','unchanged','regressed','ambiguous','provider_failure','unknown_provider_outcome','missing'}
    for row in rows:
        if row['arm'] not in {'guided_edit','blind_rerun'} or row['outcome'] not in allowed: raise ValueError('unknown experiment result')
        key=(row['case_id'],row['arm'])
        if key in by_case: raise ValueError('duplicate control arm')
        by_case[key]=row
    ids=sorted({r['case_id'] for r in rows});families=defaultdict(list)
    outcomes=defaultdict(int)
    for cid in ids:
        pair=[by_case.get((cid,a)) for a in ('guided_edit','blind_rerun')]
        if any(r is None for r in pair): raise ValueError('every allocated case must retain both arm outcomes')
        if pair[0]['family']!=pair[1]['family']: raise ValueError('paired family mismatch')
        delta=int(pair[0]['outcome']=='improved')-int(pair[1]['outcome']=='improved')
        families[pair[0]['family']].append(delta)
        for r in pair: outcomes[r['arm']+':'+r['outcome']]+=1
    if not families:
        return dict(status='insufficient_support',allocated_cases=0,confidence_interval=None,promoted=False)
    # Cluster-resample whole families, preserving all actions within a family.
    groups=list(families.values());rng=np.random.default_rng(seed);draws=[]
    for _ in range(samples):
        selected=[groups[i] for i in rng.integers(0,len(groups),len(groups))]
        draws.append(sum(sum(v) for v in selected)/sum(len(v) for v in selected))
    interval=np.quantile(draws,[.025,.975]).tolist() if len(groups)>=2 else None
    effect=sum(sum(v) for v in groups)/sum(len(v) for v in groups)
    uncertain=any(r['outcome'] in {'unknown_provider_outcome','missing','ambiguous'} for r in rows)
    guided_regressions=sum(r['outcome']=='regressed' and r['arm']=='guided_edit' for r in rows)
    blind_regressions=sum(r['outcome']=='regressed' and r['arm']=='blind_rerun' for r in rows)
    promote=bool(interval and interval[0]>0 and len(groups)>=30 and not uncertain and guided_regressions<=blind_regressions)
    return dict(status='evaluated' if len(groups)>=30 else 'insufficient_support',allocated_cases=len(ids),families=len(groups),
        improvement_difference=effect,confidence_interval=interval,outcomes=dict(outcomes),promoted=promote,
        label_scope='model-judged scoped improvement; family-clustered intervals, failures retained')


def promotion(calibration, experiment_report, *, previous_recall=None):
    reasons=[]
    for category,metric in calibration['categories'].items():
        selected=metric['selected']
        if selected is None: reasons.append(category+': insufficient validation support or quality')
        elif previous_recall and category in previous_recall and selected['recall'] is not None and selected['recall']<previous_recall[category]-.05:
            reasons.append(category+': recall loss exceeds five percentage points')
    if not calibration['categories']: reasons.append('no supported learned categories')
    if not experiment_report['promoted']: reasons.append('guided edits have not passed matched blind-rerun comparison')
    return dict(promoted=not reasons,reasons=reasons,retained_previous_best=bool(reasons))


def freeze_final(config: Campaign, *, detector_sha256, policy_sha256, prompts_sha256, preprocessing_sha256, evidence):
    for sha in (detector_sha256,policy_sha256,prompts_sha256,preprocessing_sha256):
        if len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha): raise ValueError('freeze requires actual artifact hashes')
    if not evidence.get('promotion_passed'): raise ValueError('final test requires frozen promoted policy evidence')
    specs=[c.model_dump(mode='json') for c in config.cases if c.split=='test']
    if len(specs)!=160: raise ValueError('final cohort must retain all 160 frozen test specifications')
    return dict(schema_version='frozen-final-evaluation-1.0',cases=specs,detector_sha256=detector_sha256,policy_sha256=policy_sha256,
        prompts_sha256=prompts_sha256,preprocessing_sha256=preprocessing_sha256,config_sha256=digest(config),adaptation_allowed=False)
