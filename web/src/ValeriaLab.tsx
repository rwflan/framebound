import { useEffect, useRef, useState } from "react";
import { Icon } from "./shared";
import { startJump, advanceVertical } from "./valeria-motion";
import "./valeria-lab.css";

type StateSpec = {
  frames: number[];
  duration_ticks: number[];
  loop?: boolean;
};

type CostSummary = {
  observed_microdollars: number;
  unreconciled_reserve_microdollars: number;
  unreconciled_operations: number;
  operations: number;
  missing_lineage_roots: number;
  groups: Record<string, { observed_microdollars: number }>;
};
const usd = (amount: number) => new Intl.NumberFormat('en-US', {style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 3}).format(amount / 1_000_000);

type DemoManifest = {
  schema: number;
  canvas: [number, number];
  ground_y?: number;
  render_height?: number;
  source_offsets?: { direct?: [number, number][]; framework?: [number, number][] };
  quality?: { render_fidelity?: {total: number; passed: number}; transition_checks?: {total: number; passed: number}; torso_pairs?: {total: number; passed: number}; status: string; failed_frames: number; temporal_findings: number; regenerated_frames: number; frames_with_failures?: number; unmeasured_frames?: number; visible_review?: {status: string; states: string[]; frames: number} | null };
  actor_bounds?: [number, number, number, number];
  source_dimensions?: [number, number][];
  source_pixel_scales?: { direct: number[]; framework: number[] };
  states: Record<string, StateSpec>;
  frame_count: number;
  revision: string;
  repairs_selected: number;
  comparison: string;
};

type EngineState = "idle" | "run" | "jump" | "apex" | "fall" | "slide" | "whip";
type CompareMode = "compare" | "framework" | "direct";

const TICKS_PER_SECOND = 60;
const ASSET_ROOT = "/demo/valeria-live";

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

function drawArena(
  canvas: HTMLCanvasElement,
  accent: string,
  cameraOffset = 0,
  cameraY = 0,
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

  context.strokeStyle = "#738a8730";
  context.lineWidth = 1;
  for (let x = 24 - ((cameraOffset % 96 + 96) % 96); x < width; x += 96) {
    context.beginPath();
    context.moveTo(x + 0.5, 0);
    context.lineTo(x + 0.5, height);
    context.stroke();
  }
  for (let y = 28 + (cameraY % 96); y < height; y += 96) {
    context.beginPath();
    context.moveTo(0, y + 0.5);
    context.lineTo(width, y + 0.5);
    context.stroke();
  }

  const floor = height - 44 + cameraY;
  context.fillStyle = "#cdbf9f";
  context.fillRect(0, floor, width, height - floor);
  context.strokeStyle = "#9d8a69";
  context.lineWidth = 2;
  context.beginPath();
  context.moveTo(0, floor + 1);
  context.lineTo(width, floor + 1);
  context.stroke();
  context.fillStyle = "#917e6040";
  for (let x = -24 - ((cameraOffset % 48 + 48) % 48); x < width + 40; x += 48) {
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

function drawCharacter(
  canvas: HTMLCanvasElement,
  images: HTMLImageElement[],
  manifest: DemoManifest,
  state: EngineState,
  elapsed: number,
  x: number,
  yOffset: number,
  facing: number,
  pixelScales?: number[],
  offsets?: [number, number][],
) {
  const bounds = manifest.actor_bounds;
  const halfWidth = manifest.canvas[0] / 2;
  const padding = bounds ? Math.ceil(Math.max(halfWidth - bounds[0], bounds[2] - halfWidth)
    * (manifest.render_height ?? 640) / manifest.canvas[1]) + 12 : 180;
  const projectedX = Math.max(padding, Math.min(canvas.width - padding, x));
  const scale = (manifest.render_height ?? 640) / manifest.canvas[1];
  const cameraY = bounds ? Math.max(0, 12 - (canvas.height - 44 + yOffset
    + (bounds[1] - (manifest.ground_y ?? manifest.canvas[1] * .90)) * scale)) : 0;
  const context = drawArena(canvas, "#a99d87", x - projectedX, cameraY);
  if (!context) return;
  const spec = manifest.states[state];
  const index = frameAt(spec, elapsed);
  canvas.dataset.animationState = state;
  canvas.dataset.frameIndex = String(index);
  canvas.dataset.worldY = yOffset.toFixed(2);
  const image = images[index];
  const density = pixelScales?.[index] ?? 1;
  if (!image) return;
  // Shared world camera and native-resolution sources in both lanes.
  const [offsetX, offsetY] = offsets?.[index] ?? [0, 0];
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.save();
  context.translate(projectedX, canvas.height - 44 + yOffset + cameraY);
  context.scale(facing * density, density);
  context.drawImage(image, (-manifest.canvas[0] / 2 + offsetX) * scale, (-(manifest.ground_y ?? manifest.canvas[1] * .90) + offsetY) * scale,
    manifest.canvas[0] * scale, manifest.canvas[1] * scale);
  context.restore();
}

export function ValeriaLab() {
  const [costs, setCosts] = useState<CostSummary | null>(null);
  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const response = await fetch(`${ASSET_ROOT}/costs.json?t=${Date.now()}`, {cache: "no-store"});
        if (response.ok) { const value = await response.json() as CostSummary; if (active) setCosts(value); }
      } catch { /* Retain the last recorded amount; never invent a zero. */ }
    };
    void refresh(); const timer = setInterval(() => void refresh(), 10000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  const [mode, setMode] = useState<CompareMode>("compare");
  const [paused, setPaused] = useState(false);
  const [assets, setAssets] = useState<{
    direct: HTMLImageElement[];
    framework: HTMLImageElement[];
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
    clock: 0,
    slideUntil: 0,
    attackUntil: 0,
  });
  const jump = () => {
    if (startJump(engine.current)) setPaused(false);
  };
  const slide = () => {
    setPaused(false);
    if (engine.current.offsetY < -0.01) return;
    engine.current.slideUntil = engine.current.clock + 0.46;
  };
  const attack = () => {
    setPaused(false);
    engine.current.attackUntil = engine.current.clock + 0.42;
  };

  useEffect(() => {
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    let revision: string | null = null;
    const refresh = async () => {
      try {
        const response = await fetch(`${ASSET_ROOT}/manifest.json?t=${Date.now()}`, { cache: "no-store" });
        if (!response.ok) throw new Error("Animation build is still running");
        const manifest = await response.json() as DemoManifest;
        if (manifest.schema !== 2 || !manifest.frame_count || !manifest.states?.idle || !manifest.states?.run) throw new Error("Animation build is still running");
        if (manifest.revision === revision) { timer = setTimeout(refresh, 10000); return; }
        const [direct, framework] = await Promise.all(["direct", "framework"].map(lane =>
          Promise.all(Array.from({length: manifest.frame_count}, (_, i) =>
            loadImage(`${ASSET_ROOT}/${manifest.revision}/${lane}-${i}.png`)))));
        if (live) { setAssets({direct, framework, manifest}); setError(null); revision = manifest.revision; }
      } catch (reason) {
        if (live) setError(reason);
      }
      if (live) timer = setTimeout(refresh, 10000);
    };
    void refresh();
    return () => { live = false; clearTimeout(timer); };
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
      const wallTime = time / 1000;
      const delta = Math.min(0.04, Math.max(0, wallTime - engine.current.lastTime));
      engine.current.lastTime = wallTime;
      if (!paused) engine.current.clock += delta;
      const now = engine.current.clock;
      if (!paused) {
        const moving =
          keys.current.has("arrowleft") ||
          keys.current.has("a") ||
          keys.current.has("arrowright") ||
          keys.current.has("d");
        if (keys.current.has("arrowleft") || keys.current.has("a")) {
          engine.current.facing = -1;
          engine.current.x -= 224 * delta;
        }
        if (keys.current.has("arrowright") || keys.current.has("d")) {
          engine.current.facing = 1;
          engine.current.x += 224 * delta;
        }
        // The camera follows past the safe projection bounds; long capes and
        // weapons must not reduce how far the character can travel.
        engine.current.x = Math.max(180, Math.min(780, engine.current.x));
        advanceVertical(engine.current, delta);
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

        }
      }
      const elapsed = now - engine.current.stateStarted;
      if (frameworkCanvas.current) drawCharacter(frameworkCanvas.current, assets.framework, assets.manifest,
        engine.current.state, elapsed, engine.current.x, engine.current.offsetY, engine.current.facing, assets.manifest.source_pixel_scales?.framework, assets.manifest.source_offsets?.framework);
      if (directCanvas.current) drawCharacter(directCanvas.current, assets.direct, assets.manifest,
        engine.current.state, elapsed, engine.current.x, engine.current.offsetY, engine.current.facing, assets.manifest.source_pixel_scales?.direct, assets.manifest.source_offsets?.direct);
      if (singleCanvas.current) drawCharacter(singleCanvas.current, mode === "direct" ? assets.direct : assets.framework,
        assets.manifest, engine.current.state, elapsed, engine.current.x * 2, engine.current.offsetY, engine.current.facing,
        mode === "direct" ? assets.manifest.source_pixel_scales?.direct : assets.manifest.source_pixel_scales?.framework,
        mode === "direct" ? assets.manifest.source_offsets?.direct : assets.manifest.source_offsets?.framework);
      request = requestAnimationFrame(paint);
    };
    request = requestAnimationFrame(paint);
    return () => cancelAnimationFrame(request);
  }, [assets, mode, paused]);

  return (
    <section className="valeria-proof" aria-label="Valeria movement proof">
      <div className="proof-toolbar">
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

              </header>
              <canvas ref={directCanvas} width={960} height={720} aria-label="Direct Muse Valeria playfield" />
            </article>
            <article className="proof-lane" data-output="framework">
              <header>
                <span>Framebound</span>
                {assets?.manifest.quality?.status === "refining" && <small>Refining</small>}

              </header>
              <canvas ref={frameworkCanvas} width={960} height={720} aria-label="Framebound Valeria playfield" />
            </article>
          </>
        ) : (
          <article className="proof-lane proof-lane--single" data-output={mode}>
            <header>
              <span>{mode === "direct" ? "Direct Muse" : "Framebound"}</span>

            </header>
            <canvas ref={singleCanvas} width={1920} height={720} aria-label="Valeria playfield" />
          </article>
        )}
        {!assets && <div className="proof-loading" role="status">{error ? "Preparing high-resolution animations…" : "Loading animations…"}</div>}

      </div>

      <footer className="proof-footer">
        <fieldset className="proof-controls" aria-label="Playfield controls" disabled={!assets}>
          <span>
            <button
              aria-label="Move left"
              onPointerDown={() => keys.current.add("arrowleft")}
              onPointerUp={() => keys.current.delete("arrowleft")}
              onPointerLeave={() => keys.current.delete("arrowleft")}
              onPointerCancel={() => keys.current.delete("arrowleft")}
            >
              ←
            </button>
            <button
              aria-label="Move right"
              onPointerDown={() => keys.current.add("arrowright")}
              onPointerUp={() => keys.current.delete("arrowright")}
              onPointerLeave={() => keys.current.delete("arrowright")}
              onPointerCancel={() => keys.current.delete("arrowright")}
            >
              →
            </button>
            move
          </span>
          <span><button onClick={jump}>Jump</button><kbd>Space</kbd></span>
          <span><button onClick={slide}>Slide</button><kbd>S</kbd></span>
          <span><button onClick={attack}>Attack</button><kbd>J</kbd></span>
        </fieldset>
        <span className="proof-cost" title="Provider spend across all retained framework experiments, including failed and superseded attempts. Shared initial generation included; local CPU and external services without receipts are not priced.">{costs ? `Work cost ${usd(costs.observed_microdollars)}${costs.unreconciled_operations ? ` + ${usd(costs.unreconciled_reserve_microdollars)} unreconciled` : ""}${costs.missing_lineage_roots ? " · ledger incomplete" : ""}` : "Cost unavailable"}</span>
        <details className="proof-evidence">
          <summary>Evidence</summary>
          <div>
            <p>Both versions share the initial Muse generation, character references, transparent extraction, canvas and playback timing. Framebound alone assesses and requests repairs.</p>
            {assets && <dl>
              <dt>Frame canvas</dt><dd>{assets.manifest.canvas.join(" × ")} px</dd>
              {assets.manifest.source_dimensions && <><dt>Source images</dt><dd>{assets.manifest.source_dimensions.map(size => size.join(" × ")).join(" / ")} px</dd></>}
              <dt>Frames per version</dt><dd>{assets.manifest.frame_count}</dd>
              <dt>Selected repairs</dt><dd>{assets.manifest.quality?.regenerated_frames ?? assets.manifest.repairs_selected}</dd>
              {assets.manifest.quality && <><dt>Quality gates</dt><dd>{assets.manifest.quality.status === "checks_passed" ? "Checks passed; human approval separate" : `${assets.manifest.quality.frames_with_failures ?? assets.manifest.quality.failed_frames} frames with findings; ${assets.manifest.quality.unmeasured_frames ?? 0} with unmeasured evidence; ${assets.manifest.quality.temporal_findings} transition findings`}</dd></>}
              {Boolean(assets.manifest.quality?.render_fidelity?.total) && <><dt>Original rendering</dt><dd>{assets.manifest.quality!.render_fidelity!.passed} / {assets.manifest.quality!.render_fidelity!.total} frames pass clarity review</dd></>}
              {Boolean(assets.manifest.quality?.transition_checks?.total) && <><dt>Pose transitions</dt><dd>{assets.manifest.quality!.transition_checks!.passed} / {assets.manifest.quality!.transition_checks!.total} checks passed</dd></>}
              {Boolean(assets.manifest.quality?.torso_pairs?.total) && <><dt>Body width</dt><dd>{assets.manifest.quality!.torso_pairs!.passed} / {assets.manifest.quality!.torso_pairs!.total} frame pairs within bounds</dd></>}
              {assets.manifest.quality?.visible_review?.status === "passed" && <><dt>Visible review</dt><dd>{assets.manifest.quality.visible_review.states.join(", ")} · {assets.manifest.quality.visible_review.frames} frames checked for body bulk and item construction</dd></>}
              <dt>Provider cost recorded</dt><dd>{costs ? usd(costs.observed_microdollars) : "Unavailable"}</dd>
              {costs && <><dt>Framework work</dt><dd>{usd(costs.groups.framework_work?.observed_microdollars ?? 0)}</dd><dt>Shared initial work</dt><dd>{usd(costs.groups.shared_initial?.observed_microdollars ?? 0)}</dd><dt>Unreconciled reserve</dt><dd>{usd(costs.unreconciled_reserve_microdollars)} · {costs.unreconciled_operations} calls</dd><dt>Scope</dt><dd>All retained provider calls, including failures and superseded attempts. Local CPU and unrecorded external services are not priced.</dd></>}
              <dt>Assessment</dt><dd>Automated; visual preference remains unproven.</dd>
            </dl>}

          </div>
        </details>
      </footer>
    </section>
  );
}
