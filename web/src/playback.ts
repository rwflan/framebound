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

/** Map a pointer event on a zoomed/mirrored canvas back to native pixels. */
export function toNative(
  clientX: number, clientY: number, rect: DOMRect,
  nativeW: number, nativeH: number,
  opts: { scale: number; offsetX: number; offsetY: number; mirrored: boolean; dpr?: number },
): { x: number; y: number } {
  const cssX = (clientX - rect.left - opts.offsetX) / opts.scale;
  const cssY = (clientY - rect.top - opts.offsetY) / opts.scale;
  const x = opts.mirrored ? nativeW - cssX : cssX;
  return { x: Math.max(0, Math.min(nativeW - 1e-6, x)), y: Math.max(0, Math.min(nativeH - 1e-6, cssY)) };
}
