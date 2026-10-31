"""Explicitly versioned consumer for honest v3 training views and portable evidence."""
import json
from pathlib import Path

from PIL import Image

from .validate import validate_snapshot

VIEWS={'human_accepted':'hf','automatically_verified':'automatically_verified','research':'research'}


def load_examples(snapshot_dir,view,*,supported_versions=('3.0',)):
    snap=Path(snapshot_dir);manifest=json.loads((snap/'manifest.json').read_text())
    if manifest.get('dataset_version') not in supported_versions or manifest.get('dataset_version')!='3.0':
        raise ValueError('reader does not support these snapshot label semantics')
    if view not in VIEWS:raise ValueError('choose an explicit human_accepted, automatically_verified or research view')
    report=validate_snapshot(str(snap))
    if not report['ok']:raise ValueError('invalid snapshot: '+'; '.join(report['issues'][:8]))
    folder=snap/VIEWS[view];examples=[]
    for line in (folder/'metadata.jsonl').read_text().splitlines():
        if not line.strip():continue
        row=json.loads(line)
        with Image.open(folder/row['file_name']) as image:
            pixels=image.convert('RGBA').copy()
        examples.append(dict(metadata=row,image=pixels))
    return examples


def load_preferences(snapshot_dir):
    snap=Path(snapshot_dir);manifest=json.loads((snap/'manifest.json').read_text())
    if manifest.get('dataset_version')!='3.0':raise ValueError('agent preference reader requires explicitly supported v3 semantics')
    report=validate_snapshot(str(snap))
    if not report['ok']:raise ValueError('invalid snapshot: '+'; '.join(report['issues'][:8]))
    tasks={row['id']:row for row in (json.loads(line) for line in (snap/'closure/tasks.jsonl').read_text().splitlines() if line.strip())}
    pairs=[]
    for line in (snap/'preferences.jsonl').read_text().splitlines():
        if not line.strip():continue
        pair=json.loads(line)
        decoded={}
        for key in ('chosen','rejected'):
            decoded[key]=[]
            for frame in pair[key]:
                with Image.open(snap/frame['file']) as image:decoded[key].append(image.convert('RGBA').copy())
        pairs.append(dict(metadata=pair,task=tasks[pair['task_id']],**decoded))
    return pairs


def load_model_annotations(snapshot_dir):
    """Read explicitly model-authored learning targets without a human gate.

    These are supervision/evidence, never authenticated human acceptance or a
    guarantee of label correctness. Existing snapshot rights/closure checks apply.
    """
    snap=Path(snapshot_dir);manifest=json.loads((snap/'manifest.json').read_text())
    if manifest.get('dataset_version')!='3.0':raise ValueError('model annotation reader requires v3 semantics')
    report=validate_snapshot(str(snap))
    if not report['ok']:raise ValueError('invalid snapshot: '+'; '.join(report['issues'][:8]))
    paths=json.loads((snap/'closure/asset_files.json').read_text())
    membership={row['frame_instance_id']:row for row in (json.loads(line) for line in (snap/'membership.jsonl').read_text().splitlines() if line.strip())}
    annotations=[]
    for line in (snap/'closure/revisions.jsonl').read_text().splitlines():
        if not line.strip():continue
        revision=json.loads(line);metadata=revision.get('generation_metadata') or {}
        if not isinstance(metadata,dict):continue
        judgment=metadata.get('model_review')
        if judgment is None:continue
        frames=[]
        for aid in revision['frame_asset_ids']:
            if aid not in paths:break
            with Image.open(snap/paths[aid]) as image:frames.append(image.convert('RGBA').copy())
        else:
            annotations.append(dict(revision_id=revision['id'],task_id=revision['task_id'],
                label_source='model_review',human_acceptance=False,judgment=judgment,
                family=membership[revision['frame_instance_ids'][0]]['family'],split=membership[revision['frame_instance_ids'][0]]['split'],
                provenance=metadata.get('provenance'),frames=frames))
    return annotations


def load_model_corrections(snapshot_dir):
    """Read exact parent/child pixel pairs as model supervision, never human DPO."""
    snap=Path(snapshot_dir);annotations=load_model_annotations(snap)
    by_id={row['revision_id']:row for row in annotations};pairs=[]
    for line in (snap/'closure/revisions.jsonl').read_text().splitlines():
        if not line.strip():continue
        revision=json.loads(line);parent=revision.get('parent_revision_id')
        if revision['id'] not in by_id or parent not in by_id:continue
        pairs.append(dict(baseline=by_id[parent],correction=by_id[revision['id']],
            label_source='model_review',human_acceptance=False,
            authority='Candidate correction supervised by model annotations; quality and regressions remain measured separately.'))
    return pairs


def load_campaign_examples(snapshot_dir, lane='detection'):
    """Read versioned campaign objectives; never reinterpret these as human DPO."""
    from ...v3.campaign.export import load
    return load(snapshot_dir,lane)
