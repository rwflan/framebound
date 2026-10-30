// Read-only regression checks for a single stable playback surface and pinned inspection.
import { chromium } from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
const base = process.env.WORKSPACE_URL || "http://127.0.0.1:8765";
const shots =
  process.env.WORKSPACE_SHOTS || path.resolve("output/playwright/playback");
fs.mkdirSync(shots, { recursive: true });
const get = async (route) => {
  const r = await fetch(base + route);
  assert(r.ok, route);
  return r.json();
};
const { packets } = await get("/api/packets");
const bundles = await Promise.all(
  packets.map((p) => get("/api/packet/" + encodeURIComponent(p.id))),
);
const bundle =
  bundles.find(
    (b) =>
      b.contract.action.loop &&
      b.frames.length >= 4 &&
      b.evaluation.technical_status === "fail",
  ) || bundles.find((b) => b.contract.action.loop && b.frames.length >= 4);
assert(bundle);
const holds = bundle.frames.map((f) => f.hold_ticks),
  total = holds.reduce((a, b) => a + b, 0);
const slotAt = (tick) => {
  let sum = 0;
  return holds.findIndex((hold) => (sum += hold) > tick);
};
const full = (url) => new URL(url, base).href;
const browser = await chromium.launch();
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(base + "/#/packet/" + encodeURIComponent(bundle.packet.id));
  await page.locator("#packet-title").waitFor();
  await page.locator(".transport-play:enabled").waitFor();
  const inspector = () =>
    page.locator(".frame-inspector").evaluate((node) => ({
      text: node.innerText,
      src: node.querySelector(".selected-stage img")?.src,
    }));
  const transform = () =>
    page.locator(".reel-track").evaluate((node) => node.style.transform);
  const before = await inspector(),
    reel = await transform();
  await page.locator(".transport-play").click();
  await page.locator(".playback-comparison").waitFor({ state: "visible" });
  assert.equal(
    await page.locator(".reel-lane-label strong").first().isVisible(),
    false,
    "Strip labels must not duplicate playback labels",
  );
  const transportText = await page.locator(".review-controls").innerText();
  const samples = new Set();
  const boxes = await page
    .locator(".playback-image")
    .evaluateAll((nodes) =>
      nodes.map((n) => n.getBoundingClientRect().toJSON()),
    );
  for (let i = 0; i < 12; i++) {
    await page.waitForTimeout(70);
    const snapshot = await page
      .locator(".playback-comparison")
      .evaluate((node) => ({
        tick: Number(node.querySelector("input").value),
        candidate: node.querySelector('img[alt="Candidate animation"]').src,
        reference: node.querySelector('img[alt="Reference animation"]').src,
      }));
    const slot = slotAt(snapshot.tick);
    assert(slot >= 0);
    assert.equal(
      snapshot.candidate,
      full(bundle.frames[slot].asset_url),
      "Candidate follows authored holds",
    );
    const reference = bundle.contract.phase_schedule.find(
      (p) => p.slot === slot,
    )?.motion_reference_id;
    assert.equal(
      snapshot.reference,
      full("/api/asset/" + encodeURIComponent(reference)),
      "Reference shares the candidate playhead",
    );
    samples.add(snapshot.candidate);
    assert.equal(
      await page.locator(".review-controls").innerText(),
      transportText,
      "Main transport text stays stable while looping",
    );
    assert.deepEqual(
      await inspector(),
      before,
      "Right-hand image, checks and correction controls stay pinned",
    );
    assert.equal(
      await transform(),
      reel,
      "Playback must not chase frames with the film camera",
    );
  }
  assert(
    samples.size >= 3,
    "Animation actually advances through its source images",
  );
  assert.deepEqual(
    await page
      .locator(".playback-image")
      .evaluateAll((nodes) =>
        nodes.map((n) => n.getBoundingClientRect().toJSON()),
      ),
    boxes,
    "Playback framing stays stationary",
  );
  await page.locator(".transport-play").click();
  const paused = await page
    .locator(".playback-comparison")
    .evaluate((node) => ({
      tick: Number(node.querySelector("input").value),
      src: node.querySelector('img[alt="Candidate animation"]').src,
    }));
  assert.equal(
    (await inspector()).src,
    paused.src,
    "Pausing adopts the stopped frame once",
  );
  await page.waitForTimeout(180);
  assert.equal(
    await page.getByLabel("Playback tick", { exact: true }).inputValue(),
    String(paused.tick),
  );
  await page.screenshot({ path: path.join(shots, "playback-desktop.png") });
  const scrub = page.getByLabel("Playback tick", { exact: true });
  await scrub.focus();
  await scrub.press("Home");
  const target = holds
    .slice(0, Math.min(3, holds.length - 1))
    .reduce((a, b) => a + b, 0);
  for (let i = 0; i < target; i++) await scrub.press("ArrowRight");
  assert.equal(
    (await inspector()).src,
    full(bundle.frames[slotAt(target)].asset_url),
  );
  await page.getByRole("button", { name: "Film strip", exact: true }).click();
  assert.equal(
    await page.locator(".film-stage").getAttribute("data-view-mode"),
    "frames",
  );
  await page.waitForFunction(() => {
    const f = document
        .querySelector(".candidate .reel-frame.is-current .frame-aperture")
        .getBoundingClientRect(),
      c = document.querySelector(".reel-camera").getBoundingClientRect();
    return Math.abs((f.left + f.right - c.left - c.right) / 2) < 2;
  });
  // The detailed preview is the only player when open; closing it pauses the clock.
  await page
    .getByRole("button", { name: "Open frame preview", exact: true })
    .click();
  const modal = page.getByRole("dialog");
  await modal.getByRole("button", { name: "Play", exact: true }).click();
  const pinned = await inspector(),
    stillReel = await transform();
  await page.waitForTimeout(220);
  assert.deepEqual(await inspector(), pinned);
  assert.equal(await transform(), stillReel);
  assert.equal(await page.locator(".playback-comparison").count(), 0);
  await modal
    .getByRole("button", { name: "Close review", exact: true })
    .click();
  assert.equal(
    await page.getByRole("button", { name: "Pause", exact: true }).count(),
    0,
  );
  // Region editing has a static frame, without a second playback transport in the form.
  await page
    .getByRole("button", { name: "Request correction", exact: true })
    .click();
  assert.equal(
    await page
      .getByRole("dialog")
      .getByRole("button", { name: /^(Play|Pause)$/ })
      .count(),
    0,
  );
  const canvas = page.locator("dialog canvas"),
    image = await canvas.evaluate((node) => node.toDataURL());
  await page.waitForTimeout(180);
  assert.equal(await canvas.evaluate((node) => node.toDataURL()), image);
  await page.getByRole("button", { name: "Close review", exact: true }).click();
  const oneShot = bundles.find(
    (b) => !b.contract.action.loop && b.frames.length > 1,
  );
  if (oneShot) {
    await page.goto(
      base + "/#/packet/" + encodeURIComponent(oneShot.packet.id),
    );
    await page.locator("#packet-title").waitFor();
    await page.locator(".transport-play:enabled").click();
    await page.waitForFunction(
      () =>
        document
          .querySelector(".transport-play")
          ?.getAttribute("aria-label") === "Play",
      null,
      { timeout: 4000 },
    );
    assert.equal(
      await page.locator(".selected-stage img").getAttribute("src"),
      oneShot.frames.at(-1).asset_url,
    );
    assert.match(
      await page.locator(".inspector-heading").innerText(),
      new RegExp(`Frame ${String(oneShot.frames.length).padStart(2, "0")}`),
    );
  }
  // Player panes preserve their size and don't spill into the transport at narrower widths.
  for (const width of [940, 768, 560, 390]) {
    await page.setViewportSize({ width, height: 900 });
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
    );
    const panels = await page
      .locator(".playback-lane")
      .evaluateAll((nodes) =>
        nodes.map((n) => n.getBoundingClientRect().toJSON()),
      );
    assert.equal(panels.length, 2);
    assert(panels.every((p) => p.width > 60 && p.height > 60));
    assert(
      Math.min(panels[0].right, panels[1].right) -
        Math.max(panels[0].left, panels[1].left) <=
        1 ||
        Math.min(panels[0].bottom, panels[1].bottom) -
          Math.max(panels[0].top, panels[1].top) <=
          1,
    );
    await page.screenshot({ path: path.join(shots, `playback-${width}.png`) });
  }
  assert.deepEqual(
    (await get("/api/packet/" + encodeURIComponent(bundle.packet.id))).contract
      .timing,
    bundle.contract.timing,
  );
  assert.deepEqual(errors, []);
  console.log(
    "Playback workspace passed: fixed comparison, synchronized holds, pinned inspector/camera, pause/scrub inspection, one animated surface, locked corrections, one-shot completion and responsive panes.",
  );
} finally {
  await browser.close();
}
