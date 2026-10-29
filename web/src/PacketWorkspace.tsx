import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type {
  EligibilityDto,
  EvalResultDto,
  IssueDetailDto,
  ReferencesDto,
} from "./api-types";
import { Film, FilmDock, useFilm } from "./Film";
import { Modal } from "./Modal";
import {
  actionName,
  boundLabel,
  frameIssues,
  packetId,
  revisionId,
  scopeSlot,
  valueLabel,
} from "./review-model";
import type { Bundle } from "./review-model";
import { Err, Icon, nav, useLoad, usePreload, words } from "./shared";
import { tickOfSlot, totalTicks, toNative } from "./playback";
import { usePresentationClock } from "./useClock";

type Tab = "film" | "evidence" | "correction" | "decision" | "tasks";
type Roi = [number, number, number, number];
export function PacketWorkspace({
  bundle: b,
  refs,
  issues,
  bundles,
  reviewer,
  onRefresh,
  onPair,
}: {
  bundle: Bundle;
  refs: ReferencesDto;
  issues: IssueDetailDto[];
  bundles: Bundle[];
  reviewer: string | null;
  onRefresh: () => void;
  onPair: () => void;
}) {
  const id = packetId(b),
    revision = revisionId(b),
    controls = useFilm();
  const timing = b.contract.timing as {
      holds?: number[];
      ticks_per_second?: number;
    },
    canvas = b.contract.canvas as { width?: number; height?: number };
  const holds = useMemo(() => b.frames.map((f) => f.hold_ticks), [b.frames]),
    width = canvas.width || 64,
    height = canvas.height || 64;
  const clock = usePresentationClock({
    holds,
    tps: timing.ticks_per_second || 60,
    loop: Boolean((b.contract.action as { loop?: boolean }).loop),
    resetKey: id,
    autoPlay: false,
  });
  useEffect(() => {
    clock.setPlaying(false);
    const finding = b.evaluation.results.find(
      (c) =>
        ["fail", "error", "unmeasured"].includes(c.outcome) &&
        scopeSlot(c) !== null,
    );
    const slot = finding ? scopeSlot(finding)! : 0;
    clock.selectSlot(slot);
    setSelected([slot]);
    anchor.current = slot;
  }, [id]);
  const [compare, setCompare] = useState<"reference" | "baseline">("reference");
  const base =
    typeof b.packet.comparison_revision_id === "string"
      ? b.packet.comparison_revision_id
      : "";
  const comparison = useLoad("comparison-" + id, () =>
    base ? api.compare(base, revision) : Promise.resolve(null),
  );
  const [tab, setTab] = useState<Tab | null>(null),
    [selected, setSelected] = useState([0]),
    [issueId, setIssueId] = useState<string | null>(null);
  const anchor = useRef(0);
  const [range, setRange] = useState("0-" + (holds[0] - 1)),
    [category, setCategory] = useState("torso-pulse"),
    [note, setNote] = useState(""),
    [roi, setRoi] = useState<Roi | null>(null);
  const [error, setError] = useState<unknown>(null),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false),
    [eligibility, setEligibility] = useState<EligibilityDto | null>(null);
  const submitting = useRef(false),
    operation = useRef("issue-" + crypto.randomUUID()),
    stage = useRef<HTMLCanvasElement>(null),
    drag = useRef<{ x: number; y: number; pointer: number } | null>(null);
  const phaseRefs =
    (b.contract.phase_schedule as {
      slot: number;
      motion_reference_id: string;
    }[]) || [];
  const sourceKinds = [
    ...new Set(
      b.frames.map((f) =>
        String(
          refs.assets.find((a) => a.id === f.asset_id)?.source_kind ||
            "unknown",
        ),
      ),
    ),
  ];
  const contractRefs = b.contract.references as {
    identity?: string;
    style?: string;
    motion_guide_revision?: string;
  };
  const guide = refs.motion_guides.find(
    (g) => g.id === contractRefs?.motion_guide_revision,
  );
  const referenceUrls = b.frames.map((f, i) => {
    const asset = phaseRefs.find((p) => p.slot === i)?.motion_reference_id;
    return asset ? api.assetUrl(asset) : "";
  });
  const urls = b.frames.map((f) => f.asset_url);
  const media = usePreload(urls);
  const current = b.frames[clock.slot] || b.frames[0];
  const selectedFirst = Math.min(...selected),
    selectedLast = Math.max(...selected);
  const overlapping = frameIssues(
    issues,
    b,
    tickOfSlot(holds, clock.slot),
    tickOfSlot(holds, clock.slot) + holds[clock.slot] - 1,
  );
  const activeIssue = issues.find((i) => i.event_id === issueId);
  const open = (next: Tab, index = clock.slot, exact = false) => {
    clock.setPlaying(false);
    clock.selectSlot(index);
    setTab(next);
    setError(null);
    setMessage("");
    if (next === "correction") {
      const useRange = !exact && selected.includes(index);
      setRange(
        `${tickOfSlot(holds, useRange ? selectedFirst : index)}-${tickOfSlot(holds, useRange ? selectedLast : index) + holds[useRange ? selectedLast : index] - 1}`,
      );
      setRoi(null);
      setNote("");
      setIssueId(null);
      operation.current = "issue-" + crypto.randomUUID();
    }
  };
  const focus = (i: number, shift = false) => {
    clock.setPlaying(false);
    clock.selectSlot(i);
    if (!shift) anchor.current = i;
    setSelected(
      shift
        ? Array.from(
            { length: Math.abs(anchor.current - i) + 1 },
            (_, offset) => Math.min(anchor.current, i) + offset,
          )
        : [i],
    );
    controls.film.current?.reveal(i);
  };
  useEffect(() => {
    if (clock.playing) controls.film.current?.reveal(clock.slot);
  }, [clock.slot, clock.playing]);
  useEffect(() => {
    const keyboard = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest("dialog,input,textarea,select,button,[role=region]"))
        return;
      if (e.code === "Space") {
        e.preventDefault();
        clock.setPlaying(!clock.playing);
      }
      if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
        e.preventDefault();
        focus(
          e.key === "Home"
            ? 0
            : e.key === "End"
              ? holds.length - 1
              : Math.max(
                  0,
                  Math.min(
                    holds.length - 1,
                    clock.slot + (e.key === "ArrowRight" ? 1 : -1),
                  ),
                ),
          e.shiftKey,
        );
      }
    };
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  });
  useEffect(() => {
    let live = true;
    api
      .eligibility(revision)
      .then((e) => {
        if (live) setEligibility(e);
      })
      .catch((e) => {
        if (live) setError(e);
      });
    return () => {
      live = false;
    };
  }, [b]);
  useEffect(() => {
    const ctx = stage.current?.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, width, height);
    const image = media.imgs.get(current?.asset_url);
    if (image) {
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(image, 0, 0, width, height);
    }
    if (roi) {
      ctx.strokeStyle = "#eac19b";
      ctx.lineWidth = Math.max(1, width / 128);
      ctx.strokeRect(
        roi[0] + 0.5,
        roi[1] + 0.5,
        roi[2] - roi[0],
        roi[3] - roi[1],
      );
    }
  }, [current, media.imgs, roi, tab, width, height]);
  const region = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (tab !== "correction" || (e.button !== 0 && e.type === "pointerdown"))
      return;
    const box = e.currentTarget.getBoundingClientRect(),
      p = toNative(e.clientX, e.clientY, box, width, height, {
        scaleX: box.width / width,
        scaleY: box.height / height,
        offsetX: 0,
        offsetY: 0,
        mirrored: false,
      });
    if (e.type === "pointerdown") {
      clock.setPlaying(false);
      e.currentTarget.setPointerCapture(e.pointerId);
      drag.current = { x: p.x, y: p.y, pointer: e.pointerId };
    } else if (drag.current?.pointer === e.pointerId) {
      const d = drag.current;
      if (Math.abs(d.x - p.x) >= 1 && Math.abs(d.y - p.y) >= 1)
        setRoi([
          Math.floor(Math.min(d.x, p.x)),
          Math.floor(Math.min(d.y, p.y)),
          Math.ceil(Math.max(d.x, p.x)),
          Math.ceil(Math.max(d.y, p.y)),
        ]);
      if (e.type === "pointerup") {
        drag.current = null;
        e.currentTarget.releasePointerCapture(e.pointerId);
      }
    }
  };
  const perform = async (fn: () => Promise<unknown>, success: string) => {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError(null);
    setMessage("");
    try {
      await fn();
      setMessage(success);
      onRefresh();
    } catch (e) {
      setError(e);
    } finally {
      submitting.current = false;
      setBusy(false);
    }
  };
  const sendIssue = () => {
    const match = /^(\d+)\s*-\s*(\d+)$/.exec(range.trim());
    if (
      !match ||
      Number(match[1]) > Number(match[2]) ||
      Number(match[2]) >= totalTicks(holds)
    ) {
      setError(
        new Error(
          `Use an inclusive tick range within 0–${totalTicks(holds) - 1}.`,
        ),
      );
      return;
    }
    perform(async () => {
      const result = await api.markIssue({
        id: operation.current,
        clip_revision_id: revision,
        packet_id: id,
        frame_instance_id: current.frame_instance_id,
        frame_range: [Number(match[1]), Number(match[2])],
        roi: roi
          ? { left: roi[0], top: roi[1], right: roi[2], bottom: roi[3] }
          : null,
        note: note.trim(),
        category,
      });
      setIssueId(null);
      operation.current = "issue-" + crypto.randomUUID();
      setNote("");
      return result;
    }, "Correction task recorded.");
  };
  const decide = (action: "approve" | "reject" | "needs_changes") =>
    perform(
      () =>
        api.decide({
          id: "decision-" + crypto.randomUUID(),
          action,
          clip_revision_id: revision,
          packet_id: id,
          expected_revision_id: revision,
          expected_evaluation_id: b.evaluation.id,
          note: note.trim(),
        }),
      `${words(action)} recorded for ${revision}.`,
    );
  const baselineReady =
    comparison.data?.same_contract && comparison.data.timing_equal;
  const rowFrames =
    compare === "baseline" && baselineReady
      ? comparison.data!.base.frames.map((f) => f.asset_url)
      : referenceUrls;
  const checks = [...b.evaluation.results].sort(
    (a, z) =>
      Number(["pass", "not_applicable"].includes(a.outcome)) -
      Number(["pass", "not_applicable"].includes(z.outcome)),
  );
  return (
    <>
      <div className="sequence-context">
        <h1
          id="packet-title"
          data-packet-id={id}
          data-revision-id={revision}
          data-evaluation-id={b.evaluation.id}
        >
          {actionName(b)} <span>{revision}</span>
        </h1>
        <div className="sequence-status">
          <span className={"status " + b.evaluation.technical_status}>
            Technical {words(b.evaluation.technical_status)}
          </span>
          <span>{words(b.evaluation.coverage_status)} coverage</span>
          <span>
            Review {words(b.current_decision.acceptance || "unreviewed")}
          </span>
          <span className="origin-label">
            {String((b.contract as { origin?: string }).origin || "")}
          </span>
        </div>
        <select
          aria-label="Compare candidate with"
          value={compare}
          onChange={(e) => setCompare(e.target.value as typeof compare)}
        >
          <option value="reference">Phase reference</option>
          {base && (
            <option value="baseline" disabled={!baselineReady}>
              Baseline
              {comparison.data && !baselineReady ? " · timing differs" : ""}
            </option>
          )}
        </select>
        {base && comparison.data && !baselineReady && (
          <button
            onClick={() => nav({ name: "compare", base, other: revision })}
          >
            Compare timing
          </button>
        )}
      </div>
      <Err e={comparison.err} />
      <Film
        ref={controls.film}
        filmKey={"packet-" + id}
        count={b.frames.length}
        sequence
        labels={[
          compare === "baseline" && baselineReady ? "Baseline" : "Reference",
          "Candidate",
        ]}
        selected={clock.slot}
        onStep={focus}
        onZoom={controls.setZoom}
        onPosition={controls.setPosition}
      >
        <div className="reel-ruler">
          {b.frames.map((f, i) => (
            <button
              key={i}
              aria-label={`Frame ${i + 1}`}
              aria-pressed={selected.includes(i)}
              onClick={(e) => focus(i, e.shiftKey)}
            >
              {String(i + 1).padStart(2, "0")}
            </button>
          ))}
        </div>
        {[rowFrames, urls].map((row, lane) => (
          <div
            className={
              "reel-stock reel-lane " + (lane ? "candidate" : "reference")
            }
            key={lane}
          >
            <div className="reel-shot-row">
              {row.map((url, i) => {
                const first = tickOfSlot(holds, i),
                  last = first + holds[i] - 1,
                  attached = frameIssues(issues, b, first, last);
                const scoped = b.evaluation.results.filter(
                  (c) => scopeSlot(c) === i,
                );
                const metrics = scoped
                  .filter(
                    (c) =>
                      c.observed_value != null ||
                      ["unmeasured", "error"].includes(c.outcome),
                  )
                  .sort(
                    (a, z) =>
                      Number(z.constraint_id.includes("silhouette")) -
                      Number(a.constraint_id.includes("silhouette")),
                  )
                  .slice(0, 2);
                const attention = scoped.find((c) =>
                  ["fail", "error", "unmeasured"].includes(c.outcome),
                );
                return (
                  <div className="reel-frame-unit" key={i}>
                    <button
                      className={
                        "reel-frame " + (clock.slot === i ? "is-current" : "")
                      }
                      aria-label={`${lane ? "Candidate" : "Reference"}, frame ${i + 1}`}
                      aria-pressed={selected.includes(i)}
                      onClick={(e) => focus(i, e.shiftKey)}
                      onDoubleClick={() => open("film", i)}
                    >
                      <span className="frame-aperture">
                        {url ? (
                          <img
                            draggable={false}
                            id={
                              lane && clock.slot === i ? "frame-img" : undefined
                            }
                            src={url}
                            alt={`${lane ? "Candidate" : "Reference"} frame ${i + 1}`}
                          />
                        ) : (
                          <span className="missing-reference">
                            Reference unavailable
                          </span>
                        )}
                        {lane === 1 && <span className="frame-focus-mark" />}
                      </span>
                    </button>
                    {lane === 1 && (
                      <div
                        className="frame-evidence"
                        aria-label={`Frame ${i + 1} evidence and corrections`}
                      >
                        {metrics.length ? (
                          metrics.map((m, n) => (
                            <button
                              key={n}
                              className={"frame-measure " + m.outcome}
                              aria-label={`${words(m.constraint_id)}, frame ${i + 1}: ${valueLabel(m)}`}
                              title={m.reason}
                              onClick={() => {
                                focus(i);
                                open("evidence", i);
                              }}
                            >
                              <span>
                                {words(
                                  m.constraint_id.replace("silhouette-", ""),
                                )}
                              </span>
                              <strong>{valueLabel(m)}</strong>
                              <small>{boundLabel(m)}</small>
                            </button>
                          ))
                        ) : (
                          <span className="frame-no-issues">
                            No measurements recorded
                          </span>
                        )}
                        <div className="frame-corrections">
                          {attached.length ? (
                            <button
                              className={
                                "frame-issue " +
                                (attached[0].task_status === "resolved"
                                  ? "resolved"
                                  : "open")
                              }
                              title={attached
                                .map(
                                  (iss) =>
                                    `${iss.category} · ${iss.task_status} · ${iss.clip_revision_id} · ticks ${iss.frame_range?.join("–") || "all"} · ${iss.note}`,
                                )
                                .join("\n")}
                              onClick={() => {
                                focus(i);
                                setIssueId(attached[0].event_id);
                                open("tasks", i);
                              }}
                            >
                              <span className="issue-dot" />
                              <span>
                                <strong>
                                  {attached.length > 1
                                    ? `${attached.length} corrections`
                                    : words(attached[0].category)}
                                </strong>
                                <small>
                                  {words(attached[0].task_status || "open")}
                                  {attached[0].clip_revision_id !== revision
                                    ? " · " + attached[0].clip_revision_id
                                    : ""}
                                </small>
                                <span className="correction-note">
                                  {attached[0].note}
                                </span>
                              </span>
                            </button>
                          ) : attention ? (
                            <button
                              className="frame-unknown"
                              title={attention.reason}
                              onClick={() => {
                                focus(i);
                                open("evidence", i);
                              }}
                            >
                              {words(attention.constraint_id)}
                              <span>{words(attention.outcome)}</span>
                            </button>
                          ) : (
                            <span className="frame-no-issues">
                              Corrections <span>0</span>
                            </span>
                          )}
                          <button
                            className="frame-add-correction"
                            aria-label={`Request correction for frame ${i + 1}`}
                            onClick={() => {
                              focus(i);
                              open("correction", i, true);
                            }}
                          >
                            <Icon name="plus" />
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </Film>
      <FilmDock
        controls={controls}
        index={clock.slot}
        count={b.frames.length}
        onSelect={focus}
        caption={
          <>
            <strong>
              {selected.length > 1
                ? `${selected.length} frames`
                : words(current.phase)}
            </strong>
            <span>
              {tickOfSlot(holds, selectedFirst)}–
              {tickOfSlot(holds, selectedLast) + holds[selectedLast] - 1} ticks
            </span>
          </>
        }
      >
        <button
          className="reel-icon"
          aria-label={clock.playing ? "Pause" : "Play"}
          onClick={() => {
            if (!clock.playing) open("film");
            clock.setPlaying(!clock.playing);
          }}
        >
          <Icon name={clock.playing ? "pause" : "play"} />
        </button>
        <button className="reel-secondary" onClick={() => open("evidence")}>
          Evidence
        </button>
        <button
          className="reel-secondary correction-action"
          aria-label="Request correction"
          onClick={() => open("correction")}
        >
          <Icon name="plus" />
          <span>Correction</span>
        </button>
        <button className="reel-primary" onClick={() => open("decision")}>
          Decision
          <Icon name="check" />
        </button>
      </FilmDock>
      {tab && (
        <Modal
          wide
          onKeyDown={(e) => {
            const target = e.target as HTMLElement;
            if (target.matches("input,textarea,select")) return;
            if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
              e.preventDefault();
              clock.setPlaying(false);
              if (e.key === "Home") clock.selectTick(0);
              else if (e.key === "End") clock.selectTick(totalTicks(holds) - 1);
              else clock.stepTick(e.key === "ArrowRight" ? 1 : -1);
            }
            if (e.code === "Space" && target.tagName !== "BUTTON") {
              e.preventDefault();
              clock.setPlaying(!clock.playing);
            }
          }}
          title={`${actionName(b)} / ${revision}`}
          onClose={() => {
            setTab(null);
            drag.current = null;
          }}
        >
          <nav className="inspector-tabs" aria-label="Review details">
            {(
              ["film", "evidence", "correction", "tasks", "decision"] as Tab[]
            ).map((t) => (
              <button
                key={t}
                aria-current={tab === t ? "page" : undefined}
                onClick={() => {
                  if (t === "correction" && tab !== "correction")
                    open("correction");
                  else setTab(t);
                  setError(null);
                }}
              >
                {t === "tasks" ? "Corrections" : words(t)}
              </button>
            ))}
          </nav>
          <div className="inspector-body">
            {(tab === "film" || tab === "correction") && (
              <div
                className={
                  tab === "correction" ? "correction-layout" : "preview-layout"
                }
              >
                <div className="preview-stage">
                  <canvas
                    ref={stage}
                    width={width}
                    height={height}
                    aria-label="Candidate frame; drag to mark region"
                    style={{
                      aspectRatio: `${width}/${height}`,
                      cursor: tab === "correction" ? "crosshair" : "default",
                    }}
                    onPointerDown={region}
                    onPointerMove={region}
                    onPointerUp={region}
                    onPointerCancel={() => {
                      drag.current = null;
                    }}
                  />
                  <div className="playback-controls">
                    <button
                      aria-label={clock.playing ? "Pause" : "Play"}
                      onClick={() => clock.setPlaying(!clock.playing)}
                    >
                      <Icon name={clock.playing ? "pause" : "play"} />
                    </button>
                    <button
                      onClick={() => {
                        clock.setPlaying(false);
                        clock.stepTick(-1);
                      }}
                    >
                      −1 tick
                    </button>
                    <button
                      onClick={() => {
                        clock.setPlaying(false);
                        clock.stepTick(1);
                      }}
                    >
                      +1 tick
                    </button>
                    <label>
                      Speed
                      <input
                        type="number"
                        min=".1"
                        max="4"
                        step=".1"
                        value={clock.speed}
                        onChange={(e) =>
                          clock.setSpeed(Number(e.target.value) || 1)
                        }
                      />
                      ×
                    </label>
                  </div>
                  <input
                    aria-label="Authored tick"
                    type="range"
                    min="0"
                    max={totalTicks(holds) - 1}
                    value={clock.tick}
                    onChange={(e) => {
                      clock.setPlaying(false);
                      clock.selectTick(Number(e.target.value));
                    }}
                  />
                  <p id="tick-readout">
                    tick {clock.tick} / {totalTicks(holds)} · frame{" "}
                    {clock.slot + 1} · {words(current.phase)} · hold{" "}
                    {current.hold_ticks}
                  </p>
                  {media.errors.has(current.asset_url) && (
                    <p className="error" role="alert">
                      {media.errors.get(current.asset_url)}
                    </p>
                  )}
                  {base && tab === "film" && (
                    <button
                      className="pixel-compare-link"
                      onClick={() =>
                        nav({ name: "compare", base, other: revision })
                      }
                    >
                      Pixel comparison
                      <Icon name="right" />
                    </button>
                  )}
                </div>
                {tab === "correction" && (
                  <form
                    className="form-stack"
                    onSubmit={(e) => {
                      e.preventDefault();
                      sendIssue();
                    }}
                  >
                    <label>
                      Category
                      <input
                        value={category}
                        onChange={(e) => setCategory(e.target.value)}
                        required
                      />
                    </label>
                    <label>
                      Tick range
                      <input
                        aria-label="Frame range"
                        value={range}
                        onChange={(e) => setRange(e.target.value)}
                        required
                      />
                    </label>
                    <div className="region-summary">
                      <span>
                        Region {roi ? roi.join(", ") + " px" : "Whole frame"}
                      </span>
                      <button type="button" onClick={() => setRoi(null)}>
                        Clear
                      </button>
                    </div>
                    <p className="muted">
                      Drag on the frame to mark native pixels.
                    </p>
                    <label>
                      Note
                      <textarea
                        value={note}
                        onChange={(e) => setNote(e.target.value)}
                        required
                        rows={4}
                      />
                    </label>
                    <button
                      className="primary"
                      disabled={!reviewer || busy || !note.trim()}
                    >
                      {busy ? "Recording…" : "Send to model"}
                      <Icon name="right" />
                    </button>
                  </form>
                )}
              </div>
            )}
            {tab === "evidence" && (
              <>
                <div className="reference-line">
                  {[
                    ["Identity", contractRefs?.identity],
                    ["Style", contractRefs?.style],
                    [
                      "Phase",
                      phaseRefs.find((p) => p.slot === clock.slot)
                        ?.motion_reference_id,
                    ],
                    [
                      "Editable",
                      guide?.entries.find((e) => e.phase === current.phase)
                        ?.editable_mask_asset_id,
                    ],
                    [
                      "Protected",
                      guide?.entries.find((e) => e.phase === current.phase)
                        ?.protected_mask_asset_id,
                    ],
                  ]
                    .filter(([, asset]) => Boolean(asset))
                    .map(([name, asset]) => (
                      <figure key={name}>
                        {asset && <img src={api.assetUrl(asset)} alt={name || undefined} />}
                        <figcaption>{name}</figcaption>
                      </figure>
                    ))}
                  <div>
                    <strong>
                      {words(b.evaluation.coverage_status)} coverage
                    </strong>
                    <p className="muted">
                      {refs.reference_approvals.some(
                        (a) =>
                          a.motion_guide_id === guide?.id &&
                          refs.active_approval_ids.includes(a.id),
                      )
                        ? "Reference authority active"
                        : "Reference authority unavailable"}
                    </p>
                  </div>
                </div>
                <div className="evidence-filters">
                  <strong>Evaluation checks</strong>
                  <span>{checks.length} recorded</span>
                </div>
                {checks.map((c, i) => (
                  <Check
                    key={i}
                    check={c}
                    selected={scopeSlot(c) === clock.slot}
                    onSelect={() => {
                      const slot = scopeSlot(c);
                      if (slot !== null) focus(slot);
                    }}
                  />
                ))}
                <details className="provenance">
                  <summary>Evaluation provenance</summary>
                  <dl className="facts">
                    <dt>Media source</dt>
                    <dd>{sourceKinds.join(", ")}</dd>
                    <dt>Native canvas</dt>
                    <dd>
                      {width} × {height} px · {timing.ticks_per_second || 60}{" "}
                      ticks/s
                    </dd>
                    <dt>Packet</dt>
                    <dd>{id}</dd>
                    <dt>Revision</dt>
                    <dd>{revision}</dd>
                    <dt>Evaluation</dt>
                    <dd>{b.evaluation.id}</dd>
                    <dt>Evidence digest</dt>
                    <dd>
                      {b.evaluation.evidence_manifest_sha256 || "Unavailable"}
                    </dd>
                  </dl>
                </details>
              </>
            )}
            {tab === "tasks" && (
              <div className="issue-stack">
                {(activeIssue
                  ? [
                      activeIssue,
                      ...overlapping.filter(
                        (i) => i.event_id !== activeIssue.event_id,
                      ),
                    ]
                  : overlapping
                ).map((iss) => (
                  <article className="issue-detail" key={iss.event_id}>
                    <header>
                      <h3>{words(iss.category)}</h3>
                      <span
                        className={
                          "status " +
                          (iss.task_status === "resolved"
                            ? "pass"
                            : "incomplete")
                        }
                      >
                        {words(iss.task_status || "open")}
                      </span>
                    </header>
                    <p>{iss.note}</p>
                    <dl className="facts">
                      <dt>Source revision</dt>
                      <dd>{iss.clip_revision_id}</dd>
                      <dt>Ticks</dt>
                      <dd>{iss.frame_range?.join("–") || "Whole clip"}</dd>
                      <dt>Region</dt>
                      <dd>
                        {iss.roi
                          ? Object.entries(iss.roi)
                              .map(([k, v]) => `${k} ${v}`)
                              .join(" · ")
                          : "Whole frame"}
                      </dd>
                      <dt>Attempts</dt>
                      <dd>
                        {iss.attempts.length
                          ? iss.attempts.map((a) => words(a.result)).join(" · ")
                          : "No attempts"}
                      </dd>
                    </dl>
                    {iss.candidate_revisions.map((candidate) => {
                      const replacement = bundles.find(
                        (p) => revisionId(p) === candidate.revision_id,
                      );
                      return (
                        <div
                          className="replacement-row"
                          key={String(candidate.revision_id)}
                        >
                          <span>
                            {String(candidate.revision_id)} ·{" "}
                            {words(candidate.technical_status)}
                          </span>
                          {replacement && (
                            <>
                              <button
                                onClick={() =>
                                  nav({
                                    name: "packet",
                                    id: packetId(replacement),
                                  })
                                }
                              >
                                Review replacement
                              </button>
                              <button
                                disabled={
                                  !reviewer ||
                                  busy ||
                                  iss.task_status === "resolved"
                                }
                                onClick={() =>
                                  perform(
                                    () =>
                                      api.resolveIssue(iss.event_id, {
                                        replacement_revision_id:
                                          candidate.revision_id,
                                        packet_id: packetId(replacement),
                                        note: "Compared replacement in review desk.",
                                      }),
                                    "Resolved against reviewed replacement.",
                                  )
                                }
                              >
                                Resolve with this
                              </button>
                            </>
                          )}
                        </div>
                      );
                    })}
                    {iss.task_status === "resolved" && (
                      <button
                        disabled={!reviewer || busy}
                        onClick={() =>
                          perform(
                            () =>
                              api.reopenIssue(iss.event_id, {
                                note: "Reopened after visual review.",
                              }),
                            "Reopened correction.",
                          )
                        }
                      >
                        Reopen
                      </button>
                    )}
                  </article>
                ))}
                {!overlapping.length && !activeIssue && (
                  <p className="muted">No corrections on this frame.</p>
                )}
                <button onClick={() => nav({ name: "issues", revision })}>
                  All revision issues
                  <Icon name="right" />
                </button>
              </div>
            )}
            {tab === "decision" && (
              <div className="decision-panel">
                <dl className="facts">
                  <dt>Technical</dt>
                  <dd className={"status " + b.evaluation.technical_status}>
                    {words(b.evaluation.technical_status)}
                  </dd>
                  <dt>Coverage</dt>
                  <dd>{words(b.evaluation.coverage_status)}</dd>
                  <dt>Human review</dt>
                  <dd>
                    {words(b.current_decision.acceptance || "unreviewed")}
                  </dd>
                  <dt>Release eligibility</dt>
                  <dd>
                    {eligibility
                      ? eligibility.eligible
                        ? "Eligible"
                        : "Blocked"
                      : "Loading…"}
                  </dd>
                </dl>
                {eligibility && !eligibility.eligible && (
                  <ul className="release-reasons">
                    {eligibility.reasons.map((r) => (
                      <li key={r}>{words(r)}</li>
                    ))}
                  </ul>
                )}
                <label>
                  Review note
                  <textarea
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    rows={3}
                  />
                </label>
                <div className="decision-actions">
                  <button
                    disabled={!reviewer || busy}
                    onClick={() => decide("reject")}
                  >
                    Reject
                  </button>
                  <button
                    disabled={!reviewer || busy}
                    onClick={() => decide("needs_changes")}
                  >
                    Needs work
                  </button>
                  <button
                    className="primary"
                    disabled={!reviewer || busy}
                    onClick={() => decide("approve")}
                  >
                    Approve
                    <Icon name="check" />
                  </button>
                </div>
                <p className="muted exact-binding">
                  {revision} · {b.evaluation.id}
                </p>
              </div>
            )}
            {!reviewer && ["decision", "correction", "tasks"].includes(tab) && (
              <button
                className="pair-prompt"
                onClick={() => {
                  setTab(null);
                  onPair();
                }}
              >
                Pair a reviewer to record changes
                <Icon name="right" />
              </button>
            )}
            {message && (
              <p role="status" className="success-message">
                {message}
              </p>
            )}
            <Err e={error} />
          </div>
        </Modal>
      )}
    </>
  );
}
function Check({
  check: c,
  selected,
  onSelect,
}: {
  check: EvalResultDto;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      className={"check-row " + c.outcome + (selected ? " current-check" : "")}
      onClick={onSelect}
    >
      <span className="check-name">
        <strong>{words(c.constraint_id)}</strong>
        <small>
          {c.scope} · {words(c.outcome)}
        </small>
      </span>
      <span className="check-value">
        <strong>{valueLabel(c)}</strong>
        <small>{boundLabel(c)}</small>
      </span>
      <p>{c.reason}</p>
    </button>
  );
}
