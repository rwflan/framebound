"""Copy the built review desk (web/dist) into the packaged resource dir (framebound/desk).

Run after `npm --prefix web run build` and before `pip wheel .` so the wheel
serves the desk via importlib.resources without searching parent directories.
Source checkouts keep serving web/dist directly; this script is only needed
for building a self-contained distribution.
"""
from __future__ import annotations
import shutil
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
src = root / "web" / "dist"
dst = root / "framebound" / "desk"
if not (src / "index.html").is_file():
    sys.exit(f"refusing: {src}/index.html missing; run `npm --prefix web run build` first")
if dst.exists():
    shutil.rmtree(dst)
shutil.copytree(src, dst)
print(f"synced {src} -> {dst}")
