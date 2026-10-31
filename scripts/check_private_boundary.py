"""Check tracked/deploy files without publishing private names or hash lists."""
import argparse
import hashlib
import json
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
            private |= hashlib.sha256(path.read_bytes()).hexdigest() in private_hashes
        if unsafe or private:
            failures.append(name)
    return failures


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='.')
    parser.add_argument('--private-manifest', help='Local-only JSON list of SHA256 hashes; never print or upload it')
    parser.add_argument('--deploy', action='store_true', help='Inspect every file in a prepared deployment context')
    args = parser.parse_args()
    root = Path(args.root)
    hashes = json.loads(Path(args.private_manifest).read_text()) if args.private_manifest else []
    files = [str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()] if args.deploy else subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    failures = audit(root, [f for f in files if f], hashes)
    print(json.dumps({'ok': not failures, 'rejected_file_count': len(failures)}))
    raise SystemExit(bool(failures))
