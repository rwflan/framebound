import test from "node:test";
import assert from "node:assert/strict";
globalThis.matchMedia = () => ({ matches: true });
globalThis.ResizeObserver = class {
  observe() {}
  disconnect() {}
};
globalThis.requestAnimationFrame = () => 1;
globalThis.cancelAnimationFrame = () => {};
const { ReelCamera } = await import("../src/reel-camera.js");
function camera() {
  const captures = new Set();
  const viewport = {
    clientWidth: 1000,
    clientHeight: 600,
    addEventListener() {},
    querySelectorAll() {
      return [];
    },
    getBoundingClientRect() {
      return { left: 0, top: 0 };
    },
    setPointerCapture(id) {
      captures.add(id);
    },
    hasPointerCapture(id) {
      return captures.has(id);
    },
    releasePointerCapture(id) {
      captures.delete(id);
    },
    classList: { add() {}, remove() {} },
  };
  const track = {
    offsetWidth: 2000,
    offsetHeight: 500,
    querySelectorAll() {
      return [];
    },
    style: {},
  };
  return { c: new ReelCamera(viewport, track, () => {}), captures };
}
test("camera zoom anchors the viewed pixels, clamps both axes and Fits all film", () => {
  const { c } = camera();
  c.jump(-400);
  c.zoomTo(1.5, 500, 300, true);
  assert.equal((500 - c.x) / c.zoom, 900);
  c.zoomTo(2, 500, 200, true);
  assert.ok(Math.abs((200 - 300 - c.y) / c.zoom + 100 / 1.5) < 1e-8);
  c.jump(-1e5, -1e5);
  assert.equal(c.x, c.min);
  assert.equal(c.y, c.minY);
  c.fit();
  assert.ok(c.trackWidth * c.zoom <= c.width - 48 + 0.001);
  assert.ok(c.trackHeight * c.zoom <= c.height - 24 + 0.001);
  c.destroy();
});
test("two-pointer pinch keeps its centroid anchored and releases both captures", () => {
  const { c, captures } = camera();
  c.jump(-400);
  const event = (id, x, y) => ({
    pointerId: id,
    pointerType: "touch",
    button: 0,
    clientX: x,
    clientY: y,
    target: {
      closest() {
        return null;
      },
    },
    preventDefault() {},
  });
  c.down(event(1, 200, 200));
  c.down(event(2, 400, 200));
  assert.equal(captures.size, 2);
  c.move(event(2, 500, 200));
  assert.equal(c.zoom, 1.5);
  assert.equal((350 - c.x) / c.zoom, 700);
  c.up(event(2, 500, 200));
  c.up(event(1, 200, 200));
  assert.equal(captures.size, 0);
  c.destroy();
});
