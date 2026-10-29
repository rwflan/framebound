"""Local browser review sessions, with no code exchange or enrollment step.

The browser transport is checked by the API before a session is created. Tokens
are stored as hashes and delivered only as an HttpOnly, same-site cookie.
Explicit tokens remain usable by trusted integrations; model actor credentials
never become reviewer credentials. Unrestricted project filesystem access is
outside the HTTP principal boundary.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from .. import domain as D
from .. import storage as S
from .errors import AuthorizationError, InvalidInput

SESSION_TTL_HOURS = 12


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def require_operator(credential: str | None) -> None:
    """Operator-only provider administration and explicit token revocation."""
    expected = os.environ.get("FRAMEBOUND_OPERATOR_SECRET", "")
    if not expected or not credential or not hmac.compare_digest(str(credential), expected):
        raise AuthorizationError("operator authorization required")


def create_session(project_dir: str, reviewer_id: str = "local-reviewer") -> dict:
    """Trusted server entry point after validating the local browser request."""
    if not reviewer_id.strip() or len(reviewer_id) > 200:
        raise InvalidInput("reviewer id must be nonempty and at most 200 characters")
    token = secrets.token_hex(32)
    record = D.ReviewerSession(token_sha256=_sha(token), reviewer_id=reviewer_id,
        expires_at=(_now() + timedelta(hours=SESSION_TTL_HOURS)).isoformat())
    con = S.connect(project_dir)
    try:
        con.execute("INSERT INTO reviewer_sessions(token_sha, data) VALUES(?, ?)",
                    (record.token_sha256, record.model_dump_json()))
        con.commit()
    finally:
        con.close()
    return {"session_token": token, "reviewer_id": reviewer_id, "expires_at": record.expires_at}


def revoke_session(project_dir: str, token: str, *, operator_credential: str | None = None) -> dict:
    """Revoke a reviewer session so its token stops authorizing writes."""
    require_operator(operator_credential)
    if not token:
        raise InvalidInput("session token is required")
    con = S.connect(project_dir)
    try:
        cur = con.execute("DELETE FROM reviewer_sessions WHERE token_sha=?", (_sha(token),))
        con.commit()
        revoked = cur.rowcount > 0
    finally:
        con.close()
    return {"revoked": revoked}


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
