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
const out = {};
let step = 'init';

function assert(cond, msg) {
  if (!cond) throw new Error(`E2E FAIL [${step}]: ${msg}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const OPERATOR_SECRET = process.env.FRAMEBOUND_OPERATOR_SECRET ?? 'e2e-operator-secret';
async function api(p, { method = 'GET', body = null, token = null, actor = null, operator = false } = {}) {
  const headers = {};
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
  const r = spawnSync(PY, args, { cwd: ROOT, encoding: 'utf8', ...opts });
  if (r.status !== 0) throw new Error(`E2E FAIL [${step}]: python ${args.join(' ')} exited ${r.status}: ${(r.stderr || '').slice(-800)}`);
  return r.stdout;
}

async function waitHealth(proc) {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(BASE + '/api/health');
      if (r.ok) return;
    } catch { /* not up yet */ }
    if (proc.exitCode !== null) throw new Error(`E2E FAIL [${step}]: API exited early with ${proc.exitCode}`);
    await sleep(500);
  }
  throw new Error(`E2E FAIL [${step}]: API never became healthy`);
}

function startApi() {
  const proc = spawn(PY, ['-m', 'framebound', 'serve', '--project', PROJ, '--port', PORT],
    { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, FRAMEBOUND_OPERATOR_SECRET: OPERATOR_SECRET } });
  proc.stdout.on('data', () => {});
  proc.stderr.on('data', () => {});
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
    assert(info.packet_id === 'pkt-base', 'setup did not build pkt-base');

    step = 'start-api';
    apiProc = startApi();
    await waitHealth(apiProc);

    step = 'reviewer-ceremony';
    const pair = await api('/api/reviewer/pair', { method: 'POST', body: { reviewer_id: 'e2e-human' }, operator: true });
    assert(pair.status === 201, `pair failed: ${pair.status} ${pair.text.slice(0, 200)}`);
    const open = await api('/api/reviewer/open', { method: 'POST', body: { pairing_code: pair.json.pairing_code } });
    assert(open.status === 201, `open failed: ${open.status}`);
    const TOKEN = open.json.session_token;
    assert(TOKEN && TOKEN.length > 8, 'no session token minted');

    step = 'launch-browser';
    browser = await chromium.launch();
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    await ctx.addInitScript((t) => {
      window.localStorage.setItem('fb.reviewer_token', t);
      window.localStorage.setItem('fb.reviewer_id', 'e2e-human');
    }, TOKEN);
    const page = await ctx.newPage();
    page.on('pageerror', (e) => { out.pageerror = String(e).slice(0, 300); });

    step = 'open-packet';
    await page.goto(BASE + '/#/packet/pkt-diff', { waitUntil: 'networkidle' });
    await page.waitForSelector('#packet-title', { timeout: 15000 });
    const title = await page.locator('#packet-title').textContent();
    assert(title.includes('pkt-diff'), `packet title wrong: ${title}`);

    step = 'assert-frame-media';
    await page.keyboard.press('Home'); // Home also pauses via the desk shortcut
    const frameImg = page.locator('#frame-img');
    await frameImg.waitFor({ timeout: 15000 });
    const natural = await frameImg.evaluate((el) => ({ w: el.naturalWidth, h: el.naturalHeight, src: el.currentSrc }));
    assert(natural.w === 64 && natural.h === 64, `frame media is not the 64x64 asset: ${JSON.stringify(natural)}`);
    assert(natural.src.includes('f-e2e-0'), `frame 0 is the wrong asset: ${natural.src}`);
    const tickText = async () => page.locator('#tick-readout').textContent();
    const parseTick = (s) => { const m = /tick (\d+) \/ (\d+)/.exec(s || ''); assert(m, `unparseable tick readout: ${s}`); return [parseInt(m[1], 10), parseInt(m[2], 10)]; };
    {
      const [t0, total] = parseTick(await tickText());
      assert(total === 32, `expected 32 authored ticks, got ${total}`);
      assert(t0 >= 0 && t0 < 32, `tick out of range: ${t0}`);
    }

    step = 'pause-step-resume';
    const toggle = page.getByRole('button', { name: /^(Play|Pause)$/ });
    if ((await toggle.textContent()) === 'Play') await toggle.click(); // ensure running
    await page.getByRole('button', { name: 'Pause' }).click();
    const [p0] = parseTick(await tickText());
    await sleep(700);
    const [p1] = parseTick(await tickText());
    assert(p1 === p0, `paused clock advanced ${p0} -> ${p1}`);
    await page.getByRole('button', { name: '+1 tick' }).click();
    const [p2] = parseTick(await tickText());
    assert(p2 === p0 + 1 || (p0 === 31 && p2 === 0), `tick step failed ${p0} -> ${p2}`);
    await page.getByRole('button', { name: 'Play' }).click();
    await sleep(900);
    const [p3] = parseTick(await tickText());
    assert(p3 !== p2, `resumed clock stalled at ${p2}`);

    step = 'speed-preserves-position';
    const [s0] = parseTick(await tickText());
    await page.locator('label:has-text("Speed") input').fill('2');
    await sleep(600);
    const [s1] = parseTick(await tickText());
    assert(s1 >= s0, `speed change reset the timeline ${s0} -> ${s1}`);

    step = 'compare-real-media-and-diff';
    await page.goto(BASE + '/#/compare?base=rev-base&other=rev-diff', { waitUntil: 'networkidle' });
    await page.waitForSelector('#compare-title', { timeout: 15000 });
    for (const sel of ['#compare-base-img', '#compare-other-img']) {
      await page.locator(sel).waitFor({ timeout: 15000 });
      const n = await page.locator(sel).evaluate((el) => ({ w: el.naturalWidth, src: el.currentSrc }));
      assert(n.w === 64, `${sel} media missing/wrong: ${JSON.stringify(n)}`);
    }
    await page.locator('#compare-slot').fill('3');
    await page.locator('select').selectOption('diff');
    await page.waitForFunction(() => /mean abs diff [\d.]+%/.test(document.querySelector('#diff-readout')?.textContent || ''), null, { timeout: 15000 });
    const diffText = await page.locator('#diff-readout').textContent();
    const dm = /mean abs diff ([\d.]+)%/.exec(diffText || '');
    assert(dm && parseFloat(dm[1]) > 0, `no real pixel difference at slot 3: ${diffText}`);
    out.diff_at_slot3 = dm[1] + '%';
    await page.screenshot({ path: path.join(SHOTS, 'compare.png') });

    step = 'mark-issue';
    await page.goto(BASE + '/#/packet/pkt-diff', { waitUntil: 'networkidle' });
    await page.waitForSelector('#packet-title', { timeout: 15000 });
    const canvas = page.locator('canvas').first();
    const box = await canvas.boundingBox();
    assert(box, 'stage canvas has no box');
    const x0 = box.x + box.width * 0.2, y0 = box.y + box.height * 0.2;
    const x1 = box.x + box.width * 0.5, y1 = box.y + box.height * 0.5;
    await page.mouse.move(x0, y0);
    await page.mouse.down();
    await page.mouse.move(x1, y1, { steps: 5 });
    await page.mouse.up();
    await page.locator('label:has-text("Frame range") input').fill('12-15');
    await page.locator('label:has-text("Note") input').fill('e2e blank at slot 3');
    await page.getByRole('button', { name: 'Send to model' }).click();
    await page.waitForSelector('text=correction task', { timeout: 10000 });
    out.issue = await page.locator('text=correction task').textContent();

    step = 'assert-server-geometry';
    const issues = await api('/api/issues?revision=rev-diff');
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
    assert(iss.clip_revision_id === 'rev-diff', 'issue on wrong revision');
    const TASK = iss.task_id;
    const BASE_EV = iss.baseline_evaluation_id;
    assert(TASK && BASE_EV, 'issue has no task/baseline binding');
    await page.screenshot({ path: path.join(SHOTS, 'issue.png') });

    step = 'restart-api-and-reload';
    const before = await api('/api/asset/f-e2e-0');
    assert(before.status === 200, 'asset fetch failed before restart');
    const shaBefore = createHash('sha256').update(Buffer.from(before.text, 'binary')).digest('hex');
    await stopApi(apiProc);
    apiProc = startApi();
    await waitHealth(apiProc);
    await page.reload({ waitUntil: 'networkidle' });
    await page.waitForSelector('#packet-title', { timeout: 15000 });
    const issues2 = await api('/api/issues?revision=rev-diff');
    assert(issues2.status === 200 && issues2.json.length === 1, 'issue lost across API restart');
    assert(issues2.json[0].event_id === iss.event_id, 'issue identity changed across restart');
    const after = await api('/api/asset/f-e2e-0');
    const shaAfter = createHash('sha256').update(Buffer.from(after.text, 'binary')).digest('hex');
    assert(shaAfter === shaBefore, 'source bytes changed across restart');

    step = 'mask-claim-submit-cli';
    const mask = await api('/api/masks', { method: 'POST', body: { issue_event_id: iss.event_id, mask_asset_id: 'm-e2e-full', covered_slots: [3] }, token: TOKEN });
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
    const pre = await api('/api/issues?revision=rev-diff');
    assert(pre.json[0].task_status === 'awaiting_comparison', `task not awaiting comparison after CLI submit: ${pre.json[0].task_status}`);
    await page.goto(BASE + '/#/issues?revision=rev-diff', { waitUntil: 'networkidle' });
    await page.waitForSelector('text=rev-e2e-fix', { timeout: 15000 });
    await page.getByRole('button', { name: 'Resolve with this' }).click();
    await page.waitForSelector('text=Resolved', { timeout: 10000 });
    const resolved = await api('/api/issues?revision=rev-diff');
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

    step = 'export-through-desk-move-consume';
    await page.goto(BASE + '/#/export', { waitUntil: 'networkidle' });
    await page.locator('label:has-text("Name") input').fill('e2e-exp');
    await page.locator('label:has-text("Revisions") input').fill('rev-diff,rev-e2e-fix');
    await page.getByRole('button', { name: 'Build + validate' }).click();
    await page.waitForSelector('text="ok": true', { timeout: 120000 });
    const moved = path.join(WORK, 'moved-exp');
    fs.renameSync(path.join(PROJ, 'exports', 'e2e-exp'), moved);
    const rep = runPy(['-c', 'import json,sys; from framebound.v2.exports import validate_snapshot; print(json.dumps(validate_snapshot(sys.argv[1])))', moved]);
    const parsed = JSON.parse(rep.trim().split('\n').pop()); // pycocotools logs to stdout; JSON is last
    assert(parsed.ok === true, `moved export invalid: ${JSON.stringify(parsed.issues).slice(0, 400)}`);
    out.export_counts = parsed.counts;

    step = 'done';
    await page.screenshot({ path: path.join(SHOTS, 'final.png') });
  } finally {
    if (browser) await browser.close().catch(() => {});
    if (apiProc) await stopApi(apiProc).catch(() => {});
  }
}

main().then(
  () => { console.log(JSON.stringify({ result: 'PASS', ...out }, null, 2)); },
  (e) => { console.error(`E2E RESULT: FAIL\n${e.stack || e}`); console.error(JSON.stringify({ result: 'FAIL', at_step: step, ...out }, null, 2)); process.exitCode = 1; },
);
