"""Concrete preference consumer: multimodal chosen/rejected/common-prompt records.

Reads a published snapshot's preferences.jsonl and materializes one record
per explicit human comparison: the shared conditioning (contract +
evaluations), the chosen pixels and the rejected pixels, opened through the
targeted loader (PIL here; the schema carries file refs + hashes so a
datasets/torch adapter can join without re-parsing). Weak technical rankings
are never yielded here — see weak_preferences.jsonl, explicitly labeled.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image


def load_preferences(snapshot_dir: str | Path) -> list[dict]:
    """Materialize every explicit human-comparison pair with decoded pixels.

    Raises on the first unreadable chosen/rejected image: a training consumer
    must fail loudly rather than silently drop pairs.
    """
    snap = Path(snapshot_dir)
    rows = []
    for line in (snap / "preferences.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        pr = json.loads(line)
        if pr.get("origin") != "human-comparison":
            raise ValueError(f"non-human pair in preferences.jsonl: {pr.get('origin')}")
        cond = pr.get("conditioning") or {}
        if not cond.get("contract") or not cond.get("chosen_evaluation") \
                or not cond.get("rejected_evaluation"):
            raise ValueError("pair lacks common conditioning "
                             f"(contract/evaluations): {pr.get('comparison_packet')}")
        chosen = [_open(snap, f) for f in (pr.get("chosen") or [])]
        rejected = [_open(snap, f) for f in (pr.get("rejected") or [])]
        if not chosen or not rejected:
            raise ValueError(f"pair {pr.get('comparison_packet')} has empty chosen/rejected")
        closure=json.loads((snap/'closure'/'conditioning.json').read_text())
        contract=closure['contracts'].get(pr['chosen_revision'])
        if contract is None:raise ValueError('preference contract is not portable')
        guide=closure['motion_guides'].get(contract['references'].get('motion_guide_revision'))
        if guide is None:raise ValueError('preference guide is not portable')
        asset_records={a['id']:a for a in (json.loads(line) for line in (snap/'closure'/'assets.jsonl').read_text().splitlines() if line.strip())}
        control_ids={contract['references'][role] for role in ('identity','style')}
        for entry in guide['entries']:
            control_ids.update(entry.get(k) for k in ('asset_id','editable_mask_asset_id','protected_mask_asset_id') if entry.get(k))
        control_images={}
        for aid in sorted(control_ids):
            asset=asset_records[aid]
            control_images[aid]=_open(snap,{'file':'closure/blobs/'+asset['byte_sha256'],'sha256':asset['byte_sha256']})['image']
        rows.append({
            'conditioning_data':{'contract':contract,'guide':guide,'images':control_images},
            "prompt": pr.get("prompt"),
            "conditioning": cond,
            "comparison_packet": pr.get("comparison_packet"),
            "rejected_issue": pr.get("rejected_issue"),
            "reason": pr.get("reason"),
            "split": pr.get("split", "unsplit"),
            "chosen_images": chosen,
            "rejected_images": rejected,
        })
    return rows


def _open(snap: Path, ref: dict) -> dict:
    p=(snap/ref['file']).resolve()
    if not p.is_relative_to(snap.resolve()):raise ValueError('preference path escapes snapshot')
    if not p.is_file():raise ValueError('pair file missing from snapshot: '+ref['file'])
    raw=p.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=ref.get('sha256'):raise ValueError('preference image hash mismatch: '+ref['file'])
    with Image.open(p) as im:
        image=im.convert('RGBA');image.load()
    return {'file':ref['file'],'sha256':ref['sha256'],'size':image.size,'mode':image.mode,'image':image}


def decoded_batch(snapshot_dir,batch_size=1):
    """Framebound preference v1: paired native RGBA arrays and common conditioning.

    This project format is not a universal trainer API. Unequal sequence lengths
    remain explicit lists; callers choose padding/loss masks for their trainer.
    """
    import numpy as np
    if not isinstance(batch_size,int) or isinstance(batch_size,bool) or batch_size<1:
        raise ValueError('batch_size must be a positive integer')
    pairs=load_preferences(snapshot_dir)[:batch_size]
    if not pairs:raise ValueError('snapshot contains no explicit human preference batch')
    return {'format':'framebound-preference-v1','conditioning':[{'contract':p['conditioning_data']['contract'],'guide':p['conditioning_data']['guide'],
                'images':{aid:np.asarray(image,dtype=np.uint8) for aid,image in p['conditioning_data']['images'].items()}} for p in pairs],
            'chosen':[[np.asarray(im['image'],dtype=np.uint8) for im in p['chosen_images']] for p in pairs],
            'rejected':[[np.asarray(im['image'],dtype=np.uint8) for im in p['rejected_images']] for p in pairs],
            'comparison_packet_ids':[p['comparison_packet'] for p in pairs]}
