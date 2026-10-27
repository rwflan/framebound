"""MCP server (stdio, line-delimited JSON-RPC) exposing the same tools
as the CLI. The orchestrating model is the primary consumer: it calls
these tools to bound and verify its own animation work before any
human review. Run: framebound mcp
"""
import json
import sys
from pathlib import Path

TOOLS = [
    {"name": "check_clip", "description": "Run all consistency checks on a contract project. Returns named issue codes, metrics, and evidence_id.",
     "inputSchema": {"type": "object", "properties": {"contract": {"type": "string"}}, "required": ["contract"]}},
    {"name": "compile_brief", "description": "Compile a hash-bound generation brief for one slot (master + identity + phase + neighbours).",
     "inputSchema": {"type": "object", "properties": {"contract": {"type": "string"}, "slot": {"type": "integer"}, "out": {"type": "string"}}, "required": ["contract", "slot", "out"]}},
    {"name": "preflight_candidate", "description": "Read-only check of proposed replacement frames. Never promotes art.",
     "inputSchema": {"type": "object", "properties": {"contract": {"type": "string"}, "manifest": {"type": "string"}}, "required": ["contract", "manifest"]}},
    {"name": "plan_repair", "description": "Turn a failing report into bounded redraw tasks with instructions per issue code.",
     "inputSchema": {"type": "object", "properties": {"report": {"type": "string"}, "out": {"type": "string"}}, "required": ["report", "out"]}},
    {"name": "evaluate_repair", "description": "Evaluate a candidate batch: protection, strict improvement, zero remaining errors.",
     "inputSchema": {"type": "object", "properties": {"contract": {"type": "string"}, "manifest": {"type": "string"}, "out": {"type": "string"}}, "required": ["contract", "manifest", "out"]}},
    {"name": "export_dataset", "description": "Export COCO + Hugging Face + preference + temporal training data from a checked project.",
     "inputSchema": {"type": "object", "properties": {"contract": {"type": "string"}, "out": {"type": "string"}}, "required": ["contract", "out"]}},
    {"name": "list_corrections", "description": "List open human correction tasks from the review desk database.",
     "inputSchema": {"type": "object", "properties": {"contract": {"type": "string"}}, "required": ["contract"]}},
]


def call_tool(name, args):
    from .audit import audit, preflight
    from .brief import compile_brief
    from .repair import plan, evaluate
    from .dataset import export_dataset
    if name == "check_clip":
        return audit(args["contract"])
    if name == "compile_brief":
        path, brief = compile_brief(args["contract"], args["slot"], args["out"])
        return {"brief": str(path), **brief}
    if name == "preflight_candidate":
        return preflight(args["contract"], args["manifest"])
    if name == "plan_repair":
        return plan(args["report"], args["out"])
    if name == "evaluate_repair":
        return evaluate(args["contract"], args["manifest"], args["out"])
    if name == "export_dataset":
        return export_dataset(args["contract"], args["out"])
    if name == "list_corrections":
        import sqlite3
        db_path = Path(args["contract"]).resolve().parent / "review.db"
        if not db_path.is_file():
            return {"tasks": []}
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT id,slot,category,note FROM issues WHERE status='open' ORDER BY id").fetchall()
        return {"tasks": [{"task_id": r[0], "slot": r[1], "code": r[2], "note": r[3]} for r in rows]}
    raise ValueError(f"Unknown tool {name}")


def serve_stdio():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        method, rid = req.get("method"), req.get("id")
        try:
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "framebound", "version": "0.1.0"}}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                result = {"content": [{"type": "text", "text": json.dumps(
                    call_tool(req["params"]["name"], req["params"].get("arguments", {})))}]}
            elif method == "ping":
                result = {}
            else:
                raise ValueError(f"Unknown method {method}")
            resp = {"jsonrpc": "2.0", "id": rid, "result": result}
        except Exception as exc:  # tool errors are data for the model, not crashes
            resp = {"jsonrpc": "2.0", "id": rid, "error": {"code": -32000, "message": str(exc)}}
        print(json.dumps(resp), flush=True)
