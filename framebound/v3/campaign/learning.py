"""Small, reproducible feature-based baselines with masked supervision.

No teacher confidence is treated as a truth probability. The temporal baseline
uses adjacent-frame context; spatial/anatomical localization is unsupported.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import numpy as np

from .assessment import CATEGORIES
from .contracts import canonical, digest
from .transfer import FeatureShard

RECIPE = dict(version='masked-feature-head-v1',learning_rate=0.05,steps=200,seeds=[0,1,2],
    unknown_loss='masked',features='native-numeric-v1',checkpoint_seconds=600)


def eligibility(shard: FeatureShard, categories):
    rows=[r for r in shard.rows if r.split=='train']
    support={c:sum(r.assessed[CATEGORIES.index(c)] and r.targets[CATEGORIES.index(c)]==1 for r in rows) for c in categories}
    reasons=[]
    if len(rows)<300: reasons.append('requires 300 distinct training sequences')
    if len({r.family_id for r in rows})<75: reasons.append('requires 75 training families')
    for c,count in support.items():
        if count<30: reasons.append(f'{c}: requires 30 explicitly labeled positive sequences')
    if not categories: reasons.append('no advertised learned categories')
    return dict(eligible=not reasons,sequences=len(rows),families=len({r.family_id for r in rows}),positive_support=support,reasons=reasons)


def _design(features, model):
    x=np.asarray(features,dtype=np.float64)
    if model=='linear': return x
    if model!='temporal': raise ValueError('unknown feature head')
    # Frozen local temporal receptive field; learned category heads operate at
    # each native window rather than averaging an animation before inference.
    previous=np.concatenate([x[:1],x[:-1]])
    following=np.concatenate([x[1:],x[-1:]])
    return np.concatenate([x,previous,following,x-previous],axis=1)


def _sequence_vectors(rows,model):
    # Sequence losses use max evidence across native windows. Prediction also
    # returns every window so evidence is not lost in a clip average.
    return [_design(r.features,model) for r in rows]


def _sigmoid(z): return 1/(1+np.exp(-np.clip(z,-40,40)))


def fit(shard: FeatureShard, *, categories, model='linear', seed=0, steps=200, engineering=False, checkpoint=None):
    if any(c not in CATEGORIES for c in categories): raise ValueError('unsupported category')
    gate=eligibility(shard,categories)
    if not gate['eligible'] and not engineering: return dict(status='insufficient_support',gate=gate,checkpoint=None)
    rows=[r for r in shard.rows if r.split=='train']
    if not rows: raise ValueError('training split is empty')
    xs=_sequence_vectors(rows,model)
    mean=np.concatenate(xs).mean(axis=0);scale=np.maximum(np.concatenate(xs).std(axis=0),1e-6)
    xs=[(x-mean)/scale for x in xs]
    ys=np.asarray([r.targets for r in rows],dtype=float)
    masks=np.asarray([r.assessed for r in rows],dtype=float)
    included=np.asarray([c in categories for c in CATEGORIES],dtype=float)
    masks*=included
    weights=np.asarray([r.weight for r in rows])[:,None]
    rng=np.random.default_rng(seed)
    w=rng.normal(0,0.01,(xs[0].shape[1],9));b=np.zeros(9)
    start=time.monotonic();last_checkpoint=start
    for step in range(steps):
        dw=np.zeros_like(w);db=np.zeros_like(b);loss=0.
        denom=max(float((masks*weights).sum()),1.)
        for index,x in enumerate(xs):
            scores=x@w+b
            selected=np.argmax(scores,axis=0)
            logits=scores[selected,np.arange(9)]
            p=_sigmoid(logits)
            multiplier=masks[index]*weights[index]/denom
            delta=(p-ys[index])*multiplier
            dw+=x[selected].T*delta
            db+=delta
            loss+=float(np.sum((np.logaddexp(0,logits)-ys[index]*logits)*multiplier))
        w-=RECIPE['learning_rate']*dw;b-=RECIPE['learning_rate']*db
        if checkpoint and time.monotonic()-last_checkpoint>=600:
            checkpoint(dict(step=step,weights=w.tolist(),bias=b.tolist(),seed=seed))
            last_checkpoint=time.monotonic()
    artifact=dict(schema_version='feature-detector-1.0',model=model,weights=w.tolist(),bias=b.tolist(),mean=mean.tolist(),scale=scale.tolist(),
        categories=categories,seed=seed,steps=steps,recipe=RECIPE,data_sha256=digest(shard),engineering_only=engineering,
        seconds=time.monotonic()-start,loss=loss,unsupported=['spatial ROI','severity','anatomy semantics without evaluated labels'])
    if checkpoint: checkpoint(dict(step=steps,artifact=artifact))
    return dict(status='trained',gate=gate,checkpoint=artifact)


def predict(artifact, row):
    x=_design(row.features,artifact['model'])
    x=(x-np.asarray(artifact['mean']))/np.asarray(artifact['scale'])
    windows=_sigmoid(x@np.asarray(artifact['weights'])+np.asarray(artifact['bias']))
    scores=windows.max(axis=0)
    return dict(scores={c:float(scores[i]) if c in artifact['categories'] else None for i,c in enumerate(CATEGORIES)},
                windows=windows.tolist(),roi=None,calibration='uncalibrated score; use held-out selective thresholds')


def wilson(successes,n,z=1.96):
    if not n: return None
    p=successes/n;d=1+z*z/n;center=(p+z*z/(2*n))/d
    radius=z*np.sqrt(p*(1-p)/n+z*z/(4*n*n))/d
    return [max(0.,float(center-radius)),min(1.,float(center+radius))]


def calibrate(artifact,shard: FeatureShard):
    rows=[r for r in shard.rows if r.split=='validation']
    metrics={}
    for c in artifact['categories']:
        i=CATEGORIES.index(c);assessed=[r for r in rows if r.assessed[i]]
        scored=[(r,predict(artifact,r)['scores'][c]) for r in assessed]
        curves=[]
        for threshold in (0.5,0.6,0.7,0.8,0.9,0.95,0.99):
            positives=[r for r,s in scored if s>=threshold]
            tp=sum(r.targets[i] for r in positives);n=len(positives)
            negatives=[r for r in assessed if r.challenge and not r.targets[i]]
            fp=sum(predict(artifact,r)['scores'][c]>=threshold for r in negatives)
            curves.append(dict(threshold=threshold,precision=tp/n if n else None,precision_interval=wilson(tp,n),positive_support=n,
                recall=tp/sum(r.targets[i] for r in assessed) if any(r.targets[i] for r in assessed) else None,
                coverage=n/len(rows) if rows else 0,assessed_support=len(assessed),abstained=len(rows)-len(assessed),
                challenge_support=len(negatives),challenge_fpr=fp/len(negatives) if negatives else None))
        eligible=[v for v in curves if v['positive_support']>=30 and v['precision']>=0.9 and v['challenge_support']>=100 and v['challenge_fpr']<=0.05]
        selected=max(eligible,key=lambda v:v['coverage']) if eligible else None
        metrics[c]=dict(selected=selected,curves=curves,status='eligible_for_comparison' if selected else 'insufficient_support_or_quality')
    return dict(split='validation_only',categories=metrics,promoted=False,
        limitation='Scoped model-label accuracy, not independently established human truth. Repair control and recall-regression gates remain required.')


def fit_ranker(pairs, *, seed=0, steps=200):
    valid=[p for p in pairs if p['split']=='train' and p.get('preference') in {'baseline','candidate'} and p.get('assessed',False)]
    if len(valid)<30 or len({p['family'] for p in valid})<10:
        return dict(status='insufficient_support',pairs=len(valid),checkpoint=None)
    x=np.asarray([np.asarray(p['candidate_features'])-np.asarray(p['baseline_features']) for p in valid],dtype=float)
    if x.ndim!=2 or not np.isfinite(x).all(): raise ValueError('ranker requires finite derived vectors')
    y=np.asarray([p['preference']=='candidate' for p in valid],dtype=float)
    w=np.zeros(x.shape[1]);b=0.
    for _ in range(steps):
        d=_sigmoid(x@w+b)-y;w-=0.05*x.T@d/len(y);b-=0.05*float(d.mean())
    return dict(status='trained',checkpoint=dict(weights=w.tolist(),bias=b,seed=seed,steps=steps,pairs_sha256=digest(valid)),
        promoted=False,limitation='Validation calibration, untouched family evaluation and repair-control gates required')


def train_temporal_torch(shard, *, categories, seed=0, steps=200, checkpoint=None, device=None):
    """Optional trainable temporal convolution with masked sequence supervision."""
    gate=eligibility(shard,categories)
    if not gate['eligible']: return dict(status='insufficient_support',gate=gate,checkpoint=None)
    import torch
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    rows=[r for r in shard.rows if r.split=='train']
    device=device or ('cuda' if torch.cuda.is_available() else 'cpu')
    frames=torch.zeros((len(rows),24,8),dtype=torch.float32,device=device)
    valid=torch.zeros((len(rows),24),dtype=torch.bool,device=device)
    for n,row in enumerate(rows):
        frames[n,:len(row.features)]=torch.tensor(row.features,device=device)
        valid[n,:len(row.features)]=True
    mean=frames[valid].mean(dim=0);scale=frames[valid].std(dim=0).clamp_min(1e-6)
    frames=(frames-mean)/scale
    frames[~valid]=0
    targets=torch.tensor([r.targets for r in rows],dtype=torch.float32,device=device)
    assessed=torch.tensor([r.assessed for r in rows],dtype=torch.float32,device=device)
    assessed*=torch.tensor([c in categories for c in CATEGORIES],device=device)
    assessed*=torch.tensor([r.weight for r in rows],device=device)[:,None]
    model=torch.nn.Sequential(torch.nn.Conv1d(8,32,3,padding=1),torch.nn.GELU(),torch.nn.Conv1d(32,9,1)).to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=0.001)
    started=time.monotonic();saved=started
    for step in range(steps):
        optimizer.zero_grad()
        windows=model(frames.transpose(1,2)).transpose(1,2)
        windows=windows.masked_fill(~valid[:,:,None],-1e9)
        logits=windows.max(dim=1).values
        loss=(torch.nn.functional.binary_cross_entropy_with_logits(logits,targets,reduction='none')*assessed).sum()/assessed.sum().clamp_min(1)
        loss.backward();optimizer.step()
        if time.monotonic()-started>3300: break
        if checkpoint and time.monotonic()-saved>=600:
            checkpoint(dict(step=step,weights={k:v.detach().cpu().tolist() for k,v in model.state_dict().items()}))
            saved=time.monotonic()
    artifact=dict(schema_version='temporal-convolution-1.0',weights={k:v.detach().cpu().tolist() for k,v in model.state_dict().items()},
        mean=mean.cpu().tolist(),scale=scale.cpu().tolist(),categories=categories,seed=seed,steps=step+1,
        data_sha256=digest(shard),torch_version=torch.__version__,device=device,loss=float(loss.item()),seconds=time.monotonic()-started,
        unsupported=['ROI without patch labels','anatomical correctness without evaluation'])
    if checkpoint: checkpoint(dict(step=step+1,artifact=artifact))
    return dict(status='trained',gate=gate,checkpoint=artifact)


def experiment(root, campaign, shard: FeatureShard, *, categories):
    from .contracts import local_path
    gate=eligibility(shard,categories)
    folder=local_path(root,f'campaigns/{campaign}/checkpoints/{digest(shard)}')
    folder.mkdir(parents=True,exist_ok=True)
    results=[]
    if gate['eligible']:
        for model in ('linear','temporal'):
            for seed in RECIPE['seeds']:
                trained=fit(shard,categories=categories,model=model,seed=seed)
                calibration=calibrate(trained['checkpoint'],shard)
                filename=f'{model}-{seed}.json';raw=canonical(trained['checkpoint'])
                (folder/filename).write_bytes(raw)
                results.append(dict(model=model,seed=seed,sha256=hashlib.sha256(raw).hexdigest(),calibration=calibration))
    card=dict(schema_version='animation-model-card-1.0',status='evaluated_candidates' if results else 'insufficient_support',
        gate=gate,recipe=RECIPE,data_sha256=digest(shard),results=results,promoted=False,
        limitations=['Eight local numeric measurements have a limited semantic ceiling.',
            'No human-ground-truth accuracy claim.', 'Repair-controls and unseen-family evaluation required before promotion.'])
    (folder/'model-card.json').write_bytes(canonical(card))
    return dict(path=str(folder),card=card)
