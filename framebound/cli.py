"""Framebound CLI. Every command reads and writes JSON so the primary
consumer, an orchestrating model, never has to parse prose."""
import argparse
import json
import sys
import time
from pathlib import Path


def _print(obj):
    print(json.dumps(obj, indent=2))


def main(argv=None):
    p = argparse.ArgumentParser(prog="framebound", description="Consistency bounds for AI-generated 2D animation.")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="Run all consistency checks on a contract")
    c.add_argument("--contract", required=True)
    c.add_argument("--report", help="Write the report JSON here")
    c.add_argument("--anchors", help="JSON file mapping slot to reviewed [x, y] anchor")

    b = sub.add_parser("brief", help="Compile a hash-bound generation brief for one slot")
    b.add_argument("--contract", required=True); b.add_argument("--slot", type=int, required=True)
    b.add_argument("--out", required=True)

    pf = sub.add_parser("preflight", help="Read-only check of candidate replacement frames")
    pf.add_argument("--contract", required=True); pf.add_argument("--manifest", required=True)
    pf.add_argument("--report")

    rp = sub.add_parser("repair-plan", help="Turn a failing report into bounded repair tasks")
    rp.add_argument("--report", required=True); rp.add_argument("--out", required=True)

    re_ = sub.add_parser("repair-evaluate", help="Evaluate a repair candidate batch")
    re_.add_argument("--contract", required=True); re_.add_argument("--manifest", required=True)
    re_.add_argument("--out", required=True)

    rf = sub.add_parser("record-failure", help="Record a new failure case linked to a check code")
    rf.add_argument("--contract", required=True); rf.add_argument("--slot", type=int, required=True)
    rf.add_argument("--code", required=True); rf.add_argument("--symptom", required=True)
    rf.add_argument("--expected", required=True); rf.add_argument("--out", required=True)

    ex = sub.add_parser("export-dataset", help="Export COCO + HF + preference + temporal training data")
    ex.add_argument("--contract", required=True); ex.add_argument("--out", required=True)

    sv = sub.add_parser("serve", help="Start the persistent human review desk")
    sv.add_argument("--contract", required=False, default=None)
    sv.add_argument("--project", required=False, default=None)
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--db")

    dm = sub.add_parser("demo", help="Build and verify the procedural demo project end to end")
    dm.add_argument("--out", default="build/demo")
    dm.add_argument("--profile", default="v1", choices=["v1", "v2", "wp6"])
    dm.add_argument("--offline", action="store_true", default=False)
    dm.add_argument("--replace", action="store_true", default=False,
                    help="replace a previous framework-owned output (refuses unmarked dirs)")
    bm = sub.add_parser("benchmark", help="v2: run the procedural stress fixture and report timing")
    bm.add_argument("--fixture", default="stress-200", choices=["stress-200"])
    bm.add_argument("--report", help="Write the benchmark report JSON here")
    be = sub.add_parser("benchmark-eval", help="v2: benchmark the public evaluation service (cold/warm/incremental)")
    be.add_argument("--report", help="Write the benchmark report JSON here")
    be.add_argument("--warm-runs", default="25")
    be.add_argument("--cold-runs", default="5")
    mc = sub.add_parser("v2-mcp", help="v2: serve application services over MCP (stdio)")
    mc.add_argument("--project", required=True)
    rp = sub.add_parser("reviewer-pair", help="v2: pair a human reviewer (prints single-use code)")
    rp.add_argument("--project", required=True); rp.add_argument("--reviewer-id", required=True)
    rp.add_argument("--operator-secret", required=False, default=None,
                    help="operator secret (or FRAMEBOUND_OPERATOR_SECRET env)")
    ro = sub.add_parser("reviewer-open", help="v2: exchange a pairing code for a session token")
    ro.add_argument("--project", required=True); ro.add_argument("--code", required=True)
    gp = sub.add_parser("guide-propose", help="v2: propose a draft motion guide (orchestrator tool)")
    gp.add_argument("--project", required=True); gp.add_argument("--guide", required=True)
    gp.add_argument("--actor-id", required=False, default="cli")
    ra = sub.add_parser("reference-approve", help="v2: reviewer-approves references (needs session token)")
    ra.add_argument("--project", required=True); ra.add_argument("--character", required=True)
    ra.add_argument("--guide", required=True); ra.add_argument("--event-id", required=False, default=None)
    ra.add_argument("--session-token", required=False, default=None)
    for name, helps, args in [
        ("project-create", "Create or resume a project", [("--project", True), ("--project-id", True), ("--name", False)]),
        ("character-propose", "Propose an immutable character", [("--project", True), ("--character", True)]),
        ("asset-import", "v2: import an image asset", [("--src", True), ("--asset-id", True), ("--project", True)]),
        ("contract-propose", "v2: validate + store a clip contract", [("--contract", True), ("--project", True)]),
        ("clip-create", "v2: create a clip revision", [("--contract-id", True), ("--revision-id", True), ("--project", True), ("--frames", True), ("--phases", True)]),
        ("clip-evaluate", "v2: evaluate a stored clip revision", [("--revision-id", True), ("--project", True)]),
        ("brief-compile", "v2: compile a conditioning bundle", [("--contract-id", True), ("--slot", True), ("--project", True)]),
        ("job-submit", "v2: submit a generation job (idempotent)", [("--brief", True), ("--project", True), ("--idempotency-key", True)]),
        ("job-get", "v2: read a persisted job", [("--job-id", True), ("--project", True)]),
        ("job-claim", "v2: claim a queued job with a lease", [("--job-id", True), ("--project", True), ("--worker-id", True), ("--expected-version", True)]),
        ("job-cancel", "v2: cancel a non-terminal job", [("--job-id", True), ("--project", True), ("--expected-version", True)]),
        ("job-reconcile", "v2: recover expired-lease RUNNING jobs", [("--project", True)]),
        ("orchestrator-run", "v2: start a durable orchestrator run", [("--project", True)]),
        ("orchestrator-send", "v2: authorized send-complete for one job (stored request; brief optional)", [("--project", True), ("--run-id", True), ("--job-id", True), ("--brief", False), ("--worker-id", True)]),
        ("capabilities", "v2: audited transport x operation table", [("--project", True)]),
        ("candidate-register", "v2: register replacements as a child revision", [("--baseline", True), ("--new-id", True), ("--project", True), ("--slots", True), ("--recipe", True)]),
        ("correction-submit", "v2: gated repair submit (holder+token+lease+scope+matrix)", [("--project", True), ("--task-id", True), ("--claim-token", True), ("--new-id", True), ("--slots", True), ("--recipe", True), ("--baseline-evaluation", True), ("--idempotency-key", True)]),
        ("correction-claim", "v2: claim an open correction task (worker holder)", [("--project", True), ("--task-id", True), ("--expected-version", True)]),
        ("correction-get", "v2: explicit correction task status", [("--project", True), ("--task-id", True)]),
        ("corrections-list-open", "v2: list open correction tasks", [("--project", True)]),
        ("mask-approve", "v2: reviewer-approve an edit mask (needs session token)", [("--project", True), ("--issue", True), ("--mask-asset", True), ("--slots", True), ("--session-token", False)]),
        ("issue-reopen", "v2: reviewer-reopen a resolved issue (needs session token)", [("--project", True), ("--issue", True), ("--session-token", False)]),
        ("eligibility", "v2: release eligibility for a revision", [("--project", True), ("--revision-id", True)]),
        ("world-trace-record", "v2: store frozen per-tick world grounding", [("--project", True), ("--revision-id", True), ("--positions", True), ("--planted", True)]),
        ("packet-create", "v2: curate a review packet", [("--packet-id", True), ("--revision-id", True), ("--evaluation-id", True), ("--project", True), ("--intent", False)]),
        ("corrections-list", "v2: list open correction tasks", [("--project", True)]),
    ]:
        c = sub.add_parser(name, help=helps)
        for flag, req in args:
            c.add_argument(flag, required=req)
        if name == "job-submit":
            c.add_argument("--offline", action="store_true", default=False,
                           help="never transmit even when a key is configured")
            c.add_argument("--max-attempts", default="3")
        if name == "orchestrator-run":
            c.add_argument("--jobs", default="")
            c.add_argument("--max-attempts", default="3")
        if name == "orchestrator-send":
            c.add_argument("--offline", action="store_true", default=False)
            c.add_argument("--fencing-token", default=None,
                           help="fencing token from job-claim (required to send)")
        if name == "correction-submit":
            c.add_argument("--transform", default=None)
            c.add_argument("--expected-version", default="1")
            c.add_argument("--actor-id", default="cli")
        if name == "correction-claim":
            c.add_argument("--actor-id", default="cli-worker")
            c.add_argument("--lease-minutes", default="30")
        if name == "issue-reopen":
            c.add_argument("--note", default="")

    sub.add_parser("mcp", help="Serve the same tools over MCP (stdio)")

    sub.add_parser("doctor", help="v2: check runtime, dependencies and project layout")
    mv = sub.add_parser("migrate-v1", help="v2: report v1 importability (dry run only)")
    mv.add_argument("--source", required=True)
    mv.add_argument("--dry-run", action="store_true", default=True)
    mv.add_argument("--report", help="Write the migration report JSON here")
    ex = sub.add_parser("export", help="v2: build a portable training snapshot")
    ex.add_argument("--project", required=True); ex.add_argument("--snapshot", required=True)
    ex.add_argument("--out", required=True); ex.add_argument("--revisions", required=True)
    ex.add_argument("--policy", required=False, default=None)
    ex.add_argument("--replace", action="store_true", default=False,
                    help="replace a previous framework-owned snapshot output (refuses unmarked dirs)")
    dv = sub.add_parser("dataset-validate", help="v2: validate a snapshot with standard loaders")
    dv.add_argument("--snapshot", required=True)
    rr = sub.add_parser("recorded-run", help="v2: DEPRECATED historical provider bundle (retired Spark gate; use offline check/repair + explicit providers)")
    rr.add_argument("--project", required=True)
    rr.add_argument("--contract", required=True)
    rr.add_argument("--slot", required=True)
    rr.add_argument("--baseline", required=True)
    rr.add_argument("--new-id", required=True)
    rr.add_argument("--out", required=True)
    rr.add_argument("--offline", action="store_true", default=False)
    rr.add_argument("--idempotency-key", required=False, default="recorded-run-1")
    vf = sub.add_parser("verify", help="v2: verify stored revisions, blobs and evidence freshness")
    vf.add_argument("--project", required=True)
    vf.add_argument("--report", help="Write the verification report JSON here")
    oj = sub.add_parser("openapi", help="v2: regenerate the committed OpenAPI schema")
    oj.add_argument("--out", required=True, help="Write the OpenAPI JSON schema here")

    args = p.parse_args(argv)
    if args.cmd == "doctor":
        from .v2.doctor import run_doctor
        _print(run_doctor())
        return 0
    if args.cmd == "migrate-v1":
        import json as _json
        from .v2.migration import dry_run as _dry
        rep = _dry(args.source)
        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(_json.dumps(rep, indent=2) + "\n")
        _print(rep)
        return 0
    if args.cmd == "export":
        import json as _json
        from .v2.exports import build_snapshot as _snap
        pol = _json.loads(open(args.policy).read()) if args.policy else {}
        if args.replace:
            pol["replace"] = True
        rep = _snap(args.project, args.snapshot, args.revisions.split(","), args.out, pol)
        _print({"snapshot": rep["snapshot"], "counts": rep["counts"],
                "exclusions": rep["exclusions"]})
        return 0
    if args.cmd == "recorded-run":
        from .v2 import recorded_run as _rr
        _print(_rr.run_recorded(args.project, args.out, contract_id=args.contract,
                                slot=int(args.slot), baseline_revision_id=args.baseline,
                                new_revision_id=args.new_id, offline=bool(args.offline),
                                idempotency_key=args.idempotency_key))
        return 0
    if args.cmd == "dataset-validate":
        from .v2.exports import validate_snapshot as _val
        rep = _val(args.snapshot)
        _print(rep)
        return 0 if rep["ok"] else 1
    if args.cmd == "openapi":
        import json as _json
        import tempfile as _tf
        from .v2.api.app import create_app as _create
        schema = _create(_tf.mkdtemp()).openapi()
        Path(args.out).write_text(_json.dumps(schema, indent=2) + "\n")
        _print({"paths": len(schema.get("paths", {})), "out": args.out})
        return 0
    if args.cmd == "verify":
        from .v2.verify import run_verify
        rep = run_verify(args.project)
        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(json.dumps(rep, indent=2) + "\n")
        _print({"ok": rep["ok"], "issues": rep["issues"]})
        return 0 if rep["ok"] else 1
    if args.cmd == "demo" and getattr(args, "profile", "v1") in ("v2", "wp6"):
        if getattr(args, "profile") == "wp6":
            from .v2.demo_wp6 import run_wp6 as _w6
            # Demos are offline procedural replays; they never send provider
            # traffic even when keys are configured (see --live spike in R3).
            _print(_w6(args.out, replace=args.replace, offline=True))
            return 0
        from .v2.demo import run_demo
        _print(run_demo(args.out, replace=args.replace))
        return 0
    if args.cmd == "v2-mcp":
        import asyncio as _aio
        from .v2.mcp import build_server as _bs
        _s = _bs(args.project)
        _aio.run(_s.run_stdio_async())
        return 0
    if args.cmd in ("project-create", "character-propose", "asset-import", "contract-propose", "clip-create", "clip-evaluate",
                    "brief-compile", "job-submit", "job-get", "job-claim",
                    "job-cancel", "job-reconcile", "orchestrator-run",
                    "orchestrator-send", "capabilities", "correction-claim", "correction-submit",
                    "correction-get", "corrections-list-open", "mask-approve",
                    "issue-reopen", "eligibility", "candidate-register",
                    "packet-create", "corrections-list", "reviewer-pair", "reviewer-open",
                    "guide-propose", "reference-approve"):
        from .v2 import cli_commands as _v2c
        _print(_v2c.dispatch(args))
        return 0
    if args.cmd == "benchmark-eval":
        from .v2 import bench_eval as _be
        rep = _be.run_bench_eval(warm_runs=int(args.warm_runs), cold_runs=int(args.cold_runs))
        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(json.dumps(rep, indent=2) + "\n")
        _print(rep)
        return 0
    if args.cmd == "benchmark":
        from .v2.demo import run_benchmark
        rep = run_benchmark()
        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(json.dumps(rep, indent=2) + "\n")
        _print(rep)
        return 0
    if args.cmd == "serve" and getattr(args, "project", None):
        from .v2.api.app import create_app as _create
        import uvicorn as _uv
        _uv.run(_create(args.project), host=args.host, port=args.port)
        return 0
    from .audit import audit, preflight
    if args.cmd == "check":
        anchors = None
        if args.anchors:
            anchors = {int(k): v for k, v in json.loads(Path(args.anchors).read_text()).items()}
        report = audit(args.contract, anchors=anchors)
        if args.report:
            Path(args.report).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        _print({"technical_status": report["technical_status"], "errors": report["errors"],
                "warnings": report["warnings"], "evidence_id": report["evidence_id"],
                "visual_acceptance": report["visual_acceptance"]})
        return 1 if report["errors"] else 0
    if args.cmd == "brief":
        from .brief import compile_brief
        path, brief = compile_brief(args.contract, args.slot, args.out)
        _print({"brief": str(path), "slot": brief["slot"], "inputs": brief["inputs"]})
        return 0
    if args.cmd == "preflight":
        report = preflight(args.contract, args.manifest)
        if args.report:
            Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
        _print({"technical_status": report["technical_status"], "errors": report["errors"]})
        return 1 if report["errors"] else 0
    if args.cmd == "repair-plan":
        from .repair import plan
        _print(plan(args.report, args.out)); return 0
    if args.cmd == "repair-evaluate":
        from .repair import evaluate
        decision = evaluate(args.contract, args.manifest, args.out)
        _print(decision); return 0 if decision["selected_for_review"] else 1
    if args.cmd == "record-failure":
        report = audit(args.contract)
        case = {"schema": 1, "character": report["character"], "slot": args.slot, "code": args.code,
                "symptom": args.symptom, "expected": args.expected,
                "evidence_id": report["evidence_id"], "status": "fixture-needed",
                "visual_approval_granted": False}
        Path(args.out).write_text(json.dumps(case, indent=2) + "\n")
        _print(case); return 0
    if args.cmd == "export-dataset":
        from .dataset import export_dataset
        _print(export_dataset(args.contract, args.out)); return 0
    if args.cmd == "serve":
        from .review import serve
        serve(args.contract, port=args.port, db_path=args.db); return 0
    if args.cmd == "mcp":
        from .mcp_server import serve_stdio
        serve_stdio(); return 0
    if args.cmd == "demo":
        return _demo(args.out, replace=getattr(args, "replace", False))
    return 2


def _demo(out_dir, replace=False):
    from .demo import build_demo, FAULTS
    from .audit import audit
    from .repair import plan, evaluate
    from .dataset import export_dataset
    out, clean, faulty = build_demo(out_dir, replace=replace)
    contract = str(out / "contract.json")
    t0 = time.perf_counter()
    clean_report = audit(contract, frame_files=clean)
    ms = (time.perf_counter() - t0) * 1000 / max(1, len(clean))
    bad = audit(contract)
    plan_path = out / "repair-plan.json"
    plan(contract_report_path(out, bad), plan_path)
    candidates = {"candidates": [{"slot": f["slot"], "file": clean[f["slot"]]} for f in FAULTS]}
    manifest = out / "repair-candidates.json"
    manifest.write_text(json.dumps(candidates, indent=2) + "\n")
    decision = evaluate(contract, manifest, out / "repair-decision.json")
    dataset = export_dataset(contract, out / "dataset")
    summary = {
        "project": str(out),
        "clean_technical_status": clean_report["technical_status"],
        "faulty_technical_status": bad["technical_status"],
        "faulty_error_codes": sorted({e["code"] for e in bad["errors"]}),
        "expected_fault_codes": sorted({f["code"] for f in FAULTS}),
        "repair_selected_for_review": decision["selected_for_review"],
        "check_ms_per_frame": round(ms, 3),
        "dataset": dataset,
        "visual_acceptance": "open",
        "next": f"framebound serve --contract {contract} --port 8765",
    }
    _print(summary)
    ok = (clean_report["technical_status"] == "pass" and bad["technical_status"] == "fail"
          and {f["code"] for f in FAULTS} <= {e["code"] for e in bad["errors"]}
          and decision["selected_for_review"])
    return 0 if ok else 1


def contract_report_path(out, report):
    path = Path(out) / "faulty-report.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    return str(path)


if __name__ == "__main__":
    sys.exit(main())
