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
    import subprocess
    runtimes = {}
    for exe in ("node", "npm"):
        path = shutil.which(exe)
        if path is None:
            runtimes[exe] = "missing"
        else:
            try:
                out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30)
                runtimes[exe] = out.stdout.strip() or "unknown"
            except Exception:
                runtimes[exe] = "unavailable"
    return {
        "schema_version": "2.0", "ok": True,
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "dependencies": deps,
        "node_runtime": runtimes,
        "notes": ("tested runtime: node 22 + npm 12 (see IMPLEMENTATION_STATUS); "
                  "frontend build requires a compatible node; "
                  "core v2 works offline without provider keys"),
    }
