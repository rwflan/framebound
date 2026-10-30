import {
  forwardRef,
  useLayoutEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import type { CSSProperties, ReactNode } from "react";
import { ReelCamera } from "./reel-camera";

export type FilmHandle = {
  reveal: (index: number, center?: boolean) => void;
  zoom: (step: number) => void;
  reset: () => void;
  fit: () => void;
  pan: (fraction: number) => void;
};
const positions = new Map<string, { x: number; y: number; zoom: number }>();
const levels = [0.05, 0.1, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];
export const Film = forwardRef<
  FilmHandle,
  {
    filmKey: string;
    count: number;
    sequence?: boolean;
    labels?: string[];
    children: ReactNode;
    onZoom: (zoom: number) => void;
    onPosition: (p: number) => void;
    onStep: (index: number, shift: boolean) => void;
    selected: number;
  }
>(function Film(
  {
    filmKey,
    count,
    sequence,
    labels,
    children,
    onZoom,
    onPosition,
    onStep,
    selected,
  },
  ref,
) {
  const viewport = useRef<HTMLDivElement>(null),
    track = useRef<HTMLDivElement>(null),
    camera = useRef<ReelCamera | null>(null);
  const callbacks = useRef({ onZoom, onPosition, onStep, selected });
  callbacks.current = { onZoom, onPosition, onStep, selected };
  useImperativeHandle(
    ref,
    () => ({
      reveal: (i, center = false) => {
        const c = camera.current;
        if (c) c.reveal(i, c.trackWidth / count, center);
      },
      zoom: (step) => {
        const c = camera.current;
        if (c)
          c.zoomTo(
            step > 0
              ? levels.find((z) => z > c.targetZoom + 0.005) || 2
              : [...levels].reverse().find((z) => z < c.targetZoom - 0.005) ||
                  0.05,
          );
      },
      reset: () => camera.current?.zoomTo(1),
      fit: () => camera.current?.fit(),
      pan: (p) => {
        const c = camera.current;
        if (c) c.go(c.max - p * (c.max - c.min));
      },
    }),
    [count],
  );
  useLayoutEffect(() => {
    if (!viewport.current || !track.current || !count) return;
    const v = viewport.current,
      t = track.current;
    const c = new ReelCamera(v, t, (p, z) => {
      callbacks.current.onZoom(Math.round(z * 100));
      callbacks.current.onPosition(
        Math.round(Math.max(0, Math.min(1, p)) * 1000),
      );
      v.dataset.zoomDetail =
        (c.trackWidth / count) * z < 65
          ? "micro"
          : (c.trackWidth / count) * z < 130
            ? "compact"
            : "expanded";
    });
    c.centerEdges = Boolean(sequence);
    camera.current = c;
    c.onResize = () =>
      c.reveal(callbacks.current.selected, c.trackWidth / count, true);
    const old = positions.get(filmKey);
    c.zoom = c.targetZoom = old?.zoom || 1;
    c.bounds();
    c.jump(
      c.width / 2 -
        (((callbacks.current.selected + 0.5) * c.trackWidth) / count) * c.zoom,
      0,
    );
    return () => {
      positions.set(filmKey, { x: c.x, y: c.y, zoom: c.zoom });
      c.destroy();
      camera.current = null;
    };
  }, [filmKey, count]);
  return (
    <div
      ref={viewport}
      className={"reel-camera" + (sequence ? " reel-sequence-camera" : "")}
      role="region"
      aria-label={
        sequence ? "Draggable frame comparison" : "Draggable review film"
      }
      tabIndex={0}
      onKeyDown={(e) => {
        if (
          !["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key) ||
          (e.target as HTMLElement).matches("input,select,textarea")
        )
          return;
        e.preventDefault();
        callbacks.current.onStep(
          e.key === "Home"
            ? 0
            : e.key === "End"
              ? count - 1
              : Math.max(
                  0,
                  Math.min(
                    count - 1,
                    selected + (e.key === "ArrowRight" ? 1 : -1),
                  ),
                ),
          e.shiftKey,
        );
      }}
    >
      <div className="reel-surface">
        <div
          ref={track}
          className={
            "reel-track " + (sequence ? "reel-sequence" : "reel-collection")
          }
          style={{ "--cell-count": count } as CSSProperties}
        >
          {children}
        </div>
      </div>
      {labels && (
        <div className="reel-lane-labels" aria-hidden="true">
          {labels.map((l, i) => (
            <div
              className={
                "reel-lane-label " +
                (i === 1 ? "candidate" : i === 2 ? "checks" : "reference")
              }
              key={i}
            >
              <strong>{l}</strong>
            </div>
          ))}
        </div>
      )}
      <div className="reel-vignette" aria-hidden="true" />
    </div>
  );
});
export function useFilm() {
  const film = useRef<FilmHandle>(null),
    [zoom, setZoom] = useState(100),
    [position, setPosition] = useState(0);
  return { film, zoom, setZoom, position, setPosition };
}
