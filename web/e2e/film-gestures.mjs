// Read-only checks of real pointer/wheel overscroll and the animated return to padded edges.
import { chromium } from "playwright";
import assert from "node:assert/strict";
const base = process.env.WORKSPACE_URL || "http://127.0.0.1:8765";
const response = await fetch(base + "/api/packets");
assert(response.ok);
const { packets } = await response.json();
assert(packets.length);
const browser = await chromium.launch();
try {
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "no-preference",
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(base + "/#/packet/" + encodeURIComponent(packets[0].id));
  await page.locator(".reel-camera").waitFor();
  const geometry = () =>
    page.locator(".reel-camera").evaluate((node) => {
      const track = node.querySelector(".reel-track"),
        m = new DOMMatrix(getComputedStyle(track).transform),
        width = track.offsetWidth * m.a;
      return {
        x: m.m41,
        zoom: m.a,
        min:
          width <= node.clientWidth - 48
            ? (node.clientWidth - width) / 2
            : node.clientWidth - width - 24,
        max:
          width <= node.clientWidth - 48 ? (node.clientWidth - width) / 2 : 24,
      };
    });
  const settled = async (end) =>
    page.waitForFunction(
      (end) => {
        const node = document.querySelector(".reel-camera"),
          track = node.querySelector(".reel-track"),
          m = new DOMMatrix(getComputedStyle(track).transform),
          width = track.offsetWidth * m.a;
        const target =
          width <= node.clientWidth - 48
            ? (node.clientWidth - width) / 2
            : end === "start"
              ? 24
              : node.clientWidth - width - 24;
        return Math.abs(m.m41 - target) < 0.5;
      },
      end,
      { timeout: 4000 },
    );
  const drag = async (end) => {
    await page.locator(".reel-camera").focus();
    await page.keyboard.press(end === "start" ? "Home" : "End");
    await page.waitForTimeout(850);
    const before = await geometry(),
      box = await page.locator(".reel-camera").boundingBox();
    const from = end === "start" ? box.x + 24 : box.x + box.width - 24,
      to = end === "start" ? box.x + box.width - 24 : box.x + 24;
    await page.mouse.move(from, box.y + box.height * 0.4);
    await page.mouse.down();
    await page.mouse.move(to, box.y + box.height * 0.4, { steps: 16 });
    const held = await geometry();
    assert(
      end === "start" ? held.x > before.x + 160 : held.x < before.x - 160,
      `Wide elastic drag at ${end}`,
    );
    const selection = await page
      .locator(".candidate .reel-frame.is-current")
      .getAttribute("aria-label");
    await page.mouse.up();
    await settled(end);
    assert.equal(
      await page
        .locator(".candidate .reel-frame.is-current")
        .getAttribute("aria-label"),
      selection,
      "Dragging must not select the frame underneath",
    );
    assert.equal(await page.locator("dialog[open]").count(), 0);
  };
  await drag("start");
  await drag("end");
  for (const end of ["start", "end"]) {
    await drag(end);
    const box = await page.locator(".reel-camera").boundingBox();
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    for (let i = 0; i < 8; i++) {
      await page.mouse.wheel(0, end === "start" ? -180 : 180);
      await page.waitForTimeout(25);
    }
    const stretched = await geometry();
    assert(
      end === "start"
        ? stretched.x > stretched.max + 160
        : stretched.x < stretched.min - 160,
      `Wide wheel overscroll at ${end}`,
    );
    await settled(end);
  }
  await page.getByRole("button", { name: "Fit", exact: true }).click();
  await page.waitForTimeout(450);
  const fit = await geometry();
  const box = await page.locator(".reel-camera").boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  for (let i = 0; i < 6; i++) {
    await page.mouse.wheel(0, -180);
    await page.waitForTimeout(25);
  }
  assert((await geometry()).x > fit.x + 160);
  await settled("start");
  assert.deepEqual(errors, []);
  console.log(
    "Film gestures passed: large pointer/wheel overscroll at both ends, animated padded rebound, unchanged selection and fitted-film centring.",
  );
} finally {
  await browser.close();
}
