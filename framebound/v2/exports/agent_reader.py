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
