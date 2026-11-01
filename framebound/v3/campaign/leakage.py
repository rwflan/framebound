"""Conservative family/shared-input/pixel/near-duplicate split quarantine."""
from collections import defaultdict

import numpy as np
from PIL import Image


def exclusions(examples, dataset):
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
