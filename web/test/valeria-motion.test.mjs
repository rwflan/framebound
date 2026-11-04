import test from 'node:test';
import assert from 'node:assert/strict';
import { startJump, advanceVertical } from './valeria-motion.bundle.mjs';

test('jump launches from its exact initial boundary, reaches an apex and lands', () => {
  const state = {offsetY: 0, velocityY: 0};
  assert.equal(startJump(state), true);
  advanceVertical(state, 1/60);
  assert.ok(state.offsetY < -0.01);
  assert.equal(startJump(state), false);
  let minimum = state.offsetY;
  let descended = false;
  for (let i=0; i<120; i++) {
    advanceVertical(state, 1/60);
    minimum = Math.min(minimum, state.offsetY);
    descended ||= state.velocityY > 0;
  }
  assert.ok(minimum < -70);
  assert.equal(descended, true);
  assert.deepEqual(state, {offsetY:0,velocityY:0});
  assert.equal(startJump(state), true);
});
