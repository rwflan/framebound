/** Exact integer-timeline playback math (mirrors media/timeline.py).
 *  The presentation clock never rewrites authored holds: speed scales the
 *  presentation only; tick-step operates on exact integers; no chained timers. */
export function slotAtTick(holds: number[], tick: number, loop: boolean): number {
  const total = holds.reduce((a, b) => a + b, 0);
  const t = loop ? tick % total : Math.min(tick, total - 1);
  let acc = 0;
  for (let i = 0; i < holds.length; i++) {
    if (acc <= t && t < acc + holds[i]) return i;
    acc += holds[i];
  }
  throw new Error('unreachable tick');
}

/** First authored tick of a slot (for exact selection/stepping). */
export function tickOfSlot(holds: number[], slot: number): number {
  let acc = 0;
  for (let i = 0; i < Math.min(slot, holds.length); i++) acc += holds[i];
  return acc;
}

export function totalTicks(holds: number[]): number {
  return holds.reduce((a, b) => a + b, 0);
}

/** Map a pointer event on a transformed canvas back to native pixels.
 *  scaleX/scaleY are CSS-px-per-native-px (uniform when aspect is preserved);
 *  using one width scale for both axes distorts non-square frames, so the
 *  caller must pass both. Mirroring flips around the native width. */
export function toNative(
  clientX: number, clientY: number, rect: { left: number; top: number; width: number; height: number },
  nativeW: number, nativeH: number,
  opts: { scaleX: number; scaleY: number; offsetX: number; offsetY: number; mirrored: boolean },
): { x: number; y: number } {
  const cssX = (clientX - rect.left - opts.offsetX) / opts.scaleX;
  const cssY = (clientY - rect.top - opts.offsetY) / opts.scaleY;
  const x = opts.mirrored ? nativeW - cssX : cssX;
  return {
    x: Math.max(0, Math.min(nativeW - 1e-6, x)),
    y: Math.max(0, Math.min(nativeH - 1e-6, cssY)),
  };
}
