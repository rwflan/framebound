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

test("lane names remain separated at minimum zoom", () => {
  const { c } = camera();
  c.lanes = [
    { top: 34, height: 190 },
    { top: 250, height: 190 },
  ];
  c.labels = [0, 1].map(() => ({
    style: {
      setProperty(key, value) {
        this[key] = value;
      },
    },
  }));
  c.zoomTo(0.05, 500, 300, true);
  const centers = c.labels.map(
    (n) => parseFloat(n.style.top) + parseFloat(n.style["--label-y"]),
  );
  assert.ok(centers[1] - centers[0] >= 28);
  assert.ok(c.labels.every((n) => n.style.visibility === "visible"));
  c.destroy();
});

test("sequence camera centers both end frames and fit centers the whole strip", () => {
  const { c } = camera();
  c.track.querySelector = () => ({ offsetWidth: 250 });
  c.centerEdges = true;
  c.bounds();
  for (const index of [0, 3, 7]) {
    c.reveal(index, 250, true);
    assert.equal(c.x + (index + 0.5) * 250 * c.zoom, c.width / 2);
  }
  c.fit();
  assert.ok(c.trackWidth * c.zoom <= c.width - 48 + 0.001);
  assert.ok(Math.abs(c.x + (c.trackWidth * c.zoom) / 2 - c.width / 2) < 0.001);
  c.destroy();
});
test("reference, candidate and measurement names stay distinct at overview zoom", () => {
  const { c } = camera();
  c.lanes = [
    { top: 34, height: 190 },
    { top: 280, height: 190 },
    { top: 530, height: 75 },
  ];
  c.labels = c.lanes.map(() => ({
    style: {
      setProperty(k, v) {
        this[k] = v;
      },
    },
  }));
  c.zoomTo(0.05, 500, 300, true);
  const centers = c.labels.map(
    (n) => parseFloat(n.style.top) + parseFloat(n.style["--label-y"]),
  );
  assert.ok(centers[1] - centers[0] >= 28 && centers[2] - centers[1] >= 28);
  c.destroy();
});
