"""Idempotent v1 → v2 migration dry-run. Never mutates originals.

Reports: importable media (decodable PNG + hashes), missing references, malformed
contracts, unresolved rights, old review decisions (untrusted unless media-proven).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _sha256_file(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def dry_run(source: str | Path) -> dict:
    source = Path(source)
    report: dict = {
        "source": str(source), "mode": "dry-run", "mutated": False,
        "importable_media": [], "missing_references": [], "malformed": [],
        "unresolved_rights": [], "legacy_decisions_untrusted": [],
    }
    contract_path = source / "contract.json" if (source / "contract.json").is_file() else (
        source if source.suffix == ".json" and source.is_file() else None)
    if contract_path is None:
        report["malformed"].append(f"no contract.json found under {source}")
        return report
    try:
        contract = json.loads(Path(contract_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        report["malformed"].append(f"contract unreadable: {e}")
        return report
    base = Path(contract_path).parent
    if contract.get("schema") != 1:
        report["malformed"].append(f"expected v1 schema 1, got {contract.get('schema')}")
    for key in ("character", "canvas", "frames"):
        if key not in contract:
            report["malformed"].append(f"contract missing {key}")
    # media inventory
    media_files: list[str] = list(contract.get("frames", []))
    for ref in contract.get("references", []) or []:
        if isinstance(ref, dict) and ref.get("file"):
            media_files.append(ref["file"])
    master = contract.get("master")
    if isinstance(master, dict) and master.get("file"):
        media_files.append(master["file"])
    try:
        from ..pngcodec import read_png
        can_decode = True
    except ImportError:
        read_png = None  # type: ignore
        can_decode = False
    for rel in media_files:
        p = (base / rel)
        if not p.is_file():
            report["missing_references"].append(rel)
            continue
        digest = _sha256_file(p)
        decodable: bool | str = True
        dims = None
        if can_decode:
            try:
                w, h, _ = read_png(p)
                dims = [w, h]
            except Exception as e:
                decodable = f"undecodable: {e}"
        entry = {"file": rel, "byte_sha256": digest, "decodable": decodable}
        if dims:
            entry["dimensions"] = dims
        report["importable_media"].append(entry)
    # forbidden inputs sanity
    for frag in contract.get("forbidden_path_fragments", []) or []:
        for f in contract.get("frames", []) or []:
            if frag in "/" + str(f).replace("\\", "/"):
                report["malformed"].append(f"frame {f} matches forbidden fragment {frag}")
    # rights: v1 contracts carry no rights field → unresolved by default
    if "rights" not in contract and "rights_policy" not in contract:
        report["unresolved_rights"].append("v1 contract declares no rights; migration requires explicit rights before import")
    # legacy review db
    for dbname in ("review.sqlite", "review.db", "desk.sqlite3"):
        if (base / dbname).is_file():
            report["legacy_decisions_untrusted"].append(
                f"{dbname}: slot-only decisions are UNTRUSTED historical events unless a matching media revision is proven; no approvals granted")
    db_files = sorted(str(p) for p in base.glob("*.sqlite*"))
    for db in db_files:
        if db not in [str(base / n) for n in ("review.sqlite", "review.db", "desk.sqlite3")]:
            report["legacy_decisions_untrusted"].append(f"{Path(db).name}: see rule above")
    return report
