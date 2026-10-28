"""Muse Spark adapter: structured tool loop + advisory critique. Critique never gates.

Wire: POST {BASE}/responses, model muse-spark-1.3, input messages with
`input_text` + `input_image` (data URL/file_id — never bare asset IDs), flat
function tools, `tool_choice: "auto"`. Model returns `function_call` items;
we execute allowlisted tools locally and return `function_call_output` items
with matching `call_id`, chained via `previous_response_id`.
"""
from __future__ import annotations

import json
import os

from ..services.errors import InvalidInput
from . import wire as W

MODEL_ENV = "FRAMEBOUND_VISION_MODEL"
DEFAULT_MODEL = "muse-spark-1.3"

# Allowlisted local tools the critic may invoke. Anything else is refused and
# reported back as an error string the model can recover from.
ALLOWED_TOOLS = {
    "get_deterministic_findings": {
        "type": "function",
        "name": "get_deterministic_findings",
        "description": "Return the deterministic check findings for the evaluated revision.",
        "parameters": {"type": "object",
                       "properties": {"revision_id": {"type": "string"}},
                       "required": ["revision_id"]},
    },
    "get_reference_metadata": {
        "type": "function",
        "name": "get_reference_metadata",
        "description": "Return stored (non-pixel) metadata for an approved reference asset.",
        "parameters": {"type": "object",
                       "properties": {"asset_id": {"type": "string"}},
                       "required": ["asset_id"]},
    },
}


def _model() -> str:
    return os.environ.get(MODEL_ENV) or DEFAULT_MODEL


def critique_request(contract_summary: str, fault_codes: list[str],
                     frame_blobs: list[dict]) -> dict:
    """Build the documented wire payload. frame_blobs carry transmittable pixels."""
    if not contract_summary or not contract_summary.strip():
        raise InvalidInput("spark critique needs a contract summary")
    blobs = frame_blobs or []
    if not blobs:
        raise InvalidInput("spark critique needs >=1 frame image to review")
    images = []
    for f in blobs:
        if not isinstance(f, dict) or not f.get("bytes_b64"):
            raise InvalidInput("spark frame needs bytes_b64 from the stored revision")
        if str(f.get("bytes_b64", "")).startswith("<"):
            raise InvalidInput("spark frame carries a redaction stub, not pixels")
        if f.get("file_id"):
            images.append({"type": "input_image", "file_id": f["file_id"], "detail": "auto"})
        else:
            images.append({"type": "input_image",
                           "image_url": W.data_url(f.get("mime") or "image/png",
                                                   f["bytes_b64"]), "detail": "auto"})
    req = {
        "model": _model(),
        "tool_choice": "auto",
        "parallel_tool_calls": True,
        "tools": [ALLOWED_TOOLS["get_deterministic_findings"],
                  ALLOWED_TOOLS["get_reference_metadata"]],
        "input": [
            {"role": "system", "content": [
                {"type": "input_text",
                 "text": "Review animation frames against the frozen contract. "
                 "Name visible inconsistencies with frame/time ids, uncertainty, and evidence refs. "
                 "Do not approve art; a technical pass is not acceptance. "
                 "Use tools for deterministic findings/reference metadata when needed."}]},
            {"role": "user", "content": [
                {"type": "input_text",
                 "text": f"Contract: {contract_summary}\nDeterministic findings: {', '.join(fault_codes) or 'none'}"},
                *images,
            ]},
        ],
    }
    violations = W.validate_spark_request(req)
    if violations:
        raise InvalidInput("built spark request fails wire validation: " + "; ".join(violations))
    return req


def parse_response(body: dict) -> dict:
    return W.parse_spark_response(body)


def parse_structured_critique(obj: dict) -> dict:
    return W.parse_structured_critique(obj)


def execute_tool_calls(calls: list[dict], *, handlers: dict | None = None) -> list[dict]:
    """Execute allowlisted calls; return function_call_output items keyed by call_id.

    Unknown tools and invalid arguments become error outputs (recoverable by
    the model), except structural problems (missing call_id) which raise.
    """
    handlers = handlers or {}
    outputs = []
    for c in calls:
        call_id = c.get("call_id")
        name = c.get("name")
        args = c.get("arguments", {})
        if not call_id or not name:
            raise InvalidInput("tool call lacks call_id/name; refusing to guess the match")
        if name not in ALLOWED_TOOLS:
            outputs.append({"type": "function_call_output", "call_id": call_id,
                            "output": json.dumps({"error": f"tool {name!r} is not allowlisted"})})
            continue
        fn = handlers.get(name)
        if fn is None:
            outputs.append({"type": "function_call_output", "call_id": call_id,
                            "output": json.dumps({"error": f"tool {name!r} has no local handler"})})
            continue
        if not isinstance(args, dict):
            outputs.append({"type": "function_call_output", "call_id": call_id,
                            "output": json.dumps({"error": "arguments must be a JSON object"})})
            continue
        try:
            result = fn(**args)
            outputs.append({"type": "function_call_output", "call_id": call_id,
                            "output": json.dumps(result)[:8000]})
        except TypeError as e:
            outputs.append({"type": "function_call_output", "call_id": call_id,
                            "output": json.dumps({"error": f"invalid arguments: {e}"})})
    # Every output must match its originating call; a mismatch is a 400-class bug.
    # Zero calls is a valid terminal text answer: nothing to match, nothing sent.
    if calls:
        check_follow_up(outputs, calls)
    return outputs


def check_follow_up(outputs: list[dict], calls: list[dict]) -> None:
    """Reject a follow-up whose outputs do not exactly answer the calls.

    Mirrors the server rule: every `function_call_output.call_id` must match a
    `function_call.call_id` from the same turn (`HTTP 400` on mismatch).
    """
    ids_in = {c.get("call_id") for c in calls}
    ids_out = {o.get("call_id") for o in outputs}
    if not ids_in or ids_in != ids_out:
        raise InvalidInput("function_call_output call_ids do not match the originating "
                           "calls; the Responses API rejects this with HTTP 400")


def _origin(transport) -> str:
    """Explicit execution origin: injected transports are simulated, never live."""
    return "simulated-transport" if transport is not None else "live"


def submit_critique(contract_summary: str, fault_codes: list[str],
                    frame_blobs: list[dict], project_dir: str, *,
                    offline: bool = False, transport=None,
                    timeout: float = 120.0, handlers: dict | None = None,
                    max_turns: int = 3) -> dict:
    """Run the real bounded Spark tool loop and return the terminal critique.

    A completed text-only answer is a valid terminal turn (no empty tool calls
    are executed). Tool turns are executed locally through allowlisted handlers
    and their outputs ARE sent back chained via previous_response_id, up to
    max_turns total requests. Exceeding the turn budget or receiving an
    incomplete/failed/refused/truncated response is an explicit halt, never a
    silent pass. Advisory criticism never gates deterministic evaluation.
    """
    from .base import _key, http_post
    from .ledger import record_artifact
    req = critique_request(contract_summary, fault_codes, frame_blobs)
    redacted = W.redact_wire(req)
    if offline or not _key():
        digest = record_artifact(project_dir, "spark_request",
                                 {"request": redacted, "sent": False,
                                  "offline": bool(offline), "model": req["model"]},
                                 provider="spark", model=req["model"])
        return {"mode": "not_configured", "sent": False, "request_artifact": digest,
                "note": "Advisory only; deterministic checks remain the gate.",
                "wire_model": req["model"], "origin": "not_configured"}
    origin = _origin(transport)
    req_digest = record_artifact(project_dir, "spark_request",
                                 {"request": redacted, "sent": True,
                                  "model": req["model"], "origin": origin},
                                 provider="spark", model=req["model"])
    turns: list[dict] = []
    # Exactly one dispatch per turn, bounded by max_turns: no auto-retry of a
    # possibly-accepted request. Transport errors surface to the caller for an
    # explicit reconcile/abandon decision upstream.
    body = http_post(W.RESPONSE_PATH, req, timeout=timeout, transport=transport)
    parsed = parse_response(body)
    turns.append({"request_artifact": req_digest, "response_id": parsed["response_id"],
                  "call_count": len(parsed["calls"]), "text_len": len(parsed["text"])})
    total_calls = list(parsed["calls"])
    tool_outputs: list[dict] = []
    text = parsed["text"]
    response_id = parsed["response_id"]
    if parsed["calls"]:
        seen_ids = [c["call_id"] for c in parsed["calls"]]
        if len(set(seen_ids)) != len(seen_ids):
            raise InvalidInput("spark turn repeats a call_id: refusing an ambiguous tool turn")
    while parsed["calls"] and len(turns) < max_turns:
        outputs = execute_tool_calls(parsed["calls"], handlers=handlers or {})
        tool_outputs.extend(outputs)
        follow_up = {"model": _model(), "previous_response_id": parsed["response_id"],
                     "tool_choice": "auto",
                     "tools": [ALLOWED_TOOLS["get_deterministic_findings"],
                               ALLOWED_TOOLS["get_reference_metadata"]],
                     "input": outputs}
        fup_digest = record_artifact(project_dir, "spark_request",
                                     {"request": W.redact_wire(follow_up), "sent": True,
                                      "model": req["model"],
                                      "previous_response_id": parsed["response_id"],
                                      "origin": origin},
                                     provider="spark", model=req["model"])
        body = http_post(W.RESPONSE_PATH, follow_up, timeout=timeout, transport=transport)
        parsed = parse_response(body)
        turns.append({"request_artifact": fup_digest, "response_id": parsed["response_id"],
                      "call_count": len(parsed["calls"]), "text_len": len(parsed["text"])})
        total_calls.extend(parsed["calls"])
        text = (text + "\n" + parsed["text"]).strip() if parsed["text"] else text
        response_id = parsed["response_id"]
        if parsed["calls"]:
            seen_ids = [c["call_id"] for c in parsed["calls"]]
            if len(set(seen_ids)) != len(seen_ids):
                raise InvalidInput("spark turn repeats a call_id: refusing an ambiguous tool turn")
    halted = bool(parsed["calls"])
    digest = record_artifact(project_dir, "spark_response",
                             {"request_artifact": req_digest,
                              "request": redacted, "sent": True, "model": req["model"],
                              "response_id": response_id,
                              "call_count": len(total_calls),
                              "turns": len(turns), "halted_on_turn_budget": halted,
                              "origin": origin},
                             provider="spark", model=req["model"],
                             request_id=str(response_id or ""))
    critique = _final_critique(text)
    return {"mode": "live", "sent": True, "request_artifact": req_digest,
            "response_artifact": digest,
            "response_id": response_id, "calls": total_calls,
            "text": text, "tool_outputs": tool_outputs,
            "turns": turns, "halted_on_turn_budget": halted,
            "origin": origin, "critique": critique,
            "advisory": "critique never gates; deterministic evaluation decides"}


def _final_critique(text: str) -> dict:
    """Integrate structured-critique parsing with the completed live loop.

    A JSON findings body in the terminal text validates into findings with
    frame/time association and uncertainty; anything else yields a reviewable
    diagnostic carrying the raw text length. Advisory only: never approval,
    never a gate override.
    """
    import json as _json
    stripped = (text or "").strip()
    if not stripped:
        return {"findings": [], "summary": "",
                "diagnostic": "empty terminal text: no advisory content to parse",
                "advisory": True}
    try:
        obj = _json.loads(stripped)
    except Exception:
        return {"findings": [], "summary": stripped[:500],
                "diagnostic": "terminal text is not structured JSON: kept as prose advisory",
                "advisory": True}
    try:
        out = parse_structured_critique(obj)
        out["diagnostic"] = ""
        return out
    except Exception as e:
        return {"findings": [], "summary": stripped[:500],
                "diagnostic": f"structured parse failed and is reviewable, not fatal: {e}",
                "advisory": True}
