// Read-only acceptance of the live workspace against a running project server.
import { chromium } from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
const base = process.env.WORKSPACE_URL || "http://127.0.0.1:8765";
const shots =
  process.env.WORKSPACE_SHOTS || path.resolve("output/playwright/workspace");
fs.mkdirSync(shots, { recursive: true });
const get = async (route) => {
  const response = await fetch(base + route);
  assert(response.ok, route);
  return response.json();
};
const packets = (await get("/api/packets")).packets;
const bundles = await Promise.all(
  packets.map((packet) => get("/api/packet/" + encodeURIComponent(packet.id))),
);
const failing = bundles.find((b) =>
  b.evaluation.results.some(
    (check) => check.outcome === "fail" && /^slot \d+$/.test(check.scope),
  ),
);
assert(failing, "Requires a project with a scoped failing check");
const issues = await get("/api/issues");
const { attentionSlot } = await import("../test/review-model.bundle.mjs");
const expected = attentionSlot(failing, issues);
const browser = await chromium.launch();
try {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(base + "/#/packet/" + encodeURIComponent(failing.packet.id));
  await page.locator("#packet-title").waitFor();
  await page.waitForFunction(() =>
    Boolean(document.querySelector(".reel-track")?.style.transform),
  );
  const centered = async () =>
    page.waitForFunction(() => {
      const current = document
          .querySelector(".candidate .reel-frame.is-current .frame-aperture")
          ?.getBoundingClientRect(),
        camera = document
          .querySelector(".reel-camera")
          ?.getBoundingClientRect();
      return (
        current &&
        camera &&
        Math.abs(
          (current.left + current.right) / 2 - (camera.left + camera.right) / 2,
        ) < 2
      );
    });
  await centered();
  assert.equal(
    await page
      .locator(".candidate .reel-frame[aria-pressed=true]")
      .getAttribute("aria-label"),
    `Candidate, frame ${expected + 1}`,
  );
  assert.equal(
    await page.locator(".reel-stock .frame-measure").count(),
    0,
    "Measurements must not be inside film stock",
  );
  assert.equal(
    await page.locator(".measurement-cell").count(),
    failing.frames.length,
  );
  assert(
    (await page.locator(".measurement-track .frame-measure.fail").count()) > 0,
  );
  const separated = await page
    .locator(".measurement-track")
    .evaluate(
      (node) =>
        node.getBoundingClientRect().top -
        document.querySelector(".candidate").getBoundingClientRect().bottom,
    );
  assert(
    separated >= 20,
    "Data sheet needs a clear physical gap below the film",
  );
  await page.locator(".selected-stage img").evaluate((image) => image.decode());
  assert(
    await page
      .locator(".film-stage")
      .evaluate((node) => parseFloat(getComputedStyle(node).paddingLeft) === 0),
    "No space reserved for row labels",
  );
  const tabs = await page
    .locator(".reel-lane-label strong")
    .evaluateAll((nodes) =>
      nodes.map((node) => node.getBoundingClientRect().toJSON()),
    );
  assert.equal(tabs.length, 3);
  const viewportLeft = (await page.locator(".reel-camera").boundingBox()).x;
  assert(
    tabs.every((tab) => Math.abs(tab.left - viewportLeft) < 1),
    "Row tabs attach flush to the left container edge",
  );
  const laneTops = await page
    .locator(".reel-lane .frame-aperture")
    .evaluateAll((nodes) => [
      nodes[0].getBoundingClientRect().top,
      nodes[nodes.length / 2].getBoundingClientRect().top,
    ]);
  const sheetTop = (await page.locator(".measurement-track").boundingBox()).y;
  for (const [i, top] of [...laneTops, sheetTop].entries())
    assert(
      tabs[i].top < top + 28 && tabs[i].bottom > top,
      "Row labels overlap the upper frame edge",
    );
  const firstMetric = (
    await page.locator(".measurement-cell .frame-measure").first().boundingBox()
  ).y;
  assert(
    tabs[2].bottom <= firstMetric + 1,
    "Checks legend clears the measurement text",
  );
  await page.screenshot({ path: path.join(shots, "desktop.png") });
  // Open every animation through the actual queue/search, including coverage gaps and clean clips.
  for (const bundle of bundles.filter((b) => b.frames.length)) {
    const wanted = attentionSlot(bundle, issues);
    const actual = page.locator(
      `.review-queue .queue-item[aria-label="${String(bundle.contract.action.name)} ${String(bundle.revision.id)}"]`,
    );
    if (await actual.count()) await actual.click();
    else {
      await page
        .getByRole("button", { name: "Find sequence", exact: true })
        .click();
      await page
        .getByLabel("Search sequences", { exact: true })
        .fill(String(bundle.revision.id));
      await page.getByLabel("Search sequences", { exact: true }).press("Enter");
    }
    await page.waitForFunction(
      (id) =>
        document
          .querySelector("#packet-title")
          ?.getAttribute("data-revision-id") === id,
      String(bundle.revision.id),
    );
    await centered();
    assert.equal(
      await page
        .locator(".candidate .reel-frame[aria-pressed=true]")
        .getAttribute("aria-label"),
      `Candidate, frame ${wanted + 1}`,
      "Each animation opens on its first attention frame",
    );
  }
  await page.goto(base + "/#/packet/" + encodeURIComponent(failing.packet.id));
  await page.locator("#packet-title").waitFor();
  await centered();
  // Center endpoints as well as interior frames, with the camera's authored image geometry intact.
  for (const index of [0, failing.frames.length - 1, expected]) {
    // Off-screen buttons cannot receive pointer events; keyboard Home/End are the actual navigation contract.
    await page.locator(".reel-camera").focus();
    await page.keyboard.press(
      index === 0
        ? "Home"
        : index === failing.frames.length - 1
          ? "End"
          : "Home",
    );
    if (index === expected)
      for (let i = 0; i < expected; i++)
        await page.keyboard.press("ArrowRight");
    await centered();
  }
  await page.locator(".reel-camera").focus();
  await page.keyboard.press("Space");
  assert.equal(
    await page.getByRole("button", { name: "Pause", exact: true }).count(),
    1,
  );
  await page.keyboard.press("Space");
  // Playback may stop on a visible frame away from the camera centre.
  // Explicit frame navigation restores the centering precondition for the checks below.
  await page.locator(".reel-camera").focus();
  await page.keyboard.press("Home");
  await page.locator(".frame-inspector .text-button").click();
  assert.equal(
    await page.locator("dialog[open]").count(),
    0,
    "Evidence must stay contextual",
  );
  assert((await page.locator(".evidence-panel .check-row.fail").count()) > 0);
  await page
    .getByRole("button", { name: "Close evidence", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Find sequence", exact: true })
    .click();
  await page
    .getByLabel("Search sequences", { exact: true })
    .fill(String(failing.revision.id));
  await page.getByLabel("Search sequences", { exact: true }).press("Enter");
  assert.equal(
    await page.locator("#packet-title").getAttribute("data-revision-id"),
    failing.revision.id,
  );
  await centered();
  for (const viewport of [
    { width: 1280, height: 900 },
    { width: 940, height: 1218 },
    { width: 768, height: 1024 },
    { width: 560, height: 900 },
    { width: 390, height: 844 },
    { width: 360, height: 720 },
  ]) {
    await page.setViewportSize(viewport);
    await centered();
    assert(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      ),
      `No page overflow at ${viewport.width}`,
    );
    const boxes = await page.locator(".review-controls").evaluate((node) => {
      const parent = node.getBoundingClientRect();
      return {
        parent: parent.toJSON(),
        children: [...node.querySelectorAll("button,select")].map((child) =>
          child.getBoundingClientRect().toJSON(),
        ),
      };
    });
    for (const box of boxes.children)
      assert(
        box.left >= boxes.parent.left &&
          box.right <= boxes.parent.right + 1 &&
          box.top >= boxes.parent.top &&
          box.bottom <= boxes.parent.bottom + 1,
        `Controls inside transport at ${viewport.width}`,
      );
    for (let i = 0; i < boxes.children.length; i++)
      for (let j = i + 1; j < boxes.children.length; j++) {
        const a = boxes.children[i],
          b = boxes.children[j];
        assert(
          Math.min(a.right, b.right) - Math.max(a.left, b.left) <= 1 ||
            Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) <= 1,
          `Controls do not overlap at ${viewport.width}`,
        );
      }
    await page.getByRole("button", { name: "Fit", exact: true }).click();
    await page.waitForFunction(() => {
      const c = document.querySelector(".reel-camera"),
        t = document.querySelector(".reel-track");
      return t.getBoundingClientRect().width <= c.clientWidth - 47;
    });
    await page.screenshot({
      path: path.join(shots, `width-${viewport.width}.png`),
    });
    await page.locator(".zoom-value").click();
  }
  assert.deepEqual(errors, []);
  console.log(
    "Workspace passed: first attention selected and centered, endpoints centered, measurements separate from film, contextual evidence, real search, zoom fit and responsive controls.",
  );
} finally {
  await browser.close();
}
