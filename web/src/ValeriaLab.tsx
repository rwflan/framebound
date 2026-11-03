import { useEffect, useRef, useState } from "react";
import { Icon } from "./shared";
import "./valeria-lab.css";

type StateSpec = {
  frames: number[];
  duration_ticks: number[];
  loop?: boolean;
};

type RefinedMeta = {
  frames: {
    region: [number, number, number, number];
    pivot: [number, number];
    trim_gp?: [number, number];
    pixel_scale?: number;
  }[];
};

type Playback = {
  states: Record<string, StateSpec>;
};

type DemoManifest = {
  direct_muse: {
    model: string;
    poses: number;
    grid: [number, number];
    alpha: boolean;
    incurred_usd: number;
  };
  framework: {
    registered_poses: number;
    run_keys: number;
    alpha: boolean;
  };
};

type EngineState = "idle" | "run" | "jump" | "apex" | "fall" | "slide" | "whip";
type CompareMode = "compare" | "framework" | "direct";

const RAW_CELLS = 9;
const RAW_COLUMNS = 3;
const RAW_CELL_WIDTH = 640;
const RAW_CELL_HEIGHT = 1280 / 3;
const TICKS_PER_SECOND = 60;

const STATE_COPY: Record<EngineState, string> = {
  idle: "idle",
  run: "run",
  jump: "takeoff",
  apex: "apex",
  fall: "descent",
  slide: "slide",
  whip: "attack",
};

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error(`Could not load ${src}`));
    image.src = src;
  });
}

function frameAt(spec: StateSpec, elapsedSeconds: number): number {
  const total = spec.duration_ticks.reduce((sum, value) => sum + value, 0);
  let tick = Math.floor(elapsedSeconds * TICKS_PER_SECOND);
  tick = spec.loop === false ? Math.min(total - 1, tick) : tick % total;
  let end = 0;
  for (let index = 0; index < spec.frames.length; index += 1) {
    end += spec.duration_ticks[index];
    if (tick < end) return spec.frames[index];
  }
  return spec.frames[spec.frames.length - 1];
}

function rawCell(state: EngineState, elapsedSeconds: number): number {
  if (state === "run") {
    return Math.floor(elapsedSeconds * 12) % RAW_CELLS;
  }
  if (state === "idle") return 0;
  if (state === "slide") return 7;
  if (state === "whip") return 8;
  return elapsedSeconds % 0.32 < 0.16 ? 3 : 5;
}

function drawArena(
  canvas: HTMLCanvasElement,
  accent: string,
): CanvasRenderingContext2D | null {
  const context = canvas.getContext("2d");
  if (!context) return null;
  const width = canvas.width;
  const height = canvas.height;
  context.clearRect(0, 0, width, height);

  const sky = context.createLinearGradient(0, 0, 0, height);
  sky.addColorStop(0, "#dce8e5");
  sky.addColorStop(0.58, "#ece6d7");
  sky.addColorStop(1, "#d7cdb8");
  context.fillStyle = sky;
  context.fillRect(0, 0, width, height);

  context.strokeStyle = "#738a8750";
  context.lineWidth = 1;
  for (let x = 24; x < width; x += 38) {
    context.beginPath();
    context.moveTo(x + 0.5, 0);
    context.lineTo(x + 0.5, height);
    context.stroke();
  }
  for (let y = 28; y < height; y += 38) {
    context.beginPath();
    context.moveTo(0, y + 0.5);
    context.lineTo(width, y + 0.5);
    context.stroke();
  }

  context.fillStyle = "#8d9b8a42";
  context.fillRect(0, 94, width, 4);
  context.fillRect(0, 142, width, 2);

  const floor = height - 44;
  context.fillStyle = "#cdbf9f";
  context.fillRect(0, floor, width, height - floor);
  context.strokeStyle = "#9d8a69";
  context.lineWidth = 2;
  context.beginPath();
  context.moveTo(0, floor + 1);
  context.lineTo(width, floor + 1);
  context.stroke();
  context.fillStyle = "#917e6040";
  for (let x = -24; x < width + 40; x += 48) {
    context.beginPath();
    context.moveTo(x, floor + 1);
    context.lineTo(x + 25, height);
    context.lineTo(x + 38, height);
    context.lineTo(x + 13, floor + 1);
    context.closePath();
    context.fill();
  }

  context.fillStyle = "#fff9e8b8";
  context.fillRect(0, 0, width, 12);
  context.fillStyle = accent;
  context.fillRect(0, 12, 56, 3);
  return context;
}

function drawFramework(
  canvas: HTMLCanvasElement,
  atlas: HTMLImageElement,
  meta: RefinedMeta,
  playback: Playback,
  state: EngineState,
  elapsed: number,
  x: number,
  yOffset: number,
  facing: number,
) {
  const context = drawArena(canvas, "#c85a2d");
  if (!context) return;

  const frameIndex = frameAt(playback.states[state], elapsed);
  const frame = meta.frames[frameIndex];
  if (!frame) return;
  const [sx, sy, sw, sh] = frame.region;
  const scale = Math.min(5.2, canvas.height / 65);
  const pixelScale = frame.pixel_scale ?? 0.25;
  const trim = frame.trim_gp ?? [0, 0];
  const pivotX = frame.pivot[0] - trim[0] * 0.5;
  const pivotY = frame.pivot[1] - trim[1] * 0.5;
  const drawX = 0;
  const drawY = 0;
  const width = sw * pixelScale * scale;
  const height = sh * pixelScale * scale;

  context.save();
  context.translate(x, canvas.height - 44 + yOffset);
  context.scale(facing, 1);
  context.drawImage(
    atlas,
    sx,
    sy,
    sw,
    sh,
    drawX - pivotX * scale,
    drawY - pivotY * scale,
    width,
    height,
  );
  context.restore();

  context.fillStyle = "#334d4922";
  context.beginPath();
  context.ellipse(x, canvas.height - 42, state === "slide" ? 44 : 23, 6, 0, 0, Math.PI * 2);
  context.fill();
}

function drawDirect(
  canvas: HTMLCanvasElement,
  sheet: HTMLImageElement,
  state: EngineState,
  elapsed: number,
  x: number,
  yOffset: number,
  facing: number,
) {
  const context = drawArena(canvas, "#d12482");
  if (!context) return;
  const cell = rawCell(state, elapsed);
  const sourceX = (cell % RAW_COLUMNS) * RAW_CELL_WIDTH;
  const sourceY = Math.floor(cell / RAW_COLUMNS) * RAW_CELL_HEIGHT;
  const width = Math.min(canvas.width * 0.70, canvas.height * 1.42);
  const height = (width * RAW_CELL_HEIGHT) / RAW_CELL_WIDTH;

  context.save();
  context.translate(x, canvas.height - 40 + yOffset);
  context.scale(facing, 1);
  context.beginPath();
  context.rect(-width / 2, -height * 0.88, width, height);
  context.clip();
  context.drawImage(
    sheet,
    sourceX,
    sourceY,
    RAW_CELL_WIDTH,
    RAW_CELL_HEIGHT,
    -width / 2,
    -height * 0.88,
    width,
    height,
  );
  context.restore();
}

export function ValeriaLab() {
  const [mode, setMode] = useState<CompareMode>("compare");
  const [paused, setPaused] = useState(false);
  const [state, setState] = useState<EngineState>("idle");
  const [assets, setAssets] = useState<{
    atlas: HTMLImageElement;
    raw: HTMLImageElement;
    meta: RefinedMeta;
    playback: Playback;
    manifest: DemoManifest;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const frameworkCanvas = useRef<HTMLCanvasElement>(null);
  const directCanvas = useRef<HTMLCanvasElement>(null);
  const singleCanvas = useRef<HTMLCanvasElement>(null);
  const keys = useRef(new Set<string>());
  const engine = useRef({
    x: 410,
    offsetY: 0,
    velocityY: 0,
    facing: 1,
    state: "idle" as EngineState,
    stateStarted: 0,
    lastTime: 0,
    slideUntil: 0,
    attackUntil: 0,
  });
  const jump = () => {
    if (engine.current.offsetY < -0.01) return;
    engine.current.velocityY = -390;
    engine.current.offsetY = -0.01;
  };
  const slide = () => {
    if (engine.current.offsetY < -0.01) return;
    engine.current.slideUntil = performance.now() / 1000 + 0.46;
  };
  const attack = () => {
    engine.current.attackUntil = performance.now() / 1000 + 0.42;
  };

  useEffect(() => {
    let live = true;
    Promise.all([
      loadImage("/demo/valeria/refined-atlas.png"),
      loadImage("/demo/valeria/raw-muse-sheet.png"),
      fetch("/demo/valeria/refined-meta.json").then((response) => {
        if (!response.ok) throw new Error("Could not load refined frame metadata");
        return response.json() as Promise<RefinedMeta>;
      }),
      fetch("/demo/valeria/playback.json").then((response) => {
        if (!response.ok) throw new Error("Could not load Valeria playback");
        return response.json() as Promise<Playback>;
      }),
      fetch("/demo/valeria/manifest.json").then((response) => {
        if (!response.ok) throw new Error("Could not load Valeria proof manifest");
        return response.json() as Promise<DemoManifest>;
      }),
    ])
      .then(([atlas, raw, meta, playback, manifest]) => {
        if (live) setAssets({ atlas, raw, meta, playback, manifest });
      })
      .catch((reason) => {
        if (live) setError(reason);
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    const down = (event: KeyboardEvent) => {
      if (
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        (event.target as HTMLElement).closest("input,textarea,select,[contenteditable='true']")
      ) {
        return;
      }
      const key = event.key.toLowerCase();
      if (["arrowleft", "arrowright", "a", "d", " "].includes(key)) event.preventDefault();
      keys.current.add(key);
      if (key === " ") jump();
      if (key === "s") slide();
      if (key === "j") attack();
    };
    const up = (event: KeyboardEvent) => keys.current.delete(event.key.toLowerCase());
    const blur = () => keys.current.clear();
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    window.addEventListener("blur", blur);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
      window.removeEventListener("blur", blur);
    };
  }, []);

  useEffect(() => {
    if (!assets) return;
    let request = 0;
    engine.current.lastTime = performance.now() / 1000;

    const paint = (time: number) => {
      const now = time / 1000;
      const delta = Math.min(0.04, Math.max(0, now - engine.current.lastTime));
      engine.current.lastTime = now;
      if (!paused) {
        const moving =
          keys.current.has("arrowleft") ||
          keys.current.has("a") ||
          keys.current.has("arrowright") ||
          keys.current.has("d");
        if (keys.current.has("arrowleft") || keys.current.has("a")) {
          engine.current.facing = -1;
          engine.current.x -= 112 * delta;
        }
        if (keys.current.has("arrowright") || keys.current.has("d")) {
          engine.current.facing = 1;
          engine.current.x += 112 * delta;
        }
        engine.current.x = Math.max(92, Math.min(868, engine.current.x));
        if (engine.current.offsetY < -0.01) {
          engine.current.velocityY += 980 * delta;
          engine.current.offsetY += engine.current.velocityY * delta;
        }
        if (engine.current.offsetY >= 0) {
          engine.current.offsetY = 0;
          engine.current.velocityY = 0;
        }
        let nextState: EngineState = "idle";
        if (engine.current.attackUntil > now) nextState = "whip";
        else if (engine.current.slideUntil > now) nextState = "slide";
        else if (engine.current.offsetY < -0.01) {
          nextState =
            engine.current.velocityY < -80
              ? "jump"
              : engine.current.velocityY < 180
                ? "apex"
                : "fall";
        } else if (moving) nextState = "run";
        if (nextState !== engine.current.state) {
          engine.current.state = nextState;
          engine.current.stateStarted = now;
          setState(nextState);
        }
      }
      const elapsed = paused ? 0 : now - engine.current.stateStarted;
      if (frameworkCanvas.current) {
        drawFramework(
          frameworkCanvas.current,
          assets.atlas,
          assets.meta,
          assets.playback,
          engine.current.state,
          elapsed,
          engine.current.x / 2,
          engine.current.offsetY,
          engine.current.facing,
        );
      }
      if (directCanvas.current) {
        drawDirect(
          directCanvas.current,
          assets.raw,
          engine.current.state,
          elapsed,
          engine.current.x / 2,
          engine.current.offsetY,
          engine.current.facing,
        );
      }
      if (singleCanvas.current) {
        if (mode === "direct") {
          drawDirect(
            singleCanvas.current,
            assets.raw,
            engine.current.state,
            elapsed,
            engine.current.x,
            engine.current.offsetY,
            engine.current.facing,
          );
        } else {
          drawFramework(
            singleCanvas.current,
            assets.atlas,
            assets.meta,
            assets.playback,
            engine.current.state,
            elapsed,
            engine.current.x,
            engine.current.offsetY,
            engine.current.facing,
          );
        }
      }
      request = requestAnimationFrame(paint);
    };
    request = requestAnimationFrame(paint);
    return () => cancelAnimationFrame(request);
  }, [assets, mode, paused]);

  return (
    <section className="valeria-proof" aria-label="Valeria movement proof">
      <div className="proof-toolbar">
        <div className="proof-verdict">
          <span className="proof-live"><i />Live proof</span>
          <strong>Same character. Same controls.</strong>
          <span className="proof-state" aria-live="polite">{STATE_COPY[state]}</span>
        </div>
        <div className="proof-view-switch" role="group" aria-label="Output view">
          {(["compare", "framework", "direct"] as const).map((value) => (
            <button
              key={value}
              aria-pressed={mode === value}
              onClick={() => setMode(value)}
            >
              {value === "framework" ? "Framework" : value === "direct" ? "Direct Muse" : "Compare"}
            </button>
          ))}
        </div>
        <button
          className="proof-pause"
          onClick={() => setPaused((value) => !value)}
          aria-pressed={paused}
        >
          <Icon name={paused ? "play" : "pause"} />
          {paused ? "Resume" : "Pause"}
        </button>
      </div>

      <div className={`proof-field proof-field--${mode}`}>
        {mode === "compare" ? (
          <>
            <article className="proof-lane" data-output="direct">
              <header>
                <span>Direct Muse</span>
                <small>opaque 3 × 3 contact sheet</small>
                <b>Control</b>
              </header>
              <canvas ref={directCanvas} width={480} height={322} aria-label="Direct Muse Valeria playfield" />
            </article>
            <article className="proof-lane" data-output="framework">
              <header>
                <span>Framebound</span>
                <small>registered native frames + authored holds</small>
                <b>Delivery ready</b>
              </header>
              <canvas ref={frameworkCanvas} width={480} height={322} aria-label="Framebound Valeria playfield" />
            </article>
          </>
        ) : (
          <article className="proof-lane proof-lane--single" data-output={mode}>
            <header>
              <span>{mode === "direct" ? "Direct Muse" : "Framebound"}</span>
              <small>
                {mode === "direct"
                  ? "raw provider output cropped by its visible cell bounds"
                  : "registered frames with native timing and transparency"}
              </small>
              <b>{mode === "direct" ? "Control" : "Delivery ready"}</b>
            </header>
            <canvas ref={singleCanvas} width={960} height={322} aria-label="Valeria playfield" />
          </article>
        )}
        {!assets && !error && <div className="proof-loading" role="status">Loading Valeria…</div>}
        {Boolean(error) && <div className="proof-loading is-error" role="alert">{String(error)}</div>}
      </div>

      <footer className="proof-footer">
        <div className="proof-controls" aria-label="Playfield controls">
          <span>
            <button
              aria-label="Move left"
              onPointerDown={() => keys.current.add("arrowleft")}
              onPointerUp={() => keys.current.delete("arrowleft")}
              onPointerLeave={() => keys.current.delete("arrowleft")}
            >
              ←
            </button>
            <button
              aria-label="Move right"
              onPointerDown={() => keys.current.add("arrowright")}
              onPointerUp={() => keys.current.delete("arrowright")}
              onPointerLeave={() => keys.current.delete("arrowright")}
            >
              →
            </button>
            move
          </span>
          <span><button onClick={jump}>Jump</button><kbd>Space</kbd></span>
          <span><button onClick={slide}>Slide</button><kbd>S</kbd></span>
          <span><button onClick={attack}>Attack</button><kbd>J</kbd></span>
        </div>
        <details className="proof-evidence">
          <summary>Evidence</summary>
          <div>
            <dl>
              <dt>Direct request</dt>
              <dd>{assets ? `${assets.manifest.direct_muse.poses} poses · ${assets.manifest.direct_muse.grid.join(" × ")} sheet` : "…"}</dd>
              <dt>Direct alpha</dt>
              <dd>{assets ? (assets.manifest.direct_muse.alpha ? "native alpha" : "none · opaque RGB") : "…"}</dd>
              <dt>Direct cost</dt>
              <dd>{assets ? `$${assets.manifest.direct_muse.incurred_usd.toFixed(2)} · ${assets.manifest.direct_muse.model}` : "…"}</dd>
              <dt>Refined frames</dt>
              <dd>{assets ? `${assets.manifest.framework.registered_poses} registered poses` : "…"}</dd>
              <dt>Run clock</dt>
              <dd>{assets ? `${assets.manifest.framework.run_keys} keys · authored holds` : "…"}</dd>
              <dt>Refined alpha</dt>
              <dd>{assets ? (assets.manifest.framework.alpha ? "native RGBA" : "none") : "…"}</dd>
            </dl>
            <p>
              The control is one provider sheet. The refined view is the validated Castlevania
              atlas with one standing authority, native registration and a complete movement
              state machine. This is a delivery comparison, not a claim of measured aesthetic superiority.
            </p>
          </div>
        </details>
      </footer>
    </section>
  );
}
