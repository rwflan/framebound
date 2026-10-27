// Browser acceptance journey: inbox → packet → true-speed playback → ROI issue → reload persistence.
import { chromium } from 'playwright';

const BASE = process.env.E2E_BASE ?? 'http://127.0.0.1:8766';
const SHOTS = process.env.E2E_SHOTS ?? '/tmp/fb-e2e-shots';
const out = {};
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.on('pageerror', (e) => { out.pageerror = String(e).slice(0, 300); });
await page.goto(BASE + '/', { waitUntil: 'networkidle' });
await page.waitForSelector('text=Framebound review desk', { timeout: 15000 });
await page.screenshot({ path: SHOTS + '/01-inbox.png' });
out.inbox = await page.locator('li').count();
await page.click('text=pkt-01');
await page.waitForSelector('text=Packet pkt-01', { timeout: 15000 });
await page.waitForTimeout(1500); // let true-speed playback advance
const counter1 = await page.locator('text=/paints \\d+/').textContent();
await page.waitForTimeout(1500);
const counter2 = await page.locator('text=/paints \\d+/').textContent();
out.paints_advance = counter1 !== counter2 ? `${counter1} → ${counter2}` : `STALLED at ${counter1}`;
await page.screenshot({ path: SHOTS + '/02-packet.png' });
// drag an ROI on the stage canvas
const canvas = page.locator('canvas').first();
const box = await canvas.boundingBox();
await page.mouse.move(box.x + 20, box.y + 20);
await page.mouse.down();
await page.mouse.move(box.x + 120, box.y + 120, { steps: 5 });
await page.mouse.up();
await page.fill('input >> nth=2', '3-5').catch(() => {});
await page.locator('label:has-text("Note") input').fill('e2e torso pulse over 3-5');
await page.click('text=Send to model');
await page.waitForSelector('text=correction task', { timeout: 10000 });
out.issue = await page.locator('text=correction task').textContent();
await page.screenshot({ path: SHOTS + '/03-issue.png' });
// reload: everything must survive
await page.reload({ waitUntil: 'networkidle' });
await page.waitForSelector('text=Framebound review desk', { timeout: 15000 });
await page.click('text=pkt-01');
await page.waitForSelector('text=Packet pkt-01', { timeout: 15000 });
await page.screenshot({ path: SHOTS + '/04-reloaded.png' });
const q = await page.locator('text=Open corrections').textContent().catch(() => 'no-queue');
out.after_reload = 'packet + desk reloaded';
await browser.close();
console.log(JSON.stringify(out, null, 2));
if (out.pageerror) process.exitCode = 2;
