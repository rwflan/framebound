import { useCallback, useEffect, useRef, useState } from 'react';
import { slotAtTick, tickOfSlot, totalTicks } from './playback';

/** Persistent monotonic-clock accumulator: pause/resume, speed changes and
 *  frame selection preserve the authored-tick position. One-shot clips stop
 *  at the terminal tick instead of wrapping. */
export function usePresentationClock(opts: {
  holds: number[];
  tps: number;
  loop: boolean;
  resetKey: string | number;
  autoPlay?: boolean;
}) {
  const { holds, tps, loop, resetKey } = opts;
  const [tickFloat, setTickFloat] = useState(0);
  const [playing, setPlaying] = useState(opts.autoPlay ?? true);
  const [speed, setSpeedState] = useState(1);
  const accRef = useRef(0);
  const lastRef = useRef(0);
  const rafRef = useRef(0);
  const liveRef = useRef({ holds, tps, loop, speed });
  liveRef.current = { holds, tps, loop, speed };

  useEffect(() => {
    accRef.current = 0;
    setTickFloat(0);
  }, [resetKey]);

  useEffect(() => {
    if (!playing) return;
    lastRef.current = performance.now();
    const step = (now: number) => {
      const s = liveRef.current;
      const dt = (now - lastRef.current) / 1000;
      lastRef.current = now;
      const total = totalTicks(s.holds);
      accRef.current += dt * s.tps * s.speed;
      if (s.loop && total > 0) accRef.current %= total;
      if (!s.loop && accRef.current >= total) {
        accRef.current = total - 1e-3;
        setTickFloat(accRef.current);
        setPlaying(false);
        return;
      }
      setTickFloat(accRef.current);
      rafRef.current = requestAnimationFrame(step);
    };
    rafRef.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(rafRef.current);
  }, [playing]);

  const total = totalTicks(holds);
  const tick = Math.max(0, Math.min(total - 1, Math.floor(loop ? tickFloat % total : tickFloat)));
  const slot = holds.length ? slotAtTick(holds, tick, loop) : 0;

  const poke = useCallback(() => { lastRef.current = performance.now(); }, []);
  const selectTick = useCallback((t: number) => {
    const totalNow = totalTicks(liveRef.current.holds);
    accRef.current = Math.max(0, Math.min(totalNow - 1e-3, t));
    lastRef.current = performance.now();
    setTickFloat(accRef.current);
  }, []);
  const stepTick = useCallback((d: number) => {
    selectTick(Math.floor(accRef.current) + d);
  }, [selectTick]);
  const selectSlot = useCallback((s: number) => {
    selectTick(tickOfSlot(liveRef.current.holds, s));
  }, [selectTick]);
  const setSpeed = useCallback((sp: number) => {
    if (!(sp > 0)) return;
    lastRef.current = performance.now(); // continuity: no jump on speed change
    setSpeedState(sp);
  }, []);

  return { tick, tickFloat, slot, total, playing, setPlaying, speed, setSpeed, selectTick, stepTick, selectSlot, poke };
}
