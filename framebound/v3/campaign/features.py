"""Local native-frame measurements. These features make no anatomy claims."""
from __future__ import annotations

import hashlib
from pathlib import Path
import time

import numpy as np
from PIL import Image

from .assessment import temporal_windows
from .contracts import digest

VERSION = 'native-numeric-v1'
FEATURE_NAMES = ('red','green','blue','alpha','luminance_std','foreground_fraction','adjacent_l1','hold_ticks')


def extract(frames, holds, *, loop, allowed_identical_slots=()):
    if len(frames) != len(holds) or not frames:
        raise ValueError('one positive hold per actual frame required')
    windows = temporal_windows(holds,loop=loop)
    arrays = [np.asarray(f.convert('RGBA'),dtype=np.uint8) for f in frames]
    if len({a.shape for a in arrays}) != 1:
        raise ValueError('mixed native canvas sizes')
    rows = []; proposals = []
    for slot,a in enumerate(arrays):
        pixels = a.astype(np.float32)/255
        previous = arrays[slot-1] if slot or loop else a
        adjacent = float(np.abs(a.astype(np.float32)-previous.astype(np.float32)).mean()/255)
        alpha = pixels[:,:,3]
        # Opaque art has no trustworthy foreground mask; NaN would also be an
        # invalid remote feature. Use alpha occupancy and expose the limitation.
        rows.append([*pixels[:,:,:3].mean(axis=(0,1)).tolist(),float(alpha.mean()),
                     float(pixels[:,:,:3].mean(axis=2).std()),float((alpha>0).mean()),adjacent,holds[slot]])
        if (slot or loop) and np.array_equal(a,previous) and slot not in allowed_identical_slots:
            proposals.append(dict(kind='identical_drawing_candidate',slots=[(slot-1)%len(arrays),slot],
                conclusion='suspicion_only',limitation='Authored holds, idle poses and deliberate repetition may be legitimate.'))
    values = np.asarray(rows,dtype=np.float32)
    return dict(version=VERSION,features=values,feature_names=FEATURE_NAMES,windows=windows,proposals=proposals,
        frame_sha256=[hashlib.sha256(a.tobytes()).hexdigest() for a in arrays],
        preprocessing_sha256=digest([VERSION,FEATURE_NAMES]),
        limitations=['No anatomy/action semantics or foreground on opaque images.', 'No learned encoder, camera separation or tracker is implied.'])


def profile(paths, holds, *, loop):
    started = time.monotonic()
    frames = []
    for path in paths:
        with Image.open(path) as image:
            image.load(); frames.append(image.convert('RGBA'))
    result = extract(frames,holds,loop=loop)
    result['seconds_per_frame'] = (time.monotonic()-started)/len(frames)
    return result


def collect(root,campaign,*,version='1'):
    """Derive learning tensors locally from validated, closed campaign exports."""
    from .export import export_campaign,load
    from .assessment import CATEGORIES
    from .transfer import FeatureRow,FeatureShard,preupload
    from .contracts import canonical,local_path
    result=export_campaign(root,campaign,version=version)
    if result.get('status')=='no_generated_examples':return result
    rows=[]
    for example in load(result['path']):
        metadata=example['metadata'];measurements=extract(example['frames'],metadata['holds'],loop=metadata['loop'])
        labels={c:dict(v) for c,v in metadata['labels'].items()}
        corroborating=metadata.get('corroborating_assessments',[])
        independent=len({a['provenance']['execution_id'] for a in corroborating})>=2 and len({a['provenance']['rubric_sha256'] for a in corroborating})>=2
        if independent:
            from .assessment import Assessment
            targets=[Assessment.model_validate(a).targets() for a in corroborating]
            for category in CATEGORIES:
                comparisons=[t[category] for t in targets]
                if not all(t['mask'] and t['target']==comparisons[0]['target'] and (t['target']==1 or set(t['slots'])==set(comparisons[0]['slots'])) for t in comparisons):
                    labels[category]['mask']=False
        for category in CATEGORIES:
            if labels[category]['target']==0 and set(labels[category]['slots'])!=set(range(len(metadata['holds']))):
                labels[category]['mask']=False
        # Weak model labels have a fixed conservative weight; teacher confidence
        # is never copied into a loss weight or treated as calibrated truth.
        rows.append(FeatureRow(case_id=digest(metadata['id']),family_id=digest(metadata['family']),split=metadata['split'],
            features=measurements['features'].tolist(),targets=[labels[c]['target'] if labels[c]['mask'] else 0 for c in CATEGORIES],
            assessed=[labels[c]['mask'] for c in CATEGORIES],weight=1.0 if independent else 0.5))
    shard=FeatureShard(rows=rows);raw,manifest=preupload(shard)
    folder=local_path(root,f'campaigns/{campaign}/features/{version}');folder.mkdir(parents=True,exist_ok=True)
    path=folder/'features.json'
    if path.exists() and path.read_bytes()!=raw:raise ValueError('feature version is immutable')
    path.write_bytes(raw);(folder/'preupload-manifest.json').write_bytes(canonical(manifest))
    return dict(path=str(path),manifest=manifest,remote_bytes_transferred=0)
