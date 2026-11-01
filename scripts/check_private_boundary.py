"""Check tracked/deploy files without publishing private names or hash lists."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

DENIED = {'campaigns', 'checkpoints', 'local-corpus', 'corpus', 'reference-cache', 'research-library', 'test-results', '.playwright-cli', '.venv', 'node_modules'}
SUFFIXES = {'.sqlite3', '.db', '.pt', '.pth', '.ckpt', '.safetensors', '.npz', '.npy', '.log', '.receipt.json'}


def audit(root, files, private_hashes=()):
    root = Path(root).resolve()
    failures = []
    for name in files:
        path = root / name
        unsafe = not path.resolve().is_relative_to(root) or path.is_symlink()
        parts = Path(name).parts
        private = bool(set(parts) & DENIED) or any(name.endswith(s) for s in SUFFIXES)
        private |= 'docs/research/' in name or name.startswith('output/')
        if path.is_file() and not unsafe:
            if path.suffix=='.json':
                try:
                    value=json.loads(path.read_text())
                    private |= isinstance(value,dict) and value.get('schema_version') in {'animation-model-card-1.0','feature-detector-1.0','temporal-convolution-1.0','feature-only-1.0','animation-training-1.0','animation-training-2.0','historical-assessment-replay-1.0','feature-only-2.0','animation-knowledge-1.0','knowledge-inventory-1.0','local-baseline-1.0','local-workload-profile-1.0','representation-ablation-1.0','knowledge-release-1.0','animation-advisory-1.0','frozen-final-report-1.0','mvp-protocol-2.0','compute-plan-1.0'}
                except (ValueError,UnicodeError):pass
            private |= hashlib.sha256(path.read_bytes()).hexdigest() in private_hashes
        if unsafe or private:
            failures.append(name)
    return failures


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    parser.add_argument('--private-manifest', help='Local-only JSON list of SHA256 hashes; never print or upload it')
    parser.add_argument('--private-root',default=os.environ.get('FRAMEBOUND_LOCAL_ROOT','/Volumes/datadisk0/data/appdata/framebound-local'),help='Optional existing local corpus root; hashes are never printed or persisted')
    parser.add_argument('--deploy', action='store_true', help='Inspect every file in a prepared deployment context')
    args = parser.parse_args()
    root = Path(args.root)
    hashes = set(json.loads(Path(args.private_manifest).read_text())) if args.private_manifest else set()
    private_root=Path(args.private_root)
    if private_root.is_dir():
        for path in private_root.rglob('*'):
            if path.is_file() and not path.is_symlink() and path.suffix.lower() in {'.png','.jpg','.jpeg','.webp','.mp4','.gif'}:
                hashes.add(hashlib.sha256(path.read_bytes()).hexdigest())
    files = [str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()] if args.deploy else subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    failures = audit(root, [f for f in files if f], hashes)
    print(json.dumps({'ok': not failures, 'rejected_file_count': len(failures)}))
    raise SystemExit(bool(failures))
