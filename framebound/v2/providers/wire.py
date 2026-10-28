"""Documented Meta Responses wire DTOs, validators, and response parsers.

Separates internal conditioning models from actual HTTP wire encoding.
Primary sources (rechecked 2026-10-27):
- Image generation: Responses `client.responses.create(model="muse-image-1.0", ...)`
  with `input=[{"role": "user", "content": [{"type": "input_text", ...},
  {"type": "input_image", "image_url": <data: or https: URL> | "file_id": ...}]}]`;
  wrapped message required (bare part lists rejected); `previous_response_id`
  chains refinements; success = `status == "completed"` plus an
  `image_generation_call` output item whose `result` is decodable base64 image
  bytes; `usage` carries token counts.
- Tool calling: Responses flat tools `{"type": "function", "name": ...,
  "description": ..., "parameters": {...}}`, `tool_choice` only `"auto"`;
  model returns `function_call` output items (`call_id`, `name`, `arguments`);
  results return as `function_call_output` items with matching `call_id`,
  chained via `previous_response_id`.
- SAM 3.1: Responses `model="sam-3.1"`, one user message with `input_text`
  concept + `input_image`/`input_video`; result streams in the `output_text`
  lane as special-token text, one `<Nf>` line per frame, each record
  `<obj><|box;...|><|mask;...|>`, mask payload base85 (`~` lossless / `!`
  one-bit). Empty lane with `response.completed` is a valid no-match.

This module never sends network traffic; it builds/validates/parses.
"""
from __future__ import annotations

import base64
import copy
import json
import re
from typing import Any

from ..services.errors import ResponseInvalid

RESPONSE_PATH = "/responses"

IMAGE_DETAIL = {"high", "low", "auto", "original"}

# Legacy v1/prototype markers that must never appear on the wire. Each is a
# distinct historical shortcut the audit reproduced.
_LEGACY_PART_TYPES = {"text", "image", "image_b64"}
_LEGACY_PART_KEYS = {"image_b64", "asset_id", "byte_sha256", "role", "frame",
                     "endpoint", "note"}
_PLACEHOLDER_URLS = ("<bytes>", "<redacted>", "<bytes-redacted")


def data_url(mime: str, raw_b64: str) -> str:
    mime = mime or "image/png"
    return f"data:{mime};base64,{raw_b64}"


def redact_wire(obj: Any) -> Any:
    """Deep-copy with image/file payloads replaced by length-annotated stubs.

    Redaction applies to stored artifacts only; `validate_*` rejects these
    stubs as transmitted values.
    """
    def _red(v: Any) -> Any:
        if isinstance(v, dict):
            out = {}
            for k, val in v.items():
                if k in ("image_url", "file_data", "file_url") and isinstance(val, str) \
                        and (val.startswith("data:") or len(val) > 64):
                    out[k] = f"<bytes-redacted:{len(val)}>"
                elif k in ("image_b64", "result") and isinstance(val, str) and len(val) > 32:
                    out[k] = f"<bytes-redacted:{len(val)}>"
                elif k.lower() in ("authorization", "api_key", "model_api_key"):
                    out[k] = "<secret-redacted>"
                else:
                    out[k] = _red(val)
            return out
        if isinstance(v, list):
            return [_red(i) for i in v]
        return v
    return _red(copy.deepcopy(obj))


def _is_message(m: Any) -> bool:
    return isinstance(m, dict) and isinstance(m.get("role"), str) \
        and isinstance(m.get("content"), list)


def _validate_image_part(part: dict, where: str) -> list[str]:
    errs: list[str] = []
    if not isinstance(part, dict):
        return [f"{where}: part must be an object"]
    t = part.get("type")
    if t == "input_text":
        if not isinstance(part.get("text"), str) or not part["text"].strip():
            errs.append(f"{where}: input_text needs non-empty text")
    elif t == "input_image":
        url = part.get("image_url")
        fid = part.get("file_id")
        if (url is None) == (fid is None):
            errs.append(f"{where}: input_image needs exactly one of image_url/file_id")
        if url is not None:
            if not isinstance(url, str) or not url:
                errs.append(f"{where}: image_url must be a non-empty string")
            elif url in _PLACEHOLDER_URLS or url.startswith("<"):
                errs.append(f"{where}: image_url is a placeholder; transmit real data URLs or file IDs")
            elif not (url.startswith("data:image/") or url.startswith("https://")):
                errs.append(f"{where}: image_url must be a data: or https: URL, got {url[:24]!r}")
        if fid is not None and (not isinstance(fid, str) or not fid.strip()):
            errs.append(f"{where}: file_id must be a non-empty string")
        if "detail" in part and part["detail"] not in IMAGE_DETAIL:
            errs.append(f"{where}: detail must be one of {sorted(IMAGE_DETAIL)}")
    elif t == "input_video":
        url = part.get("video_url") or part.get("image_url")
        fid = part.get("file_id")
        if url is None and fid is None:
            errs.append(f"{where}: input_video needs a video URL or file_id")
    elif t in _LEGACY_PART_TYPES:
        errs.append(f"{where}: legacy part type {t!r}; use input_text/input_image")
    else:
        errs.append(f"{where}: unknown part type {t!r}")
    for k in _LEGACY_PART_KEYS:
        if k in part and t in ("input_text", "input_image", "input_video"):
            errs.append(f"{where}: wire part must not carry internal key {k!r}")
    return errs


def validate_image_request(req: dict) -> list[str]:
    """Strict contract test for generation wire payloads. Empty == acceptable."""
    errs: list[str] = []
    if not isinstance(req, dict):
        return ["request must be an object"]
    if not req.get("model") or not isinstance(req.get("model"), str):
        errs.append("model must be a non-empty string")
    for k in ("endpoint", "note"):
        if k in req:
            errs.append(f"top-level {k!r} is a diagnostic stub, not a wire field")
    prev = req.get("previous_response_id")
    if prev is not None and (not isinstance(prev, str) or not prev.strip()):
        errs.append("previous_response_id must be a non-empty string when present")
    inp = req.get("input")
    if isinstance(inp, str):
        if not inp.strip():
            errs.append("string input must be non-empty")
        return errs
    if not isinstance(inp, list) or not inp:
        return errs + ["input must be a non-empty string or message list"]
    if any(not _is_message(m) for m in inp):
        errs.append("input list must contain {role, content:[...]} messages; bare part lists are rejected")
        return errs
    n_images = 0
    n_text = 0
    for i, msg in enumerate(inp):
        content = msg.get("content", [])
        for j, part in enumerate(content):
            where = f"input[{i}].content[{j}]"
            errs.extend(_validate_image_part(part, where))
            if isinstance(part, dict) and part.get("type") == "input_image":
                n_images += 1
            if isinstance(part, dict) and part.get("type") == "input_text":
                n_text += 1
    if n_text < 1:
        errs.append("generation input needs at least one input_text instruction")
    need = 1 if prev else 2
    if n_images < need:
        errs.append(f"generation input needs >={need} input_image parts "
                    f"({'refine chain' if prev else 'identity + style'}), got {n_images}")
    return errs


def validate_spark_request(req: dict) -> list[str]:
    # Critique needs >=1 frame image (not the >=2 identity+style generation rule).
    errs = validate_image_request(req)
    errs = [e for e in errs if not e.startswith("generation input needs >=")]
    if not any(isinstance(m, dict) and isinstance(m.get("content"), list)
               for m in (req.get("input") or [])):
        pass
    else:
        n_images = sum(1 for m in req.get("input", []) if isinstance(m, dict)
                       for c in m.get("content", [])
                       if isinstance(c, dict) and c.get("type") == "input_image")
        if n_images < 1:
            errs.append("spark critique needs >=1 input_image frame part")
    tools = req.get("tools", [])
    if not isinstance(tools, list) or not tools:
        return errs + ["spark critique needs a non-empty tools list"]
    for i, t in enumerate(tools):
        where = f"tools[{i}]"
        if not isinstance(t, dict):
            errs.append(f"{where}: tool must be an object")
            continue
        if t.get("type", "function") != "function":
            errs.append(f"{where}.type must be 'function'")
        for k in ("name", "description", "parameters"):
            if k not in t:
                errs.append(f"{where}: missing {k!r} (flat Responses tool shape)")
        name = t.get("name", "")
        if isinstance(name, str) and not re.fullmatch(r"[A-Za-z0-9_.\-]{1,64}", name):
            errs.append(f"{where}.name violates ^[A-Za-z0-9_.-]+$ (max one dot)")
        elif isinstance(name, str) and name.count(".") > 1:
            errs.append(f"{where}.name has more than one dot")
        params = t.get("parameters")
        if params is not None and not isinstance(params, dict):
            errs.append(f"{where}.parameters must be a JSON-schema object")
    tc = req.get("tool_choice", "auto")
    if tc != "auto":
        errs.append('tool_choice must be "auto"; "none"/"required"/named choices return HTTP 400')
    return errs


def validate_sam_request(req: dict) -> list[str]:
    errs: list[str] = []
    if not isinstance(req, dict):
        return ["request must be an object"]
    if req.get("model") != "sam-3.1":
        errs.append("SAM model must be exactly 'sam-3.1'")
    inp = req.get("input")
    if not isinstance(inp, list) or not inp or any(not _is_message(m) for m in inp):
        return errs + ["SAM input must be a message list [{role, content:[...]}]"]
    kinds: list[str] = []
    for i, msg in enumerate(inp):
        for j, part in enumerate(msg.get("content", [])):
            where = f"input[{i}].content[{j}]"
            if not isinstance(part, dict):
                errs.append(f"{where}: part must be an object")
                continue
            t = part.get("type")
            if t == "input_text":
                if not isinstance(part.get("text"), str) or not part["text"].strip():
                    errs.append(f"{where}: concept prompt must be a non-empty noun phrase")
                elif len(part["text"]) > 160:
                    errs.append(f"{where}: concept prompt should be a short noun phrase, got {len(part['text'])} chars")
            elif t in ("input_image", "input_video"):
                kinds.append(t)
                errs.extend(_validate_image_part(
                    {"type": part["type"],
                     "image_url": part.get("image_url"), "file_id": part.get("file_id"),
                     **({"detail": part["detail"]} if "detail" in part else {})}
                    if t == "input_image" else part, where))
                url = part.get("image_url", "")
                if isinstance(url, str) and url in _PLACEHOLDER_URLS:
                    errs.append(f"{where}: placeholder image never transmits pixels")
            else:
                errs.append(f"{where}: SAM parts must be input_text + input_image/input_video, got {t!r}")
            for k in _LEGACY_PART_KEYS:
                if k in part:
                    errs.append(f"{where}: wire part must not carry internal key {k!r}")
    if "input_image" not in kinds and "input_video" not in kinds:
        errs.append("SAM input needs one input_image or input_video part")
    return errs


def parse_image_response(body: dict) -> dict:
    """Extract generated bytes from a Responses body. Raises ResponseInvalid."""
    if not isinstance(body, dict):
        raise ResponseInvalid("response_invalid: body must be an object")
    if body.get("status") != "completed":
        raise ResponseInvalid(f"response_invalid: status is {body.get('status')!r}, expected 'completed'")
    output = body.get("output")
    if not isinstance(output, list):
        raise ResponseInvalid("response_invalid: missing output item list")
    calls = [o for o in output if isinstance(o, dict) and o.get("type") == "image_generation_call"]
    if not calls:
        raise ResponseInvalid("response_invalid: no image_generation_call item in output")
    images = []
    for c in calls:
        result = c.get("result")
        if not isinstance(result, str) or not result.strip():
            raise ResponseInvalid("response_invalid: image_generation_call lacks a result payload")
        try:
            raw = base64.b64decode(result, validate=True)
        except Exception as e:
            raise ResponseInvalid(f"response_invalid: result is not valid base64: {e}") from e
        if not raw:
            raise ResponseInvalid("response_invalid: decoded image bytes are empty")
        images.append({"bytes": raw, "item_id": c.get("id"), "usage": body.get("usage"),
                       "response_id": body.get("id")})
    return {"images": images, "response_id": body.get("id"),
            "status": body.get("status"), "usage": body.get("usage")}


def parse_spark_response(body: dict) -> dict:
    """Split a Spark Responses body into function_calls + text. Raises ResponseInvalid.

    Status is enforced first: only `completed` yields a usable turn. Incomplete,
    failed, truncated, or refused responses are explicit errors, never an empty
    text or a silent no-call pass.
    """
    if not isinstance(body, dict):
        raise ResponseInvalid("response_invalid: body must be an object")
    status = body.get("status")
    if status != "completed":
        detail = body.get("error") or body.get("incomplete_details") or status
        raise ResponseInvalid(f"response_invalid: spark turn status is {status!r}, "
                              f"not 'completed': {str(detail)[:200]}")
    output = body.get("output", [])
    if not isinstance(output, list):
        raise ResponseInvalid("response_invalid: missing output item list")
    calls = []
    texts = []
    for o in output:
        if not isinstance(o, dict):
            continue
        t = o.get("type")
        if t == "function_call":
            call_id = o.get("call_id")
            name = o.get("name")
            args = o.get("arguments", "{}")
            if not call_id or not name:
                raise ResponseInvalid("response_invalid: function_call lacks call_id/name")
            try:
                parsed = json.loads(args) if isinstance(args, str) else args
            except Exception as e:
                raise ResponseInvalid(f"response_invalid: call {call_id} arguments are not JSON: {e}") from e
            calls.append({"call_id": call_id, "name": name, "arguments": parsed,
                          "status": o.get("status")})
        elif t in ("message", "output_text"):
            content = o.get("content") or o.get("text") or ""
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict) and c.get("type") in ("output_text", "text"):
                        texts.append(c.get("text", ""))
            elif isinstance(content, str):
                texts.append(content)
    return {"calls": calls, "text": "\n".join(t for t in texts if t),
            "response_id": body.get("id"), "status": body.get("status")}


def parse_structured_critique(obj: dict) -> dict:
    """Validate the advisory structured-critic schema. Raises ResponseInvalid."""
    if not isinstance(obj, dict):
        raise ResponseInvalid("response_invalid: structured critique must be an object")
    findings = obj.get("findings")
    if not isinstance(findings, list):
        raise ResponseInvalid("response_invalid: critique needs a findings list")
    clean = []
    for i, f in enumerate(findings):
        if not isinstance(f, dict):
            raise ResponseInvalid(f"response_invalid: finding[{i}] must be an object")
        frame = f.get("frame")
        note = f.get("note") or f.get("description") or ""
        if not isinstance(frame, int) or isinstance(frame, bool) or frame < 0:
            raise ResponseInvalid(f"response_invalid: finding[{i}].frame must be a tick/frame int")
        if not isinstance(note, str) or not note.strip():
            raise ResponseInvalid(f"response_invalid: finding[{i}] needs a note")
        unc = f.get("uncertainty", 0.5)
        if not isinstance(unc, (int, float)) or not (0.0 <= float(unc) <= 1.0):
            raise ResponseInvalid(f"response_invalid: finding[{i}].uncertainty must be 0..1")
        ev = f.get("evidence_refs", [])
        if not isinstance(ev, list):
            raise ResponseInvalid(f"response_invalid: finding[{i}].evidence_refs must be a list")
        clean.append({"frame": frame, "note": note.strip(),
                      "uncertainty": float(unc), "evidence_refs": [str(e) for e in ev]})
    return {"findings": clean, "summary": str(obj.get("summary", "")),
            "advisory": True}


# ---------------------------------------------------------------- SAM grammar
_BOX_RE = re.compile(
    r"(\d+)<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)(;c=([0-9]+(?:\.[0-9]+)?))?\|>")
_MASK_RE = re.compile(
    r"<\|mask;x=0;y=0(;c=([0-9]+(?:\.[0-9]+)?))?;data=(\d+),(\d+),([~!])(.*?)\|>",
    re.DOTALL)
_FRAME_RE = re.compile(r"<(\d+)f>")


def _b85decode(payload: str) -> bytes:
    data = payload.strip().encode("ascii")
    try:
        # RFC1924 base85 (the documented SAM mask encoding).
        return base64.b85decode(data)
    except Exception:
        # Tolerate plain Ascii85 (no Adobe markers) once before failing.
        try:
            return base64.a85decode(data, adobe=False)
        except Exception as e:
            raise ValueError(f"mask payload is not base85-decodable: {e}") from e


def _unpack_bits(raw: bytes, h: int, w: int) -> bytes:
    need = h * w
    out = bytearray(need)
    pos = 0
    for byte in raw:
        for bit in range(7, -1, -1):
            if pos >= need:
                break
            out[pos] = (byte >> bit) & 1
            pos += 1
    if pos < need:
        raise ValueError(f"bit payload covers {pos} of {need} pixels")
    return bytes(out)


def decode_sam_payload(h: int, w: int, enc: str, payload: str) -> bytes:
    """Decode one mask record payload to a row-major 0/1 raster of H*W bytes."""
    if h <= 0 or w <= 0 or h * w > 2048 * 2048:
        raise ValueError(f"mask raster dimensions rejected: {h}x{w}")
    raw = _b85decode(payload)
    if enc == "!":
        if len(raw) * 8 < h * w or len(raw) > (h * w + 7) // 8 + 1:
            raise ValueError(f"one-bit payload {len(raw)} bytes misaligned with {h}x{w}")
        return _unpack_bits(raw, h, w)
    # "~" lossless: accept byte-per-pixel, else bit-packed fallback; anything
    # else is corrupt rather than a silent mis-decode.
    if len(raw) == h * w and set(raw) <= {0, 1}:
        return bytes(raw)
    if len(raw) * 8 >= h * w and len(raw) <= (h * w + 7) // 8 + 1:
        raster = _unpack_bits(raw, h, w)
        return raster
    raise ValueError(f"lossless payload {len(raw)} bytes misaligned with {h}x{w}; "
                     "not byte-per-pixel nor bit-packed")


def parse_sam_output_text(text: str, *, source_width: int | None = None,
                          source_height: int | None = None,
                          status: str | None = None) -> dict:
    """Parse SAM special-token output_text into geometry records.

    Returns {outcome, records, ...} where outcome is one of
    no_match | mask | empty | full | corrupt | failed. Never raises for model
    content; structural problems are reported as corrupt with a reason. An
    empty lane is a valid no-match ONLY for a completed response: failed,
    incomplete, or truncated responses are provider failures, never no-match.
    """
    if status is not None and status != "completed":
        return {"outcome": "failed",
                "reason": f"SAM response status is {status!r}, not 'completed': "
                          "provider failure, never a valid empty segmentation",
                "records": []}
    if not isinstance(text, str) or not text.strip():
        if status is None:
            return {"outcome": "corrupt",
                    "reason": "empty output_text lane with unknown response status: "
                              "completion unconfirmed, refusing a no-match verdict",
                    "records": []}
        return {"outcome": "no_match", "reason": "empty output_text lane with response.completed",
                "records": []}
    records = []
    frame_sizes: set[tuple[int, int]] = set()
    for raw_line in text.strip().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = _FRAME_RE.match(line)
        if not m:
            return {"outcome": "corrupt", "reason": f"line lacks a <Nf> frame marker: {line[:60]!r}",
                    "records": []}
        frame = int(m.group(1))
        rest = line[m.end():]
        pos = 0
        line_records = 0
        while pos < len(rest):
            if rest[pos] == ",":
                pos += 1
                continue
            bm = _BOX_RE.match(rest, pos)
            if not bm:
                return {"outcome": "corrupt",
                        "reason": f"record @frame {frame} lacks <obj><|box;...|> (offset {pos})",
                        "records": []}
            obj = int(bm.group(1))
            x1, y1, x2, y2, w, h = (int(bm.group(i)) for i in range(2, 8))
            conf_b = float(bm.group(9)) if bm.group(9) is not None else None
            mm = _MASK_RE.match(rest, bm.end())
            if not mm:
                return {"outcome": "corrupt",
                        "reason": f"record {obj}@frame {frame} pairs no <|mask;...|> after its box",
                        "records": []}
            conf_m = float(mm.group(2)) if mm.group(2) is not None else None
            mh, mw, enc, payload = int(mm.group(3)), int(mm.group(4)), mm.group(5), mm.group(6)
            if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
                return {"outcome": "corrupt",
                        "reason": f"box {obj}@frame {frame} [{x1},{y1},{x2},{y2}] outside {w}x{h}",
                        "records": []}
            frame_sizes.add((w, h))
            try:
                raster = decode_sam_payload(mh, mw, enc, payload)
            except ValueError as e:
                return {"outcome": "corrupt",
                        "reason": f"mask {obj}@frame {frame} undecodable: {e}", "records": []}
            fg = sum(1 for b in raster if b)
            records.append({"frame": frame, "object_id": obj,
                            "box": {"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                                    "frame_w": w, "frame_h": h,
                                    **({"confidence": conf_b} if conf_b is not None else {})},
                            "mask": {"height": mh, "width": mw, "encoding": enc,
                                     "raster": raster, "foreground": fg,
                                     **({"confidence": conf_m} if conf_m is not None else {})}})
            line_records += 1
            pos = mm.end()
        if line_records == 0:
            return {"outcome": "corrupt",
                    "reason": f"frame line {frame} carries no box+mask records", "records": []}
    if not records:
        return {"outcome": "no_match", "reason": "no frame lines carried records", "records": []}
    if source_width is not None and any(w != source_width or h != source_height
                                        for (w, h) in frame_sizes):
        return {"outcome": "corrupt",
                "reason": f"SAM frame size {sorted(frame_sizes)} disagrees with source "
                          f"{source_width}x{source_height}", "records": records}
    if all(sum(1 for b in r["mask"]["raster"] if b) == 0 for r in records):
        return {"outcome": "empty",
                "reason": "SAM returned all-zero rasters; unmeasured, never pass-by-zero-area",
                "records": records}
    dims = {(r["mask"]["width"], r["mask"]["height"]) for r in records}
    if len(dims) == 1:
        mw, mh = next(iter(dims))
        if all(sum(1 for b in r["mask"]["raster"] if b) == mw * mh for r in records):
            return {"outcome": "full",
                    "reason": "SAM returned full-frame rasters; not a subject mask",
                    "records": records}
    return {"outcome": "mask", "reason": f"decoded {len(records)} record(s) across "
            f"{len({r['frame'] for r in records})} frame(s)", "records": records}
