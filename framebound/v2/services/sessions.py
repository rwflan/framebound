"""Reviewer sessions: localhost pairing ceremony, never header self-assertion.

The model/orchestrator credential can propose, generate, repair and acknowledge;
it can never mint a reviewer session. A local operator pairs a reviewer id
(explicit human action, e.g. `framebound reviewer-pair`), then exchanges the
single-use pairing code for a session token. Reviewer writes present that token.
Only token hashes are stored; raw codes/tokens are shown once at creation.

Threat boundary: this protects the API/MCP/CLI transport. A process with
unrestricted filesystem access to the project database can rewrite the database
directly; no HTTP role check can prevent that, and none is claimed here.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from .. import domain as D
from .. import storage as S
from .errors import AuthorizationError, InvalidInput

PAIRING_TTL_MINUTES = 15
SESSION_TTL_HOURS = 12


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def pair_reviewer(project_dir: str, reviewer_id: str) -> dict:
    """Start pairing for a human reviewer. Returns a single-use code (shown once)."""
    reviewer_id = (reviewer_id or "").strip()
    if not reviewer_id or len(reviewer_id) > 200:
        raise InvalidInput("reviewer_id must be a non-empty id (<=200 chars)")
    code = secrets.token_hex(16)
    rec = D.ReviewerPairing(code_sha256=_sha(code), reviewer_id=reviewer_id,
                            expires_at=(_now() + timedelta(minutes=PAIRING_TTL_MINUTES)).isoformat())
    con = S.connect(project_dir)
    try:
        con.execute("INSERT INTO reviewer_pairings(code_sha, data) VALUES(?, ?)",
                    (rec.code_sha256, rec.model_dump_json()))
        con.commit()
    finally:
        con.close()
    return {"pairing_code": code, "reviewer_id": reviewer_id,
            "expires_at": rec.expires_at, "ttl_minutes": PAIRING_TTL_MINUTES}


def open_session(project_dir: str, pairing_code: str) -> dict:
    """Exchange an unused, unexpired pairing code for a reviewer session token (shown once)."""
    if not pairing_code:
        raise InvalidInput("pairing_code is required")
    digest = _sha(pairing_code)
    con = S.connect(project_dir)
    try:
        row = con.execute("SELECT data FROM reviewer_pairings WHERE code_sha=?", (digest,)).fetchone()
        if row is None:
            raise AuthorizationError("unknown or already-consumed pairing code")
        import json as _json
        rec = D.ReviewerPairing.model_validate_json(row["data"])
        if rec.used or _now() > datetime.fromisoformat(rec.expires_at):
            raise AuthorizationError("pairing code expired or already used")
        rec.used = True
        con.execute("UPDATE reviewer_pairings SET data=? WHERE code_sha=?",
                    (rec.model_dump_json(), digest))
        token = secrets.token_hex(32)
        sess = D.ReviewerSession(token_sha256=_sha(token), reviewer_id=rec.reviewer_id,
                                 expires_at=(_now() + timedelta(hours=SESSION_TTL_HOURS)).isoformat())
        con.execute("INSERT INTO reviewer_sessions(token_sha, data) VALUES(?, ?)",
                    (sess.token_sha256, sess.model_dump_json()))
        con.commit()
    finally:
        con.close()
    return {"session_token": token, "reviewer_id": rec.reviewer_id,
            "expires_at": sess.expires_at}


def resolve_session(project_dir: str, token: str | None) -> str | None:
    """Return the reviewer id for a live session token, else None. Never raises."""
    if not token:
        return None
    try:
        con = S.connect(project_dir)
        try:
            row = con.execute("SELECT data FROM reviewer_sessions WHERE token_sha=?",
                              (_sha(token),)).fetchone()
        finally:
            con.close()
        if row is None:
            return None
        import json as _json
        sess = D.ReviewerSession.model_validate_json(row["data"])
        if _now() > datetime.fromisoformat(sess.expires_at):
            return None
        return sess.reviewer_id
    except Exception:
        return None
