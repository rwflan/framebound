import test from 'node:test';
import assert from 'node:assert/strict';
import { slotAtTick, tickOfSlot, totalTicks, toNative, filmPosition } from './playback.bundle.mjs';

// Mirrors media/timeline.py half-open intervals: slot i covers [sum(holds[:i]), sum(holds[:i+1])).
test('slotAtTick maps authored ticks to slots', () => {
  const holds = [4, 4, 4, 4, 4, 4, 4, 4];
  assert.equal(slotAtTick(holds, 0, true), 0);
  assert.equal(slotAtTick(holds, 3, true), 0);
  assert.equal(slotAtTick(holds, 4, true), 1);
  assert.equal(slotAtTick(holds, 12, true), 3);
  assert.equal(slotAtTick(holds, 31, true), 7);
  assert.equal(slotAtTick(holds, 32, true), 0); // loop wraps
  assert.equal(slotAtTick(holds, 32, false), 7); // one-shot holds terminal
  assert.equal(slotAtTick(holds, 999, false), 7);
});

test('tickOfSlot / totalTicks are exact inverses', () => {
  const holds = [4, 4, 4, 4, 4, 4, 4, 4];
  assert.equal(totalTicks(holds), 32);
  assert.equal(tickOfSlot(holds, 0), 0);
  assert.equal(tickOfSlot(holds, 3), 12);
  assert.equal(slotAtTick(holds, tickOfSlot(holds, 5), true), 5);
});

test('toNative uses separate x/y scales and clamps', () => {
  const rect = { left: 100, top: 50, width: 288, height: 144 };
  // non-square stage: width scale 4.5, height scale 2.25 for a 64x64 canvas
  const p = toNative(100 + 45, 50 + 22.5, rect, 64, 64,
    { scaleX: 288 / 64, scaleY: 144 / 64, offsetX: 0, offsetY: 0, mirrored: false });
  assert.ok(Math.abs(p.x - 10) < 1e-9, `x=${p.x}`);
  assert.ok(Math.abs(p.y - 10) < 1e-9, `y=${p.y}`);
  // a single width scale for both axes would map y to 5, not 10
  const wrong = (22.5) / (288 / 64);
  assert.ok(Math.abs(wrong - 5) < 1e-9);
  // mirrored flips around native width; out-of-bounds clamps
  const m = toNative(100, 50, rect, 64, 64,
    { scaleX: 288 / 64, scaleY: 144 / 64, offsetX: 0, offsetY: 0, mirrored: true });
  assert.equal(m.x, 64 - 1e-6);
  const over = toNative(10000, 10000, rect, 64, 64,
    { scaleX: 1, scaleY: 1, offsetX: 0, offsetY: 0, mirrored: false });
  assert.ok(over.x <= 64 && over.y <= 64);
});


test('film motion preserves uneven authored holds and wraps to an identical repeat',()=>{
  const holds=[2,6,1];
  assert.equal(filmPosition(holds,0,true),0);
  assert.equal(filmPosition(holds,1,true),.5);
  assert.equal(filmPosition(holds,2,true),1);
  assert.equal(filmPosition(holds,5,true),1.5);
  assert.equal(filmPosition(holds,8.5,true),2.5);
  assert.equal(filmPosition(holds,9,true),0);
  assert.equal(filmPosition(holds,10,true),filmPosition(holds,1,true));
  assert.ok(filmPosition(holds,100,false)<3);
  assert.equal(filmPosition(holds,-10,false),0);
  assert.equal(filmPosition([],0,true),0);
});
