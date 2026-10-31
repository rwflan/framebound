"""Synthetic keys only; never inspect an operator's credential."""
import os
from pathlib import Path
import pytest

from framebound.v3.campaign import credentials as C


def test_secret_is_saved_privately_and_environment_override_wins(tmp_path,monkeypatch):
    path=tmp_path/'credentials.json'
    monkeypatch.setenv('FRAMEBOUND_MUSE_KEY_FILE',str(path));monkeypatch.delenv('MODEL_API_KEY',raising=False)
    assert C.load_key() is None
    C.save_key('synthetic-engineering-key')
    assert path.stat().st_mode & 0o777 == 0o600
    assert C.load_key()=='synthetic-engineering-key'
    monkeypatch.setenv('MODEL_API_KEY','synthetic-environment-key')
    assert C.load_key()=='synthetic-environment-key'


def test_symlink_and_permissive_credentials_are_rejected(tmp_path,monkeypatch):
    path=tmp_path/'key.json';target=tmp_path/'target.json';target.write_text('{}');path.symlink_to(target)
    monkeypatch.setenv('FRAMEBOUND_MUSE_KEY_FILE',str(path));monkeypatch.delenv('MODEL_API_KEY',raising=False)
    with pytest.raises(ValueError,match='symlink'):C.save_key('synthetic-engineering-key')
    path.unlink();C.save_key('synthetic-engineering-key');path.chmod(0o644)
    with pytest.raises(ValueError,match='private'):C.load_key()


def test_manual_setup_preserves_saved_key(tmp_path,monkeypatch):
    path=tmp_path/'key.json';monkeypatch.setenv('FRAMEBOUND_MUSE_KEY_FILE',str(path))
    assert C.prepare_file()==path
    assert path.stat().st_mode & 0o777 == 0o600
    C.save_key('synthetic-engineering-key')
    before=path.read_bytes()
    C.prepare_file()
    assert path.read_bytes()==before
