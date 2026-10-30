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
