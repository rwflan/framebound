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


GEOMETRY_NAMES = ('bbox_width','bbox_height','centroid_x','centroid_y','extent','alpha_std',
                  'boundary_fraction','centroid_dx','centroid_dy','area_delta','alpha_iou','foreground_l1')


def extract(frames, holds, *, loop, allowed_identical_slots=(), extractor=VERSION):
    if extractor not in (VERSION, 'native-geometry-v2'):
        raise ValueError('unsupported feature extractor')
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
    if extractor == 'native-geometry-v2':
        masks = [a[:,:,3] > 0 for a in arrays]
        centers = []
        for mask in masks:
            y,x = np.nonzero(mask)
            centers.append((float(x.mean()/mask.shape[1]),float(y.mean()/mask.shape[0])) if len(x) else (0.,0.))
        for slot,(a,mask) in enumerate(zip(arrays,masks)):
            height,width = mask.shape
            y,x = np.nonzero(mask)
            bw = int(x.max()-x.min()+1) if len(x) else 0
            bh = int(y.max()-y.min()+1) if len(y) else 0
            prev = slot-1 if slot or loop else slot
            old = masks[prev]
            boundary = np.count_nonzero(mask[:,1:] != mask[:,:-1]) + np.count_nonzero(mask[1:] != mask[:-1])
            union = np.count_nonzero(mask | old)
            # RGB differences are measured only where both masks contain subject.
            common = mask & old
            delta = np.abs(a[:,:,:3].astype(float)-arrays[prev][:,:,:3].astype(float))
            rows[slot].extend([bw/width,bh/height,*centers[slot],float(mask.sum()/max(bw*bh,1)),
                float(a[:,:,3].std()/255),float(boundary/(width*height)),
                centers[slot][0]-centers[prev][0],centers[slot][1]-centers[prev][1],
                float((int(mask.sum())-int(old.sum()))/(width*height)),
                float(np.count_nonzero(mask & old)/union) if union else 1.,
                float(delta[common].mean()/255) if common.any() else 0.])
    values = np.asarray(rows,dtype=np.float32)
    names = FEATURE_NAMES + (GEOMETRY_NAMES if extractor != VERSION else ())
    return dict(version=extractor,features=values,feature_names=names,windows=windows,proposals=proposals,
        frame_sha256=[hashlib.sha256(a.tobytes()).hexdigest() for a in arrays],
        preprocessing_sha256=digest([extractor,names]),
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


def collect(root,campaign,*,version='1',extractor=VERSION,include_test=False,dataset_version=None,scoped=False):
    """Derive learning tensors locally from validated, closed campaign exports."""
    from .contracts import Identity
    Identity(id=version)
    if type(include_test) is not bool:raise ValueError('include_test must be an explicit boolean')
    from .export import export_campaign,load
    from .assessment import CATEGORIES
    from .transfer import FeatureRow,FeatureRowV2,FeatureShard,preupload
    from .intelligence import training_labels
    from .contracts import canonical,local_path
    dataset_version=dataset_version or version
    Identity(id=dataset_version)
    dataset=local_path(root,f'campaigns/{campaign}/training/{dataset_version}')
    result=dict(path=str(dataset)) if (dataset/'manifest.json').is_file() else export_campaign(root,campaign,version=dataset_version)
    scoped=scoped or extractor=='native-geometry-v2'
    if result.get('status')=='no_generated_examples':return result
    rows=[]
    examples=load(result['path'])
    from .leakage import exclusions
    excluded=exclusions(examples,Path(result['path']))
    for example in examples:
        metadata=example['metadata']
        if metadata['id'] in excluded:continue
        if metadata['split']=='test' and not include_test:continue
        if not metadata.get('rights') or any(r!='original' for r in metadata['rights']):continue
        from ..intake import inspect
        # Unsuitable originals remain in exports, but never become semantic training rows.
        if not all(inspect(frame)['eligible'] for frame in example['frames']):
            continue
        measurements=extract(example['frames'],metadata['holds'],loop=metadata['loop'],extractor=extractor)
        labels,weights=training_labels(metadata)
        values=dict(case_id=digest(metadata['id']),family_id=digest(metadata['family']),split=metadata['split'],
            features=measurements['features'].tolist(),targets=[labels[c]['target'] if labels[c]['mask'] else 0 for c in CATEGORIES],
            assessed=[labels[c]['mask'] for c in CATEGORIES],challenge=metadata.get('challenge_negative',False),
            weight=min(weights.values()))
        if scoped:
            values.update(sequence_id=digest(metadata['sequence_id']),category_weights=[weights[c] for c in CATEGORIES])
            rows.append(FeatureRowV2(**values))
        else:
            rows.append(FeatureRow(**values))
    if not rows:
        return dict(status='no_learning_eligible_examples',split_exclusions=len(excluded),remote_bytes_transferred=0)
    shard=FeatureShard(rows=rows,extractor=extractor,
        schema_version='feature-only-2.0' if scoped else 'feature-only-1.0')
    raw,manifest=preupload(shard)
    folder=local_path(root,f'campaigns/{campaign}/features/{version}');folder.mkdir(parents=True,exist_ok=True)
    artifacts={'features.json':raw,'preupload-manifest.json':canonical(manifest),
        'source-manifest.json':canonical(dict(dataset_version=dataset_version,
            dataset_sha256=digest(__import__('json').loads((dataset/'manifest.json').read_text())),
            extractor=extractor,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))}
    for name,content in artifacts.items():
        path=folder/name
        if path.exists() and path.read_bytes()!=content:raise ValueError('feature version is immutable')
    for name,content in artifacts.items():
        path=folder/name
        if not path.exists():path.write_bytes(content)
    return dict(path=str(folder/'features.json'),manifest=manifest,split_exclusions=len(excluded),remote_bytes_transferred=0)
