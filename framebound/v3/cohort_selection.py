"""Bounded candidate retrieval by joint profile continuity, never acceptance."""
import itertools
import math


def select_profiles(candidates,*,max_drift=.12,combination_limit=1_000_000):
    """Choose the tightest complete cohort within frozen width bounds.

    Callers must independently verify source framing, identity, items and motion.
    Unknown profiles cannot be scored as zero or silently selected.
    """
    if not 0<max_drift<=.3 or combination_limit<1:raise ValueError('Invalid selection bounds')
    ids=list(candidates)
    if not ids:return None
    pool={}
    for fid,rows in candidates.items():
        pool[fid]=[row for row in rows if isinstance(row.get('profile'),(list,tuple)) and len(row['profile'])==2 and all(isinstance(v,(int,float)) and math.isfinite(v) and v>0 for v in row['profile'])]
        if not pool[fid]:return None
    if math.prod(len(rows) for rows in pool.values())>combination_limit:raise ValueError('Candidate retrieval exceeds explicit combination budget')
    best=None
    for rows in itertools.product(*(pool[fid] for fid in ids)):
        ratios=[max(r['profile'][k] for r in rows)/min(r['profile'][k] for r in rows) for k in (0,1)]
        worst=max(ratios)
        if worst<=1+max_drift and (best is None or worst<best['worst_ratio']):
            best=dict(frames=dict(zip(ids,rows)),ratios=ratios,worst_ratio=worst,scope='Profile candidate retrieval only; semantic, item, motion and framing review required',accepted=False)
    return best
