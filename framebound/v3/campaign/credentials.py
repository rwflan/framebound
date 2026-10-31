"""Private local credential loading and manual setup, without a web server."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets


def key_file():
    path=Path(os.environ.get('FRAMEBOUND_MUSE_KEY_FILE',str(Path.home()/'.config/framebound/muse-api-key.json'))).expanduser().absolute()
    if path.resolve().is_relative_to(Path(__file__).resolve().parents[3]):
        raise ValueError('Credential files must remain outside the repository')
    return path


def load_key():
    value=os.environ.get('MODEL_API_KEY')
    if value:return value
    path=key_file()
    if not path.is_file():return None
    if path.is_symlink() or path.stat().st_mode & 0o077:raise ValueError('API key file must be private (0600) and not a symlink')
    return json.loads(path.read_text())['api_key']


def save_key(value):
    if not isinstance(value,str) or not 8<=len(value)<=4096 or any(c.isspace() for c in value):raise ValueError('Enter the complete API key without whitespace')
    path=key_file();path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.is_symlink():raise ValueError('API key path cannot be a symlink')
    temporary=path.parent/('.key-'+secrets.token_hex(16))
    fd=os.open(temporary,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,'w') as stream:
            json.dump({'api_key':value},stream);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_file():
    """Create an empty private file for manual entry; preserve existing secrets."""
    path=key_file();path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    try:
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    except FileExistsError:
        if path.is_symlink():raise ValueError('API key path cannot be a symlink')
        return path
    with os.fdopen(fd,'w') as stream:
        json.dump({'api_key':''},stream,indent=2);stream.write('\n')
    return path


if __name__=='__main__':
    print(prepare_file())
