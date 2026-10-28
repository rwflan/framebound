"""Reviewer sessions: operator-issued pairing ceremony, never header self-assertion.

The model/orchestrator credential can propose, generate, repair and acknowledge;
it can never mint a reviewer session. A local operator (holder of the
FRAMEBOUND_OPERATOR_SECRET, e.g. `framebound reviewer-pair`) pairs a reviewer
id, then the reviewer exchanges the single-use pairing code for a session
token. Reviewer writes present that token. Only hashes are stored; raw
codes/tokens are shown once at creation.

Threat boundary: this protects the API/MCP/CLI transport. A process with
unrestricted filesystem access to the project database can rewrite the database
directly; no HTTP role check can prevent that, and none is claimed here.
Anonymous HTTP clients and model grants cannot mint reviewer authority.
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

PAIRING_TTL_MINUTES = 15
SESSION_TTL_HOURS = 12


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _operator_secret() -> str:
    return os.environ.get("FRAMEBOUND_OPERATOR_SECRET", "")


def require_operator(credential: str | None) -> None:
    """Gate the pairing ceremony on an out-of-band operator secret.

    The secret is never a model-facing tool argument and never travels in
    reviewer URLs/logs. Without it, pairing is refused even on localhost:
    localhost alone is not a distinct principal.
    """
    expected = _operator_secret()
    if not expected:
        raise AuthorizationError(
            "reviewer pairing is disabled: FRAMEBOUND_OPERATOR_SECRET is not "
            "configured on this server; use `framebound reviewer-pair` on the "
            "operator console")
    if not credential or not hmac.compare_digest(str(credential), expected):
        raise AuthorizationError("operator authorization required to pair a reviewer")


def pair_reviewer(project_dir: str, reviewer_id: str,
                  *, operator_credential: str | None = None) -> dict:
    """Start pairing for a human reviewer. Returns a single-use code (shown once).

    Requires the operator secret; anonymous/model callers cannot mint codes.
    """
    require_operator(operator_credential)
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


def issue_test_pairing(project_dir: str, reviewer_id: str) -> dict:
    """Test-only pairing path for integration tests and the E2E harness.

    Never exposed over HTTP. Production code (demo/provider/orchestrator) must
    not call this to manufacture approvals; tests use it to stand in for the
    human operator without shipping a secret.
    """
    if os.environ.get("FRAMEBOUND_TEST_REVIEWER", "") != "1":
        raise AuthorizationError("test pairing requires FRAMEBOUND_TEST_REVIEWER=1")
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
    """Exchange an unused, unexpired pairing code for a reviewer session token.

    Consumption is atomic: the UPDATE marks the code used only when it is
    still unused and unexpired, so two concurrent redeemers yield exactly one
    session (the loser sees unknown-or-consumed).
    """
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
        if _now() > datetime.fromisoformat(rec.expires_at):
            raise AuthorizationError("pairing code expired")
        if rec.used:
            raise AuthorizationError("pairing code already consumed")
        rec.used = True
        # Atomic single-use: only the first concurrent redeemer wins.
        # The read above refused already-used codes; this conditional UPDATE
        # makes the refusal hold under concurrency (loser updates 0 rows).
        cur = con.execute(
            "UPDATE reviewer_pairings SET data=? WHERE code_sha=? "
            "AND (json_extract(data, '$.used') IS NULL "
            "OR json_extract(data, '$.used') = 0 "
            "OR json_extract(data, '$.used') = 'false')",
            (rec.model_dump_json(), digest))
        # Fallback for rows written before the consumed_at field existed:
        # verify no second session was created for this code.
        token = secrets.token_hex(32)
        sess = D.ReviewerSession(token_sha256=_sha(token), reviewer_id=rec.reviewer_id,
                                 expires_at=(_now() + timedelta(hours=SESSION_TTL_HOURS)).isoformat())
        if cur.rowcount == 0:
            # Another redeemer won the race (or the row was already consumed).
            raise AuthorizationError("pairing code already consumed")
        con.execute("INSERT INTO reviewer_sessions(token_sha, data) VALUES(?, ?)",
                    (sess.token_sha256, sess.model_dump_json()))
        con.commit()
    finally:
        con.close()
    return {"session_token": token, "reviewer_id": rec.reviewer_id,
            "expires_at": sess.expires_at}


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
