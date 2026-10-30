"""Crash-recoverable immutable directory publication on the destination filesystem."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from filelock import FileLock
from .. import storage as S
from ..safe_output import OutputExistsError,UnsafeOutputError,_refuse_root_or_home


def _write(path,value):
    temporary=path.with_name(path.name+'.new-'+uuid.uuid4().hex)
    with temporary.open('x') as stream:
        json.dump(value,stream,indent=2);stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)
    descriptor=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(descriptor)
    finally:os.close(descriptor)


def _checkpoint(stage):
    """Process-death test boundary; no production execution hook parameter."""


def _validated(path,digest):
    from .validate import validate_snapshot
    manifest=json.loads((path/'manifest.json').read_text())
    if manifest.get('inputs_digest')!=digest:raise OutputExistsError('destination contains a different immutable snapshot')
    report=validate_snapshot(str(path))
    if not report['ok']:raise ValueError('snapshot is incomplete or corrupt: '+'; '.join(report['issues'][:8]))
    return manifest


def publish(project,name,rids,out_dir,policy,digest):
    from .snapshot import _build_into,_record_snapshot,_h
    out=Path(out_dir).expanduser().absolute()
    _refuse_root_or_home(out)
    source=Path(project).resolve()
    if out.resolve()==source or out.resolve() in source.parents or out.is_symlink():
        raise UnsafeOutputError('snapshot destination overlaps source or is a symlink')
    if (out/'framebound.sqlite3').exists() or (out/'blobs').is_dir():raise UnsafeOutputError('snapshot destination contains project data')
    out.parent.mkdir(parents=True,exist_ok=True)
    journal_dir=out.parent/('.'+out.name+'.framebound-publication')
    with FileLock(str(journal_dir)+'.lock'):
        if out.exists() and (out/'manifest.json').is_file():
            manifest=_validated(out,digest)
            _record_snapshot(project,name,rids,policy,manifest,manifest_sha256=_h((out/'manifest.json').read_bytes()))
            # Replaying an immutable historical snapshot never rebuilds current state.
            return manifest
        if out.exists() and (not out.is_dir() or any(out.iterdir())):
            raise OutputExistsError('refusing populated destination; preserve it and choose a new snapshot path')
        state_file=journal_dir/'state.json'
        if state_file.is_file():
            state=json.loads(state_file.read_text())
            if state['digest']!=digest or state['source']!=str(source):raise S.ConflictError('publication journal already bound to another request')
            stage=out.parent/state['stage']
            if stage.parent!=out.parent or stage.name!=state['stage']:raise ValueError('invalid staging identity in journal')
        else:
            if journal_dir.exists() and not (journal_dir/'.framebound-publication').is_file():
                raise UnsafeOutputError('refusing unowned publication directory')
            journal_dir.mkdir(exist_ok=True)
            (journal_dir/'.framebound-publication').write_text('framebound snapshot publication\n')
            pinned=source/'backups'/('snapshot-'+digest+'.sqlite3')
            with FileLock(str(pinned)+'.lock'):
                if not pinned.exists():
                    temporary=pinned.with_name(pinned.name+'.pinning-'+uuid.uuid4().hex)
                    original=S.connect(project);backup=sqlite3.connect(temporary)
                    try:original.backup(backup)
                    finally:backup.close();original.close()
                    temporary.rename(pinned)
            stage=out.parent/(out.name+'.staging-'+uuid.uuid4().hex)
            state={'digest':digest,'source':str(source),'stage':stage.name,'phase':'pinned','snapshot':name,
                   'revision_ids':rids,'policy':policy,'source_sha256':hashlib.sha256(pinned.read_bytes()).hexdigest(),'source_backup':pinned.name}
            _write(state_file,state)
        pinned=source/'backups'/state['source_backup']
        if pinned.parent!=source/'backups' or pinned.name!=state['source_backup']:raise ValueError('invalid pinned source identity')
        if hashlib.sha256(pinned.read_bytes()).hexdigest()!=state['source_sha256']:
            raise ValueError('pinned source state differs from publication journal')
        _checkpoint('pinned')
        if state['phase']=='pinned':
            if stage.exists():
                # Only the journal-owned partial directory is moved; user data is retained.
                stage.rename(stage.with_name(stage.name+'.interrupted-'+uuid.uuid4().hex))
            stage.mkdir()
            # The hash-bound backup is immutable; reading must not create WAL sidecars.
            con=sqlite3.connect(f'{pinned.resolve().as_uri()}?immutable=1', uri=True);con.row_factory=sqlite3.Row
            try:
                from .agent_snapshot import is_agent_selection, build_into
                manifest=(build_into(project,name,rids,stage,policy,digest,con)
                          if is_agent_selection(con,rids) else _build_into(project,name,rids,stage,policy,digest,connection=con))
            finally:con.close()
            marker={'snapshot':name,'inputs_digest':digest,'manifest_sha256':_h((stage/'manifest.json').read_bytes()),
                    'dataset_version':manifest['dataset_version']}
            _write(stage/'COMPLETE',marker)
            manifest=_validated(stage,digest)
            # Flush all staged files before the one namespace publication.
            for path in stage.rglob('*'):
                if path.is_file():
                    fd=os.open(path,os.O_RDONLY)
                    try:os.fsync(fd)
                    finally:os.close(fd)
            state['phase']='staged';state['manifest_sha256']=_h((stage/'manifest.json').read_bytes());_write(state_file,state)
        _checkpoint('staged')
        if state['phase']=='staged':
            manifest=_validated(stage,digest)
            if _h((stage/'manifest.json').read_bytes())!=state['manifest_sha256']:raise ValueError('staged manifest differs from journal')
            if out.exists():out.rmdir()  # only an empty reserved directory can reach this point
            stage.rename(out)
            descriptor=os.open(out.parent,os.O_RDONLY)
            try:os.fsync(descriptor)
            finally:os.close(descriptor)
            state['phase']='published';_write(state_file,state)
        _checkpoint('published')
        manifest=_validated(out,digest)
        _record_snapshot(project,name,rids,policy,manifest,manifest_sha256=_h((out/'manifest.json').read_bytes()))
        state['phase']='recorded';_write(state_file,state)
        _checkpoint('recorded')
        return manifest
