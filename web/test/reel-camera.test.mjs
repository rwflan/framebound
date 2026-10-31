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

function pointer(x) {
  return {
    pointerId: 1,
    pointerType: "mouse",
    button: 0,
    clientX: x,
    clientY: 100,
    target: {
      closest() {
        return null;
      },
    },
    preventDefault() {},
  };
}
function wheel(deltaY) {
  return { deltaX: 0, deltaY, deltaMode: 0, preventDefault() {} };
}
test("drag can travel far beyond each end and releases to padded film edges", () => {
  const { c, captures } = camera();
  c.track.querySelector = () => ({ offsetWidth: 250 });
  c.centerEdges = true;
  c.bounds();
  c.jump(c.max);
  const first = c.x;
  c.down(pointer(100));
  c.move(pointer(900));
  assert(
    c.x > first + 160,
    "The drag should stretch far past a centred end frame",
  );
  c.up(pointer(900));
  assert.equal(c.x, 24);
  assert.equal(captures.size, 0);
  c.jump(c.min);
  const last = c.x;
  c.down(pointer(900));
  c.move(pointer(100));
  assert(c.x < last - 160);
  c.up(pointer(100));
  assert.equal(c.x, c.width - c.trackWidth * c.zoom - 24);
  assert.equal(captures.size, 0);
  c.reveal(0, 250, true);
  assert.equal(
    c.x + 125,
    c.width / 2,
    "Frame selection still centres the first frame",
  );
  c.destroy();
});
test("wheel scrolling stretches beyond both ends and settles after input stops", async () => {
  const { c } = camera();
  c.jump(24);
  c.wheel(wheel(-1000));
  assert(c.x > 24 + 160);
  await new Promise((resolve) => setTimeout(resolve, 180));
  assert.equal(c.x, 24);
  assert.equal(c.wheelPan, null);
  const end = c.width - c.trackWidth * c.zoom - 24;
  c.jump(end);
  c.wheel(wheel(1000));
  assert(c.x < end - 160);
  await new Promise((resolve) => setTimeout(resolve, 180));
  assert.equal(c.x, end);
  c.destroy();
});
test("navigation cancels a pending wheel rebound and short film returns to the centre", async () => {
  const { c } = camera();
  c.wheel(wheel(-1000));
  c.reveal(3, 250, true);
  const selected = c.x;
  await new Promise((resolve) => setTimeout(resolve, 180));
  assert.equal(c.x, selected);
  c.zoomTo(0.25, 500, 300, true);
  c.jump((c.width - c.trackWidth * c.zoom) / 2);
  const center = c.x;
  c.down(pointer(100));
  c.move(pointer(900));
  assert(c.x > center + 160);
  c.up(pointer(900));
  assert.equal(c.x, center);
  c.destroy();
});

test('drawing on a frame keeps the camera fixed and leaves pointer capture to the annotation surface',()=>{
  const {c,captures}=camera();c.jump(-400);const before={x:c.x,y:c.y,zoom:c.zoom};
  const target={closest:selector=>selector.includes('data-annotation')?{}:null};
  c.down({...pointer(200),target});c.move({...pointer(350),target});
  let prevented=false;c.wheel({...wheel(-120),target,preventDefault(){prevented=true;}});
  assert.equal(captures.size,0);assert.equal(c.drag,null);assert.equal(prevented,true);
  assert.deepEqual({x:c.x,y:c.y,zoom:c.zoom},before);c.destroy();
});
