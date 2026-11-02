"""Conservative family/shared-input/pixel/near-duplicate split quarantine."""
from collections import defaultdict
from functools import lru_cache

import numpy as np
from PIL import Image


def legacy_exclusions(examples, dataset):
    parent={e['metadata']['id']:e['metadata']['id'] for e in examples}
    def find(value):
        while parent[value]!=value:
            parent[value]=parent[parent[value]];value=parent[value]
        return value
    def union(a,b):
        parent[find(a)]=find(b)
    owners={};seen={};buckets=defaultdict(set)
    for example in examples:
        row=example['metadata'];rid=row['id']
        keys=[('family',f) for f in [row['family'],*row.get('ancestry',[])]]
        keys.extend(('pixels',a['sha256']) for a in [*row['frames'],*row['conditioning']])
        for key in keys:
            if key in owners:union(rid,owners[key])
            owners[key]=rid
        for artifact in [*row['frames'],*row['conditioning']]:
            with Image.open(dataset/artifact['file']) as im:
                rgba=im.convert('RGBA');base=Image.new('RGBA',rgba.size,(0,0,0,255));base.alpha_composite(rgba)
                gray=np.asarray(base.convert('L').resize((9,8),Image.Resampling.LANCZOS))
            bits=(gray[:,1:]>gray[:,:-1]).ravel();value=sum(int(bit)<<i for i,bit in enumerate(bits))
            if value in seen:
                union(rid,seen[value]);continue
            parts=[(i,(value>>(i*13))&8191) for i in range(5)]
            candidates=set().union(*(buckets[p] for p in parts))
            for other in candidates:
                if (value^other).bit_count()<=4:union(rid,seen[other])
            seen[value]=rid
            for part in parts:buckets[part].add(value)
    splits=defaultdict(set)
    for e in examples:splits[find(e['metadata']['id'])].add(e['metadata']['split'])
    return {e['metadata']['id']:['family/shared-input/exact-pixel/near-duplicate component crosses splits']
        for e in examples if len(splits[find(e['metadata']['id'])])>1}


POLICY = 'confirmed-visual-quarantine-v2'
_SIZE = 192


@lru_cache(maxsize=1024)
def _signature(path):
    """Small local comparison views, never exported as training/remote data."""
    with Image.open(path) as source:
        rgba=source.convert('RGBA');views=[]
        for color in ((0,0,0,255),(255,255,255,255)):
            base=Image.new('RGBA',rgba.size,color);base.alpha_composite(rgba)
            if not views:
                gray=np.asarray(base.convert('L').resize((9,8),Image.Resampling.LANCZOS))
                bits=(gray[:,1:]>gray[:,:-1]).ravel();coarse=sum(int(bit)<<i for i,bit in enumerate(bits))
            views.append(np.asarray(base.convert('RGB').resize((_SIZE,_SIZE),Image.Resampling.LANCZOS)))
    pixels=np.stack(views);border=np.concatenate((pixels[:,0],pixels[:,-1],pixels[:,:,0],pixels[:,:,-1]),axis=1)
    background=np.median(border,axis=1)[:,None,None,:]
    content=(np.abs(pixels.astype(np.int16)-background).max(axis=(0,3))>12)
    delta=pixels.astype(np.int16);edges=np.zeros((_SIZE,_SIZE),dtype=bool)
    edges[:,1:]|=(np.abs(delta[:,:,1:]-delta[:,:,:-1]).max(axis=(0,3))>24)
    edges[1:]|=(np.abs(delta[:,1:]-delta[:,:-1]).max(axis=(0,3))>24)
    return coarse,pixels,content,edges


def _iou(a,b):
    union=int((a|b).sum())
    return float((a&b).sum()/union) if union else 1.


def confirm_near_duplicate(left,right):
    """Confirm a coarse-hash candidate using visible pixels and detailed shape.

    Sparse white layouts cannot dilute the error: measure over the content
    union on both black/white composites. Recolored copies also quarantine when
    detailed occupancy AND edge geometry agree. Small translation tolerance
    retains shifted copies. This never edits the original pixels or labels.
    """
    _,a,am,ae=_signature(str(left));_,b,bm,be=_signature(str(right));best=None
    for dy in (0,-1,1,-2,2):
        for dx in (0,-1,1,-2,2):
            ay=slice(max(0,dy),min(_SIZE,_SIZE+dy));by=slice(max(0,-dy),min(_SIZE,_SIZE-dy))
            ax=slice(max(0,dx),min(_SIZE,_SIZE+dx));bx=slice(max(0,-dx),min(_SIZE,_SIZE-dx))
            mask=am[ay,ax]|bm[by,bx]
            if not mask.any():mask=np.ones(mask.shape,dtype=bool)
            diff=np.abs(a[:,ay,ax].astype(np.int16)-b[:,by,bx].astype(np.int16))
            error=float(diff[:,mask].mean(axis=(1,2)).max()/255.)
            changed=float((diff.max(axis=3)>32)[:,mask].mean(axis=1).max())
            occupancy=_iou(am[ay,ax],bm[by,bx]);edge=_iou(ae[ay,ax],be[by,bx])
            confirmed=(error<=.035 and changed<=.08) or (occupancy>=.98 and edge>=.95)
            metrics=dict(confirmed=bool(confirmed),content_rgb_mae=error,changed_content_fraction=changed,
                occupancy_iou=occupancy,edge_iou=edge,translation=[dx,dy],policy=POLICY)
            if confirmed:return metrics
            if best is None or error<best['content_rgb_mae']:best=metrics
    return best


def exclusions(examples,dataset,*,evidence=None):
    """Family/exact shared-input gates plus confirmed visual duplicate components.

    The 64-bit luminance hash remains a <=4-bit candidate search, not a proof
    that different drawings are the same input. Historical one-stage behavior
    remains available as legacy_exclusions for reproducing retained reports.
    """
    # Closed exports share content-addressed conditioning and original pixels
    # across revisions. Reusing an identical ordered pair result changes no
    # decision or metric and avoids repeating expensive full-resolution proof.
    compare = lru_cache(maxsize=8192)(confirm_near_duplicate)
    parent={e['metadata']['id']:e['metadata']['id'] for e in examples}
    def find(value):
        while parent[value]!=value:
            parent[value]=parent[parent[value]];value=parent[value]
        return value
    def union(a,b):parent[find(a)]=find(b)
    owners={};seen=defaultdict(list);buckets=defaultdict(set)
    for example in examples:
        row=example['metadata'];rid=row['id']
        keys=[('family',f) for f in [row['family'],*row.get('ancestry',[])]]
        keys.extend(('pixels',a['sha256']) for a in [*row['frames'],*row['conditioning']])
        for key in keys:
            if key in owners:union(rid,owners[key])
            owners[key]=rid
        for artifact in [*row['frames'],*row['conditioning']]:
            path=str(dataset/artifact['file']);value=_signature(path)[0]
            parts=[(i,(value>>(i*13))&8191) for i in range(5)]
            candidates=set().union(*(buckets[p] for p in parts))
            for other in candidates:
                if (value^other).bit_count()>4:continue
                for other_rid,other_path in seen[other]:
                    if find(rid)==find(other_rid):continue
                    result=compare(path,other_path)
                    if evidence is not None:evidence.append(dict(left=rid,right=other_rid,hash_hamming=(value^other).bit_count(),**result))
                    if result['confirmed']:union(rid,other_rid)
            seen[value].append((rid,path))
            for part in parts:buckets[part].add(value)
    splits=defaultdict(set)
    for example in examples:splits[find(example['metadata']['id'])].add(example['metadata']['split'])
    return {e['metadata']['id']:['family/shared-input/exact-pixel/confirmed-near-duplicate component crosses splits']
        for e in examples if len(splits[find(e['metadata']['id'])])>1}
