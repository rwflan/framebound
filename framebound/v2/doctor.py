"""v2 doctor: runtime, dependencies, layout. Offline; never calls providers."""
from __future__ import annotations

import sqlite3
import sys


def run_doctor() -> dict:
    deps = {}
    for mod in ("pydantic", "numpy", "PIL", "fastapi", "uvicorn", "mcp", "datasets", "pycocotools"):
        try:
            m = __import__(mod)
            deps[mod] = getattr(m, "__version__", "installed")
        except ImportError:
            deps[mod] = "missing"
    import shutil
    return {
        "schema_version": "2.0", "ok": True,
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "dependencies": deps,
        "notes": "missing entries are expected before WP3/WP5 pin their extras; core v2 works offline without them",
    }
