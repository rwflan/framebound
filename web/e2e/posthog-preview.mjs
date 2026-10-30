/** Standalone preview acceptance checks. Run against a static web/public server. */
import { chromium } from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
const url = process.env.PREVIEW_URL || "http://127.0.0.1:8933/designs/posthog/";
const shots =
  process.env.PREVIEW_SHOTS ||
  path.resolve("output/playwright/posthog-preview");
fs.mkdirSync(shots, { recursive: true });
const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  reducedMotion: "reduce",
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("response", (response) => {
  if (response.status() >= 400)
    errors.push(`${response.status()} ${response.url()}`);
});
try {
  await page.goto(url);
  await page.locator("[data-selected]").evaluate((image) => image.decode());
  assert.match(await page.locator("[data-heading]").innerText(), /Run r02/);
  assert.match(await page.locator("[data-measurements]").innerText(), /41.0%/);
  assert.equal(await page.locator(".candidate-strip .film-unit").count(), 8);
  assert.equal(await page.locator(".film-metric.fail").count(), 1);
  await page.screenshot({ path: path.join(shots, "desktop.png") });
  await page.locator("[data-reference=identity]").click();
  assert.match(
    await page.locator("[data-dialog-title]").innerText(),
    /Identity/,
  );
  await page.keyboard.press("Escape");
  await page.locator("[data-fit]").click();
  assert.match(await page.locator("[data-reset-zoom]").innerText(), /%/);
  assert(
    await page
      .locator("[data-film-scroll]")
      .evaluate((node) => node.scrollWidth <= node.clientWidth + 3),
    "Fit should show every frame",
  );
  const labels = await page.locator(".lane-label").evaluateAll((nodes) =>
    nodes.map((node) => ({
      text: node.textContent,
      box: node.getBoundingClientRect().toJSON(),
    })),
  );
  assert(
    labels[1].box.y > labels[0].box.y + 50,
    "Lane labels stay separated at fit zoom",
  );
  await page.screenshot({ path: path.join(shots, "fit.png") });
  await page.locator("[data-reset-zoom]").click();
  await page.locator("[data-correction]").click();
  await page
    .locator("textarea[name=note]")
    .fill("Restore the torso silhouette.");
  const canvas = page.locator(".correction-canvas");
  const rect = await canvas.boundingBox();
  await page.mouse.move(rect.x + rect.width * 0.3, rect.y + rect.height * 0.25);
  await page.mouse.down();
  await page.mouse.move(
    rect.x + rect.width * 0.65,
    rect.y + rect.height * 0.65,
    { steps: 6 },
  );
  await page.mouse.up();
  await page.locator(".correction-form button[type=submit]").click();
  assert.match(
    await page.locator("[data-corrections]").innerText(),
    /Restore the torso/,
  );
  assert.match(await page.locator("[data-corrections]").innerText(), /12–15/);
  assert.equal(await page.locator(".region-box").count(), 1);
  const stored = await page.evaluate(() =>
    JSON.parse(localStorage.getItem("framebound.posthog-preview.v1")),
  );
  assert(stored.issues[0].roi.width > 0 && stored.issues[0].roi.width <= 96);
  assert.equal(stored.issues[0].frame_instance_id, "pip-run-r02-fi-03");
  await page.reload();
  assert.match(
    await page.locator("[data-corrections]").innerText(),
    /Restore the torso/,
  );
  await page.locator("[data-decision]").click();
  assert.match(await page.locator(".review-facts").innerText(), /Not eligible/);
  await page.locator("[data-verdict=needs_changes]").click();
  assert.equal(
    await page.locator("[data-acceptance]").innerText(),
    "Needs changes",
  );
  await page.locator(".queue [data-revision=pip-jump-r01]").click();
  assert.match(await page.locator("[data-heading]").innerText(), /Jump/);
  assert.match(
    await page.locator("[data-measurements]").innerText(),
    /unmeasured/,
  );
  await page.locator("[data-evidence]").click();
  assert.equal(await page.locator(".check.unmeasured").count(), 1);
  assert.equal(await page.locator(".check.not_applicable").count(), 3);
  assert.equal(
    await page.locator("[data-dialog]").evaluate((node) => node.open),
    false,
  );
  await page.locator("[data-next-review]").click();
  assert.match(await page.locator("[data-heading]").innerText(), /Idle/);
  assert.equal(
    await page.locator(".check.unmeasured").count(),
    0,
    "Evidence follows the newly selected revision",
  );
  await page.locator("[data-close-evidence]").click();
  await page.locator(".queue [data-revision=pip-jump-r01]").click();
  await page.locator("[data-play]").click();
  await page.waitForTimeout(650);
  assert.equal(
    await page.locator("[data-play]").getAttribute("aria-label"),
    "Play animation",
    "Non-looping animation stops",
  );
  assert.match(await page.locator("[data-position]").innerText(), /06 \/ 06/);
  await page.locator("[data-view=timeline]").click();
  assert((await page.locator(".queue-item.event").count()) >= 17);
  await page.locator(".queue [data-revision=pip-run-r03]").first().click();
  assert.match(await page.locator("[data-heading]").innerText(), /Run r03/);
  assert.match(
    await page.locator("[data-states]").innerText(),
    /Technical pass/,
  );
  await page.locator("[data-compare]").selectOption("baseline");
  assert.equal(await page.locator(".reference-label").innerText(), "Previous");
  assert.match(
    await page
      .locator('.reference-strip [data-frame="3"] img')
      .getAttribute("src"),
    /run-wide-torso/,
  );
  await page.locator("[data-play]").click();
  await page.waitForTimeout(140);
  assert.equal(
    await page.locator("[data-play]").getAttribute("aria-label"),
    "Pause animation",
  );
  await page.locator("[data-play]").click();
  await page.locator("[data-film-scroll]").focus();
  await page.keyboard.press("Home");
  await page.keyboard.press("ArrowRight");
  assert.match(await page.locator("[data-frame-heading]").innerText(), /02/);
  // Dragging a frame pans the strip without selecting the frame underneath the release.
  await page.locator("[data-reset-zoom]").click();
  const scroller = await page.locator("[data-film-scroll]").boundingBox();
  const selected = await page.locator("[data-frame-heading]").innerText();
  await page.mouse.move(scroller.x + scroller.width * 0.75, scroller.y + 80);
  await page.mouse.down();
  await page.mouse.move(scroller.x + 80, scroller.y + 80, { steps: 10 });
  await page.mouse.up();
  assert(
    (await page
      .locator("[data-film-scroll]")
      .evaluate((node) => node.scrollLeft)) > 100,
  );
  assert.equal(
    await page.locator("[data-frame-heading]").innerText(),
    selected,
  );
  await page.locator("[data-search]").click();
  await page.locator("[data-command-search]").fill("idle");
  await page.keyboard.press("Enter");
  assert.match(await page.locator("[data-heading]").innerText(), /Idle/);
  await page.locator("[data-expand]").click();
  assert.equal(
    await page
      .locator(".window")
      .evaluate((node) => node.classList.contains("focus-film")),
    true,
  );
  await page.locator("[data-expand]").click();
  await page.keyboard.press("Control+k");
  assert.equal(
    await page.locator("[data-dialog]").evaluate((node) => node.open),
    true,
  );
  await page.keyboard.press("Escape");
  await page.locator("[data-view=interventions]").click();
  await page.locator(".queue [data-revision=pip-run-r02]").click();
  for (const width of [1024, 768, 560, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await page.waitForTimeout(60);
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
      `No page overflow at ${width}`,
    );
    const transport = await page.locator(".transport").boundingBox();
    for (const control of [
      "[data-play]",
      '[data-step="1"]',
      "[data-position]",
      "[data-speed]",
    ]) {
      const bounds = await page.locator(control).boundingBox();
      assert(
        bounds.x >= transport.x &&
          bounds.x + bounds.width <= transport.x + transport.width + 1,
        `${control} fits at ${width}`,
      );
    }
    await page.locator("[data-fit]").click();
    assert(
      await page
        .locator("[data-film-scroll]")
        .evaluate((node) => node.scrollWidth <= node.clientWidth + 3),
      `Fit at ${width}`,
    );
    await page.screenshot({ path: path.join(shots, `width-${width}.png`) });
    await page.locator("[data-reset-zoom]").click();
  }
  assert.deepEqual(errors, []);
  console.log(
    "Preview passed: fixture checks, fit at every viewport, correction region and persistence, human decision, chronological navigation, contextual evidence, frozen references, search, focus mode, authored playback, drag, keyboard and responsive layout.",
  );
} finally {
  await browser.close();
}
