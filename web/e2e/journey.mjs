// Browser acceptance journey: real API + real browser, separate OS processes.
// Every check below is a throwing assertion on served pixels, stored geometry,
// persisted bytes, or exact events. Screenshots are debug output, not proof.
import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const PY = process.env.PYTHON ?? 'python';
const PORT = process.env.E2E_PORT ?? '8767';
const BASE = `http://127.0.0.1:${PORT}`;
const SHOTS = process.env.E2E_SHOTS ?? path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'fb-e2e-shots-')));
const WORK = process.env.E2E_WORK ?? fs.mkdtempSync(path.join(os.tmpdir(), 'fb-e2e-work-'));
fs.mkdirSync(SHOTS, { recursive: true });
fs.mkdirSync(WORK, { recursive: true });
const PROJ = path.join(WORK, 'proj');
const GUARD = path.join(WORK,'egress-guard');
const EGRESS_LOG = path.join(WORK,'egress-attempts.jsonl');
fs.mkdirSync(GUARD,{recursive:true});
fs.writeFileSync(path.join(GUARD,'sitecustomize.py'),`
import socket,os,json,sys
sys._framebound_egress_guard_active=True
local={'127.0.0.1','localhost','::1','0.0.0.0','::',None}
def deny(operation,host):
 with open(os.environ['FRAMEBOUND_EGRESS_LOG'],'a') as log:log.write(json.dumps({'operation':operation,'host':str(host)})+'\\n')
 raise AssertionError('offline acceptance attempted external network access')
original_connect=socket.socket.connect
original_lookup=socket.getaddrinfo
def connect(self,address):
 if self.family in (socket.AF_INET,socket.AF_INET6) and address[0] not in local:deny('connect',address[0])
 return original_connect(self,address)
def lookup(host,*args,**kwargs):
 if host not in local:deny('getaddrinfo',host)
 return original_lookup(host,*args,**kwargs)
socket.socket.connect=connect
socket.getaddrinfo=lookup
`);
const PYENV={...process.env,PYTHONPATH:[GUARD,ROOT,process.env.PYTHONPATH||''].filter(Boolean).join(path.delimiter),
  FRAMEBOUND_EGRESS_LOG:EGRESS_LOG,HF_HUB_OFFLINE:'1',HF_DATASETS_OFFLINE:'1'};

const out = {};
let step = 'init';

function assert(cond, msg) {
  if (!cond) throw new Error(`E2E FAIL [${step}]: ${msg}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const OPERATOR_SECRET = process.env.FRAMEBOUND_OPERATOR_SECRET ?? 'e2e-operator-secret';
async function api(p, { method = 'GET', body = null, token = null, actor = null, operator = false } = {}) {
  // Synchronous Python checkpoints can outlast the server's idle timeout.
  // Give each Node probe a fresh socket; browser requests still use normal pooling.
  const headers = { Connection: 'close' };
  if (body) headers['Content-Type'] = 'application/json';
  if (token) headers['X-Session-Token'] = token;
  else if (actor) headers['X-Actor-Id'] = actor;
  if (operator) headers['X-Operator-Secret'] = OPERATOR_SECRET;
  const r = await fetch(BASE + p, { method, headers, body: body ? JSON.stringify(body) : null });
  const text = await r.text();
  let json = null;
  try { json = JSON.parse(text); } catch { /* non-JSON (media) */ }
  return { status: r.status, text, json };
}

function runPy(args, opts = {}) {
  const r = spawnSync(PY, args, { cwd: ROOT, encoding: 'utf8', env: PYENV, ...opts });
  if (r.status !== 0) throw new Error(`E2E FAIL [${step}]: python ${args.join(' ')} exited ${r.status}: ${(r.stderr || '').slice(-800)}`);
  return r.stdout;
}

async function waitHealth(proc) {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(BASE + '/api/health',{headers:{Connection:'close'}});
      if (r.ok) { await r.text();return; }
    } catch { /* not up yet */ }
    if (proc.exitCode !== null) throw new Error(`E2E FAIL [${step}]: API exited early with ${proc.exitCode}`);
    await sleep(500);
  }
  throw new Error(`E2E FAIL [${step}]: API never became healthy`);
}

function startApi() {
  const proc = spawn(PY, ['-m', 'framebound', 'serve', '--project', PROJ, '--port', PORT],
    { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...PYENV, FRAMEBOUND_OPERATOR_SECRET: OPERATOR_SECRET } });
  proc.stdout.on('data',chunk => fs.appendFileSync(path.join(WORK,'server.log'),chunk));
  proc.stderr.on('data',chunk => fs.appendFileSync(path.join(WORK,'server.log'),chunk));
  return proc;
}

async function stopApi(proc, signal = 'SIGKILL') {
  if (proc.exitCode !== null) return;
  proc.kill(signal);
  for (let i = 0; i < 40 && proc.exitCode === null; i++) await sleep(250);
}

async function main() {
  let apiProc = null;
  let browser = null;
  try {
    step = 'setup-project';
    const info = JSON.parse(runPy(['web/e2e/setup.py', PROJ]));
    assert(info.phase==='references_pending' && info.guard_active,'public MCP bootstrap/egress guard missing');
    out.public_mcp_tools=info.mcp_tool_count;

    step = 'start-api';
    apiProc = startApi();
    await waitHealth(apiProc);

    let TOKEN = '';

    step = 'launch-browser';
    browser = await chromium.launch();
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => { out.pageerror = String(e).slice(0, 300); });

    step='approve-references-in-browser';
    await page.goto(BASE+'/#/references',{waitUntil:'networkidle'});
    for (const character of info.characters) {
      const proposal=page.locator('article').filter({has:page.getByRole('heading',{name:new RegExp(character)})});
      await proposal.getByRole('button',{name:'Approve these references'}).click();
      await proposal.getByRole('button',{name:'References approved'}).waitFor();
    }
    const reviewCookie = (await ctx.cookies(BASE + '/api')).find(c => c.name === 'fb_desk_review');
    assert(reviewCookie?.httpOnly && reviewCookie.sameSite === 'Strict', 'browser did not receive its automatic review cookie');
    TOKEN = reviewCookie.value;
    await page.screenshot({path:path.join(SHOTS,'references.png')});
    step='public-automatic-work-and-worker-restart';
    const automatic=JSON.parse(runPy(['web/e2e/setup.py',PROJ,'automatic']));
    const REVIEW_REV=automatic.review_revision;
    const REVIEW_FRAME0=automatic.review_frame0_asset;
    out.automatic_runs=automatic.automatic_runs;
    out.worker_crash_exit=automatic.worker_crash_exit;

    step = 'open-packet';
    await page.goto(BASE + '/#/packet/pkt-diff', { waitUntil: 'networkidle' });
    await page.waitForSelector('#packet-title', { timeout: 15000 });
    const title = await page.locator('#packet-title').textContent();
    assert(title.includes(REVIEW_REV), `revision title wrong: ${title}`);
    assert(await page.locator('#packet-title').getAttribute('data-packet-id') === 'pkt-diff', 'view bound to wrong packet');

    step = 'film-camera-and-inline-evidence';
    assert(await page.locator('.reel-lane').count() === 2, 'comparison lanes missing');
    assert(await page.locator('.frame-evidence').count() === 8, 'per-frame evidence bands missing');
    await page.getByRole('button', {name:'Zoom in',exact:true}).click();
    await page.getByRole('button', {name:'Zoom 125%. Reset to 100%.',exact:true}).waitFor();
    const viewed = (await api('/api/packet/pkt-diff')).json;
    await page.getByRole('button', {name:'Request correction',exact:true}).click();
    await page.getByRole('dialog').getByLabel('Note', {exact:true}).fill('Unsaved review draft');
    const changed = await api('/api/decisions', {method:'POST', token:TOKEN, body:{action:'needs_changes', clip_revision_id:REVIEW_REV, packet_id:'pkt-diff', expected_revision_id:REVIEW_REV, expected_evaluation_id:viewed.evaluation.id, note:'External test action'}});
    assert(changed.status===201, 'external review action failed');
    await page.waitForFunction(() => document.querySelector('.sequence-status')?.textContent.includes('needs changes'), null, {timeout:10000});
    const draftDialogs = await page.locator('dialog').evaluateAll(nodes => nodes.map(node => ({open:node.open, textarea:node.querySelector('textarea')?.value, title:node.querySelector('h2')?.textContent})));
    assert(draftDialogs.some(d => d.open && d.textarea === 'Unsaved review draft'), 'automatic update discarded review draft: ' + JSON.stringify(draftDialogs));
    await page.getByRole('dialog').getByRole('button',{name:'Close review',exact:true}).click();
    assert(await page.locator('.zoom-value').textContent() === '125%', 'automatic update reset camera zoom');

    await page.getByRole('button', {name:'Fit',exact:true}).click();
    await page.waitForFunction(() => {
      const camera = document.querySelector('.reel-camera'), track = document.querySelector('.reel-track');
      return track && camera && track.getBoundingClientRect().width <= camera.clientWidth - 47;
    });
    await page.locator('.zoom-value').click();
    await page.getByRole('button', {name:'Zoom 100%. Reset to 100%.',exact:true}).waitFor();

    step = 'assert-frame-media';
    await page.getByRole('button', { name: 'Play', exact: true }).click();
    await page.keyboard.press('Home'); // Home also pauses via the desk shortcut
    const frameImg = page.locator('#frame-img');
    await frameImg.waitFor({ timeout: 15000 });
    const natural = await frameImg.evaluate((el) => ({ w: el.naturalWidth, h: el.naturalHeight, src: el.currentSrc }));
    assert(natural.w === 64 && natural.h === 64, `frame media is not the 64x64 asset: ${JSON.stringify(natural)}`);
    assert(natural.src.includes(REVIEW_FRAME0), `frame 0 is the wrong asset: ${natural.src}`);
    const tickText = async () => page.locator('#tick-readout').textContent();
    const parseTick = (s) => { const m = /tick (\d+) \/ (\d+)/.exec(s || ''); assert(m, `unparseable tick readout: ${s}`); return [parseInt(m[1], 10), parseInt(m[2], 10)]; };
    {
      const [t0, total] = parseTick(await tickText());
      assert(total === 32, `expected 32 authored ticks, got ${total}`);
      assert(t0 >= 0 && t0 < 32, `tick out of range: ${t0}`);
    }

    step = 'pause-step-resume';
    const toggle = page.getByRole('dialog').getByRole('button', { name: /^(Play|Pause)$/ });
    if ((await toggle.getAttribute('aria-label')) === 'Play') await toggle.click(); // ensure running
    await page.getByRole('dialog').getByRole('button', { name: 'Pause', exact:true }).click();
    const [p0] = parseTick(await tickText());
    await sleep(700);
    const [p1] = parseTick(await tickText());
    assert(p1 === p0, `paused clock advanced ${p0} -> ${p1}`);
    await page.getByRole('button', { name: '+1 tick' }).click();
    const [p2] = parseTick(await tickText());
    assert(p2 === p0 + 1 || (p0 === 31 && p2 === 0), `tick step failed ${p0} -> ${p2}`);
    await page.getByRole('dialog').getByRole('button', { name: 'Play', exact:true }).click();
    await sleep(900);
    const [p3] = parseTick(await tickText());
    assert(p3 !== p2, `resumed clock stalled at ${p2}`);

    step = 'speed-preserves-position';
    await page.getByRole('dialog').getByRole('button',{name:'Pause',exact:true}).click();
    const [s0]=parseTick(await tickText());
    await page.locator('label:has-text("Speed") input').fill('2');
    const [s1]=parseTick(await tickText());
    assert(s1===s0,`speed change moved a paused timeline ${s0} -> ${s1}`);
    await page.getByRole('dialog').getByRole('button',{name:'Play',exact:true}).click();

    step = 'compare-real-media-and-diff';
    await page.goto(BASE + `/#/compare?base=rev-base&other=${REVIEW_REV}`, { waitUntil: 'networkidle' });
    await page.waitForSelector('#compare-title', { timeout: 15000 });
    for (const sel of ['#compare-base-img', '#compare-other-img']) {
      await page.locator(sel).waitFor({ timeout: 15000 });
      const n = await page.locator(sel).evaluate((el) => ({ w: el.naturalWidth, src: el.currentSrc }));
      assert(n.w === 64, `${sel} media missing/wrong: ${JSON.stringify(n)}`);
    }
    await page.locator('#compare-slot').fill('3');
    await page.getByLabel('Mode', {exact:true}).selectOption('diff');
    await page.waitForFunction(() => /mean abs diff [\d.]+%/.test(document.querySelector('#diff-readout')?.textContent || ''), null, { timeout: 15000 });
    const diffText = await page.locator('#diff-readout').textContent();
    const dm = /mean abs diff ([\d.]+)%/.exec(diffText || '');
    assert(dm && parseFloat(dm[1]) > 0, `no real pixel difference at slot 3: ${diffText}`);
    out.diff_at_slot3 = dm[1] + '%';
    await page.screenshot({ path: path.join(SHOTS, 'compare.png') });

    step = 'mark-issue';
    await page.goto(BASE + '/#/packet/pkt-diff', { waitUntil: 'networkidle' });
    await page.waitForSelector('#packet-title', { timeout: 15000 });
    await page.getByRole('button', { name: 'Request correction', exact: true }).click();
    const canvas = page.locator('dialog canvas');
    const box = await canvas.boundingBox();
    assert(box, 'stage canvas has no box');
    const x0 = box.x + box.width * 0.2, y0 = box.y + box.height * 0.2;
    const x1 = box.x + box.width * 0.5, y1 = box.y + box.height * 0.5;
    await page.mouse.move(x0, y0);
    await page.mouse.down();
    await page.mouse.move(x1, y1, { steps: 5 });
    await page.mouse.up();
    await page.getByLabel('Frame range', {exact:true}).fill('12-15');
    await page.getByLabel('Note', {exact:true}).fill('test input: bounded visual defect at slot 3');
    await page.getByRole('button', { name: 'Send to model' }).click();
    await page.getByRole('status').filter({hasText:'Correction task recorded.'}).waitFor({ timeout:10000 });
    out.issue = await page.getByRole('status').filter({hasText:'Correction task recorded.'}).textContent();

    step = 'assert-server-geometry';
    const issues = await api(`/api/issues?revision=${REVIEW_REV}`);
    assert(issues.status === 200, `issues failed: ${issues.status}`);
    assert(issues.json.length === 1, `expected 1 issue, got ${issues.json.length}`);
    const iss = issues.json[0];
    const exp = [Math.floor(0.2 * 64), Math.floor(0.2 * 64), Math.ceil(0.5 * 64), Math.ceil(0.5 * 64)];
    for (let i = 0; i < 4; i++) {
      assert(Math.abs(iss.roi[['left', 'top', 'right', 'bottom'][i]] - exp[i]) <= 2,
        `ROI drifted: got ${JSON.stringify(iss.roi)}, want ~${exp}`);
    }
    assert(JSON.stringify(iss.frame_range) === '[12,15]', `range wrong: ${JSON.stringify(iss.frame_range)}`);
    assert(iss.category === 'torso-pulse', `category wrong: ${iss.category}`);
    assert(iss.clip_revision_id === REVIEW_REV, 'issue on wrong revision');
    const TASK = iss.task_id;
    const BASE_EV = iss.baseline_evaluation_id;
    assert(TASK && BASE_EV, 'issue has no task/baseline binding');
    await page.screenshot({ path: path.join(SHOTS, 'issue.png') });

    step = 'restart-api-and-reload';
    const before=await fetch(BASE+`/api/asset/${REVIEW_FRAME0}`,{headers:{Connection:'close'}});
    assert(before.ok,'asset fetch failed before restart');
    const shaBefore=createHash('sha256').update(Buffer.from(await before.arrayBuffer())).digest('hex');
    await stopApi(apiProc);
    apiProc = startApi();
    await waitHealth(apiProc);
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForSelector('#packet-title', { timeout: 15000 });
    const issues2 = await api(`/api/issues?revision=${REVIEW_REV}`);
    assert(issues2.status === 200 && issues2.json.length === 1, 'issue lost across API restart');
    assert(issues2.json[0].event_id === iss.event_id, 'issue identity changed across restart');
    assert((await page.locator('.frame-issue').allTextContents()).some(t => t.includes('torso pulse')), 'persisted correction missing from frame strip');
    const after=await fetch(BASE+`/api/asset/${REVIEW_FRAME0}`,{headers:{Connection:'close'}});
    const shaAfter=createHash('sha256').update(Buffer.from(await after.arrayBuffer())).digest('hex');
    out.asset_sha256_after_restart=shaAfter;
    assert(shaAfter === shaBefore, 'source bytes changed across restart');

    step = 'mask-claim-submit-cli';
    const mask = await api('/api/masks', { method: 'POST', body: { issue_event_id: iss.event_id, mask_asset_id: 'm-e2e-scope', covered_slots: [3] }, token: TOKEN });
    assert(mask.status === 201, `mask approval failed: ${mask.status} ${mask.text.slice(0, 200)}`);
    const taskGet = await api(`/api/corrections/${TASK}`);
    const claimOut = JSON.parse(runPy(['-m', 'framebound', 'correction-claim', '--project', PROJ, '--task-id', TASK,
      '--expected-version', String(taskGet.json.version), '--actor-id', 'e2e-worker']));
    assert(claimOut.claim_token, 'CLI claim returned no token');
    const submitOut = JSON.parse(runPy(['-m', 'framebound', 'correction-submit', '--project', PROJ, '--task-id', TASK,
      '--claim-token', claimOut.claim_token, '--new-id', 'rev-e2e-fix', '--slots', '3=f-e2e-3',
      '--recipe', 'repair:bounded-patch', '--baseline-evaluation', BASE_EV, '--idempotency-key', 'e2e-1',
      '--actor-id', 'e2e-worker', '--expected-version', String(claimOut.version)]));
    assert(submitOut.ok === true, `CLI submit refused: ${JSON.stringify(submitOut).slice(0, 400)}`);
    assert(submitOut.revision_id === 'rev-e2e-fix', 'wrong revision from submit');

    step = 'reject-reapprove-blocked-release-invalid-resolve';
    {
      const eligBlocked = await api('/api/eligibility/rev-e2e-fix');
      assert(eligBlocked.status === 200 && eligBlocked.json.eligible === false,
        `candidate releasable while task open: ${eligBlocked.text.slice(0, 200)}`);
      assert(eligBlocked.json.reasons.join(' ').includes('unresolved'),
        `blocked for the wrong reason: ${eligBlocked.text.slice(0, 200)}`);
      const badResolve = await api(`/api/issues/${iss.event_id}/resolve`, { method: 'POST',
        body: { replacement_revision_id: 'rev-e2e-fix', note: 'no packet' }, token: TOKEN });
      assert(badResolve.status === 422, `packetless resolve not refused: ${badResolve.status} ${badResolve.text.slice(0, 200)}`);
      const rej = await api('/api/decisions', { method: 'POST', body: {
        action: 'reject', clip_revision_id: 'rev-e2e-fix', packet_id: 'pkt-rev-e2e-fix' }, token: TOKEN });
      assert(rej.status === 201, `reject failed: ${rej.status} ${rej.text.slice(0, 200)}`);
      const eligRej = await api('/api/eligibility/rev-e2e-fix');
      assert(eligRej.json.eligible === false, 'rejected candidate shows eligible');
      const reapp = await api('/api/decisions', { method: 'POST', body: {
        action: 'approve', clip_revision_id: 'rev-e2e-fix', packet_id: 'pkt-rev-e2e-fix' }, token: TOKEN });
      assert(reapp.status === 201, `reapprove failed: ${reapp.status} ${reapp.text.slice(0, 200)}`);
      const eligReapp = await api('/api/eligibility/rev-e2e-fix');
      assert(eligReapp.json.eligible === false, 'reapproved-but-unresolved candidate shows eligible');
      assert(eligReapp.json.reasons.join(' ').includes('unresolved'), 'reapproval hid the open task');
    }

    step = 'compare-and-resolve-in-browser';
    await page.goto(BASE + '/#/compare?base=rev-base&other=rev-e2e-fix', { waitUntil: 'networkidle' });
    await page.waitForSelector('#compare-other-img', { timeout: 15000 });
    const pre = await api(`/api/issues?revision=${REVIEW_REV}`);
    assert(pre.json[0].task_status === 'awaiting_comparison', `task not awaiting comparison after CLI submit: ${pre.json[0].task_status}`);
    await page.goto(BASE + `/#/issues?revision=${REVIEW_REV}`, { waitUntil: 'networkidle' });
    await page.waitForSelector('text=rev-e2e-fix', { timeout: 15000 });
    await page.getByRole('button', { name: 'Resolve with this' }).click();
    await page.waitForSelector('text=Resolved', { timeout: 10000 });
    const resolved = await api(`/api/issues?revision=${REVIEW_REV}`);
    assert(resolved.json[0].resolution_event_id, 'no resolution event recorded');
    assert(resolved.json[0].task_status === 'resolved', `task not resolved: ${resolved.json[0].task_status}`);
    const dec = await api('/api/decisions', { method: 'POST', body: {
      action: 'approve', clip_revision_id: 'rev-e2e-fix', packet_id: 'pkt-rev-e2e-fix',
      expected_revision_id: 'rev-e2e-fix' }, token: TOKEN });
    assert(dec.status === 201, `approval failed: ${dec.status} ${dec.text.slice(0, 200)}`);
    const eligFree = await api('/api/eligibility/rev-e2e-fix');
    assert(eligFree.json.eligible === true, `resolved+approved candidate not releasable: ${eligFree.text.slice(0, 300)}`);

    step = 'reopen-path';
    await page.getByRole('button', { name: 'Reopen' }).click();
    await page.waitForSelector('text=Reopened', { timeout: 10000 });
    const queue = await api('/api/corrections?status=all');
    const entry = (queue.json.tasks || []).find((t) => t.id === TASK);
    assert(entry && entry.status === 'reopened', `reopened task not visible: ${JSON.stringify(entry)}`);

    step='reopened-issue-reconfirmed-and-resolved';
    const reaffirm=await api('/api/decisions',{method:'POST',body:{action:'approve',clip_revision_id:'rev-e2e-fix',packet_id:'pkt-rev-e2e-fix',note:'test fixture: reaffirm after reopen'},token:TOKEN});
    assert(reaffirm.status===201,'reaffirmation failed');
    const resolvedAgain=await api(`/api/issues/${iss.event_id}/resolve`,{method:'POST',body:{replacement_revision_id:'rev-e2e-fix',packet_id:'pkt-rev-e2e-fix',note:'test fixture: rechecked comparison'},token:TOKEN});
    assert(resolvedAgain.status===200,'reopened issue did not resolve');
    assert((await api('/api/eligibility/rev-e2e-fix')).json.eligible,'reconfirmed result is ineligible');
    step='simulated-negative-and-unrelated-note';
    const negative=JSON.parse(runPy(['web/e2e/setup.py',PROJ,'negative']));
    const negativeDecision=await api('/api/decisions',{method:'POST',body:{action:'approve',clip_revision_id:negative.negative_revision,packet_id:negative.negative_packet,note:'TEST INPUT ONLY: proves approval cannot erase simulated origin'},token:TOKEN});
    assert(negativeDecision.status===201,'negative fixture review failed');

    step = 'export-through-desk-move-consume';
    await page.goto(BASE + '/#/export', { waitUntil: 'networkidle' });
    await page.locator('label:has-text("Name") input').fill('e2e-exp');
    await page.locator('label:has-text("Revisions") input').fill(`${REVIEW_REV},rev-e2e-fix,${negative.negative_revision}`);
    await page.getByLabel('include procedural positives (labeled research otherwise)').check();
    await page.getByRole('button', { name: 'Build + validate' }).click();
    await page.getByRole('status').filter({hasText:'Export validated'}).waitFor({timeout:120000});
    const moved = path.join(WORK, 'moved-exp');
    fs.renameSync(path.join(PROJ, 'exports', 'e2e-exp'), moved);
    await page.screenshot({path:path.join(SHOTS,'final.png')});
    await stopApi(apiProc);apiProc=null;
    fs.renameSync(path.join(PROJ,'framebound.sqlite3'),path.join(PROJ,'framebound.sqlite3.unavailable'));
    const consume=`import json,sys
from pathlib import Path
from framebound.v2.exports import validate_snapshot
from framebound.v2.exports.dpo_adapter import decoded_batch
snapshot=Path(sys.argv[1]);report=validate_snapshot(str(snapshot));assert report['ok'],report
batch=decoded_batch(snapshot);assert batch['chosen'][0][0].shape==(64,64,4)
metas=[json.loads(line) for line in (snapshot/'hf'/'metadata.jsonl').read_text().splitlines() if line.strip()]
assert sys.argv[2] not in {m['asset_id'] for m in metas}
assert not (snapshot/'closure'/'blobs'/sys.argv[3]).exists()
assert all(sys.argv[4].encode() not in path.read_bytes() for path in snapshot.rglob('*') if path.is_file())
report['decoded_batch_shape']=list(batch['chosen'][0][0].shape);print(json.dumps(report))`;
    const rep=runPy(['-c',consume,moved,negative.negative_asset,negative.private_note_digest,negative.private_note]);
    const parsed = JSON.parse(rep.trim().split('\n').pop()); // pycocotools logs to stdout; JSON is last
    assert(parsed.ok === true, `moved export invalid: ${JSON.stringify(parsed.issues).slice(0, 400)}`);
    out.export_counts = parsed.counts;
    out.decoded_batch_shape=parsed.decoded_batch_shape;
    assert(!fs.existsSync(EGRESS_LOG) || fs.readFileSync(EGRESS_LOG,'utf8').trim()==='','unexpected network attempt during offline acceptance');
    out.external_socket_attempts=0;

    assert(!out.pageerror,`browser error: ${out.pageerror}`);
    step = 'done';
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (apiProc) await stopApi(apiProc).catch(() => {});
  }
}

main().then(
  () => { console.log(JSON.stringify({ result: 'PASS', ...out }, null, 2)); },
  (e) => { console.error(`E2E RESULT: FAIL\n${e.stack || e}`); console.error(JSON.stringify({ result: 'FAIL', at_step: step, ...out }, null, 2)); process.exitCode = 1; },
);
