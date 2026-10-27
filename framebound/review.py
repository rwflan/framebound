"""Persistent review desk (standard-library HTTP server, SQLite).

The reviewer is human; the consumer of corrections is the model.
Reviewers watch playback, step frames, inspect metrics, mark issues,
and approve or reject. Open issues are exposed as machine-readable
correction tasks. Approval is recorded here and nowhere else: a
technical pass in a report never approves art.
"""
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from .audit import audit, load_contract

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Framebound review</title><style>
body{font-family:system-ui,sans-serif;margin:20px;background:#111;color:#eee}
button,input,select,textarea{background:#222;color:#eee;border:1px solid #555;padding:6px}
img{background:repeating-conic-gradient(#333 0 25%,#2a2a2a 0 50%) 0 0/16px 16px;image-rendering:pixelated}
.frame{cursor:pointer;border:2px solid transparent}.sel{border-color:#ffb020}
.err{color:#ff7a6b}.ok{color:#8be28b}table{border-collapse:collapse}td,th{border:1px solid #444;padding:4px 8px;text-align:left}
</style></head><body>
<h1>Framebound review</h1>
<p id="status"></p>
<div><img id="stage" width="288" height="288" alt="current frame">
<div><button id="play">Pause</button><button id="prev">Prev</button><button id="next">Next</button>
<label>FPS <input id="fps" type="number" value="12" min="1" max="60" style="width:60px"></label>
<span id="slotlabel"></span></div></div>
<h2>Frames</h2><div id="strip"></div>
<h2>Frame metrics</h2><div id="metrics"></div>
<h2>Mark an issue</h2>
<form id="issueform"><label>Category <select id="category"></select></label>
<label>Note <input id="note" size="40"></label><button>Send to model</button></form>
<h2>Decision for selected frame</h2>
<div><button data-dec="approved">Approve</button><button data-dec="rejected">Reject</button><button data-dec="needs-work">Needs work</button></div>
<h2>Open corrections (model queue)</h2><pre id="queue"></pre>
<button id="export">Export training dataset</button><pre id="exportout"></pre>
<script>
let P=null,cur=0,timer=null;
const $=id=>document.getElementById(id);
async function load(){P=await(await fetch('/api/project')).json();
 $('status').textContent=P.contract.character+' / '+P.contract.clip+' - technical: '+P.report.technical_status+' - visual acceptance: '+P.report.visual_acceptance+' (never automatic)';
 $('category').innerHTML=P.categories.map(c=>'<option>'+c+'</option>').join('');
 $('strip').innerHTML=P.frames.map((f,i)=>'<img class="frame" data-i="'+i+'" src="/frames/'+i+'" width="72" height="72" title="frame '+i+'">').join('');
 document.querySelectorAll('.frame').forEach(el=>el.onclick=()=>select(+el.dataset.i));
 const q=await(await fetch('/api/corrections')).json();
 $('queue').textContent=JSON.stringify(q,null,1);select(0);play();}
function select(i){cur=i;$('stage').src='/frames/'+i;$('slotlabel').textContent='Frame '+i;
 document.querySelectorAll('.frame').forEach((el,j)=>el.classList.toggle('sel',j===i));
 const m=(P.report.metrics.frames||[])[i]||{};const errs=P.report.errors.filter(e=>e.slot===i);
 $('metrics').innerHTML='<table><tr><th>Metric</th><th>Value</th></tr>'+Object.entries(m).map(([k,v])=>'<tr><td>'+k+'</td><td>'+(typeof v==='object'?JSON.stringify(v):v)+'</td></tr>').join('')+'</table>'+(errs.length?errs.map(e=>'<p class="err">'+e.code+': '+e.detail+'</p>').join(''):'<p class="ok">No errors on this frame</p>');}
function tick(){const holds=P.contract.holds;select((cur+1)%P.frames.length);
 clearTimeout(timer);timer=setTimeout(tick,1000/Math.max(1,+$('fps').value)*(holds[cur]/3));}
function play(){clearTimeout(timer);timer=setTimeout(tick,200);$('play').textContent='Pause';}
$('play').onclick=()=>{if(timer){clearTimeout(timer);timer=null;$('play').textContent='Play';}else play();};
$('prev').onclick=()=>select((cur-1+P.frames.length)%P.frames.length);
$('next').onclick=()=>select((cur+1)%P.frames.length);
$('issueform').onsubmit=async e=>{e.preventDefault();
 await fetch('/api/issues',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slot:cur,category:$('category').value,note:$('note').value})});load();};
document.querySelectorAll('[data-dec]').forEach(b=>b.onclick=async()=>{
 await fetch('/api/decisions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({slot:cur,decision:b.dataset.dec,note:''})});load();});
$('export').onclick=async()=>{const r=await(await fetch('/api/export',{method:'POST'})).json();$('exportout').textContent=JSON.stringify(r,null,1);};
load();
</script></body></html>"""


def _db(path):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS issues(id INTEGER PRIMARY KEY, slot INT, category TEXT, note TEXT, status TEXT DEFAULT 'open', created TEXT DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY, slot INT, decision TEXT, note TEXT, created TEXT DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()
    return conn


def serve(contract_path, host="127.0.0.1", port=8765, db_path=None):
    contract_path = Path(contract_path).resolve()
    base = contract_path.parent
    contract = load_contract(contract_path)
    db = _db(db_path or str(base / "review.db"))
    knowledge = json.loads((Path(__file__).parent / "knowledge.json").read_text(encoding="utf-8"))
    categories = [r["check"] or r["id"] for r in knowledge["rules"]]

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _body(self):
            return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/":
                return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
            if url.path.startswith("/frames/"):
                i = int(url.path.split("/")[2])
                return self._send(200, (base / contract["frames"][i]).read_bytes(), "image/png")
            if url.path == "/api/project":
                return self._send(200, {"contract": contract, "report": audit(contract_path),
                                        "frames": contract["frames"], "categories": categories})
            if url.path == "/api/corrections":
                rows = db.execute("SELECT id,slot,category,note,status FROM issues WHERE status='open' ORDER BY id").fetchall()
                tasks = [{"task_id": r[0], "slot": r[1], "code": r[2], "note": r[3],
                          "instruction": f"Fix frame {r[1]}: {r[2]}. Regenerate under its brief, then run candidate preflight.",
                          "requires_preflight": True, "automatic_art_approval": False} for r in rows]
                return self._send(200, {"tasks": tasks})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            url = urlparse(self.path)
            if url.path == "/api/issues":
                b = self._body()
                cur = db.execute("INSERT INTO issues(slot,category,note) VALUES(?,?,?)",
                                 (b["slot"], b["category"], b.get("note", "")))
                db.commit()
                return self._send(201, {"task_id": cur.lastrowid, "status": "open"})
            if url.path == "/api/decisions":
                b = self._body()
                db.execute("INSERT INTO decisions(slot,decision,note) VALUES(?,?,?)",
                           (b["slot"], b["decision"], b.get("note", "")))
                db.execute("UPDATE issues SET status='decided' WHERE slot=?", (b["slot"],))
                db.commit()
                return self._send(201, {"recorded": True, "slot": b["slot"], "decision": b["decision"]})
            if url.path == "/api/export":
                from .dataset import export_dataset
                rows = db.execute("SELECT slot,decision,note FROM decisions ORDER BY id").fetchall()
                decisions = {r[0]: {"decision": r[1], "note": r[2]} for r in rows}
                return self._send(200, export_dataset(contract_path, base / "dataset-export", decisions))
            return self._send(404, {"error": "not found"})

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Framebound review: http://{host}:{port}  project={contract_path}")
    server.serve_forever()
