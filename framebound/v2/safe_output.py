"""Safe output-directory handling (R0).

Demos, exports and fixtures must never recursively delete an existing user
directory. The default is to refuse a non-empty existing output path without
touching it. An explicit replace mode only proceeds for framework-owned
outputs (marked by a marker file this module writes on creation) and
preserves the previous contents as a sibling backup instead of deleting them.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

MARKER = ".framebound-output"
MARKER_TOOL_KEY = "tool"


class OutputExistsError(FileExistsError):
    """Raised when an output path is already populated and replace was not allowed."""


class UnsafeOutputError(ValueError):
    """Raised when an output path is unsafe (root, home, overlapping sources)."""


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().absolute()


def _is_nonempty_dir(p: Path) -> bool:
    try:
        with os.scandir(p) as it:
            for _ in it:
                return True
        return False
    except FileNotFoundError:
        return False


def _refuse_root_or_home(p: Path) -> None:
    if p == p.anchor or str(p) == p.anchor:
        raise UnsafeOutputError(f"refusing output at filesystem root: {p}")
    home = Path.home().absolute()
    if p == home:
        raise UnsafeOutputError(f"refusing output at home directory: {p}")


def prepare_output_dir(
    out: str | Path,
    *,
    replace: bool = False,
    tool: str = "framebound",
    refuse_inside: str | Path | None = None,
) -> Path:
    """Ensure ``out`` is a fresh empty directory owned by this framework.

    - New path: created (parents included) and marked with a marker file.
    - Existing empty path: marked and returned.
    - Existing non-empty path with ``replace=False`` (default): raises
      :class:`OutputExistsError` without modifying anything.
    - Existing non-empty path with ``replace=True``: proceeds only if the
      directory contains this framework's marker file; the previous contents
      are moved aside to ``<name>.backup-<timestamp>`` instead of deleted.

    ``refuse_inside`` optionally names a source/project directory the output
    must not overlap (prevents export-over-source accidents): the output may
    not equal the project dir, may not contain the project dir, and may not
    already hold project artifacts. A fresh subdirectory of a shared workdir
    is allowed; the marker/replace rules still govern reuse.
    """
    p = _resolved(out)
    _refuse_root_or_home(p)
    if refuse_inside is not None:
        src_dir = _resolved(refuse_inside)
        if p == src_dir or p in src_dir.parents:
            raise UnsafeOutputError(
                f"refusing output overlapping source/project dir: {p} (source: {src_dir})")
        if ((p / "framebound.sqlite3").exists() or (p / "blobs").is_dir()):
            raise UnsafeOutputError(
                f"refusing output that already holds project data: {p}")
    marker = p / MARKER
    if p.exists():
        if not p.is_dir():
            raise UnsafeOutputError(f"output path exists and is not a directory: {p}")
        if _is_nonempty_dir(p):
            if not replace:
                raise OutputExistsError(
                    f"output directory exists and is not empty: {p} "
                    "(pass replace=True only for framework-owned outputs)"
                )
            if not marker.is_file():
                raise UnsafeOutputError(
                    f"refusing to replace unmarked directory (not a framework output): {p}"
                )
            stamp = time.strftime("%Y%m%d-%H%M%S")
            backup = p.parent / f"{p.name}.backup-{stamp}"
            p.rename(backup)
            p.mkdir(parents=True)
            marker.write_text(json.dumps({MARKER_TOOL_KEY: tool, "replaced_backup": backup.name}) + "\n")
            return p
        # existing but empty: claim it
        if not marker.is_file():
            marker.write_text(json.dumps({MARKER_TOOL_KEY: tool}) + "\n")
        return p
    p.mkdir(parents=True)
    marker.write_text(json.dumps({MARKER_TOOL_KEY: tool}) + "\n")
    return p
