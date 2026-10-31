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
