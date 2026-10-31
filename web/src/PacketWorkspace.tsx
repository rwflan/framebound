import {FilmPlayback,PlaybackControls,ProjectionHandle} from './FilmPlayback';
import {ViewerExpansion,useViewerExpansion} from './ViewerExpansion';
import { useEffect, useMemo, useRef, useState } from "react";
import type {Stroke} from "./AnnotationPlayer";
import {AnnotationTools,AnnotationSurface,useAnnotations} from "./AnnotationTools";
import { api } from "./api";
import type {
  EligibilityDto,
  EvalResultDto,
  IssueDetailDto,
  ReferencesDto,
} from "./api-types";
import { Film, useFilm } from "./Film";
import { Modal } from "./Modal";
import {
  actionName,
  attentionSlot,
  boundLabel,
  frameIssues,
  packetId,
  revisionId,
  scopeSlot,
  valueLabel,
} from "./review-model";
import type { Bundle } from "./review-model";
import { Err, Icon, nav, useLoad, usePreload, words } from "./shared";
import { slotAtTick, tickOfSlot, totalTicks, toNative } from "./playback";
import { usePresentationClock } from "./useClock";

type Tab = "film" | "evidence" | "correction" | "decision" | "tasks";
type Roi = [number, number, number, number];
export function PacketWorkspace({
  bundle: b,
  refs,
  issues,
  bundles,
  onRefresh,
}: {
  bundle: Bundle;
  refs: ReferencesDto;
  issues: IssueDetailDto[];
  bundles: Bundle[];
  onRefresh: () => void;
}) {
  const projection=useRef<ProjectionHandle>(null);
  const [visual,setVisual]=useState<Stroke[]>([]);
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
  const initialSlot = useRef(attentionSlot(b, issues));
  const [inspectionSlot, setInspectionSlot] = useState(initialSlot.current);
  const [viewMode, setViewMode] = useState<"frames" | "playback">("playback");
  const wasPlaying = useRef(false);
  const clock = usePresentationClock({
    holds,
    tps: timing.ticks_per_second || 60,
    loop: Boolean((b.contract.action as { loop?: boolean }).loop),
    resetKey: id,
    autoPlay: false,
    initialTick: tickOfSlot(holds, initialSlot.current),
  });
  const [compare, setCompare] = useState<"reference" | "baseline">("reference");
  const base =
    typeof b.packet.comparison_revision_id === "string"
      ? b.packet.comparison_revision_id
      : "";
  const comparison = useLoad("comparison-" + id, () =>
    base ? api.compare(base, revision) : Promise.resolve(null),
  );
  const [tab, setTab] = useState<Tab | null>(null),
    [selected, setSelected] = useState([initialSlot.current]),
    [issueId, setIssueId] = useState<string | null>(null);
  const anchor = useRef(initialSlot.current);
  const expansion=useViewerExpansion(()=>clock.setPlaying(false)),expanded=expansion.expanded;
  const [referenceAsset, setReferenceAsset] = useState<{
    label: string;
    id: string;
  } | null>(null);
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
  const baselineReady =
    comparison.data?.same_contract && comparison.data.timing_equal;
  const rowFrames =
    compare === "baseline" && baselineReady
      ? comparison.data!.base.frames.map((f) => f.asset_url)
      : referenceUrls;
  const playbackUrls = [...urls, ...rowFrames.filter(Boolean)];
  const media = usePreload(playbackUrls);
  const candidateReady = urls.every((url) => media.imgs.has(url));
  const playbackReady =
    candidateReady &&
    playbackUrls.every((url) => media.imgs.has(url) || media.errors.has(url));
  const current = b.frames[inspectionSlot] || b.frames[0];
  const playingFrame = b.frames[clock.slot] || b.frames[0];
  const stageFrame = tab === "film" ? playingFrame : current;
  const displaySlot = viewMode === "playback" ? clock.slot : inspectionSlot;
  const selectedFirst = Math.min(...selected),
    selectedLast = Math.max(...selected);
  const overlapping = frameIssues(
    issues,
    b,
    tickOfSlot(holds, inspectionSlot),
    tickOfSlot(holds, inspectionSlot) + holds[inspectionSlot] - 1,
  );
  const activeIssue = issues.find((i) => i.event_id === issueId);
  const open = (next: Tab, index = inspectionSlot, exact = false) => {
    wasPlaying.current = false;
    clock.setPlaying(false);
    clock.selectSlot(index);
    setInspectionSlot(index);
    if (!selected.includes(index)) {
      setSelected([index]);
      anchor.current = index;
    }
    if (next !== "evidence") {
      setViewMode("playback");
      controls.film.current?.reveal(index, true);
    }
    setTab(next);
    setError(null);
    setMessage("");
    if (next === "correction") {
      const useRange = !exact && selected.includes(index);
      setRange(
        `${tickOfSlot(holds, useRange ? selectedFirst : index)}-${tickOfSlot(holds, useRange ? selectedLast : index) + holds[useRange ? selectedLast : index] - 1}`,
      );
      setRoi(null);
      setNote("");setVisual([]);
      setIssueId(null);
      operation.current = "issue-" + crypto.randomUUID();
    }
  };
  const focus = (i: number, shift = false, reveal = true) => {
    wasPlaying.current = false;
    clock.setPlaying(false);
    clock.selectSlot(i);
    setInspectionSlot(i);
    if (!shift) anchor.current = i;
    setSelected(
      shift
        ? Array.from(
            { length: Math.abs(anchor.current - i) + 1 },
            (_, offset) => Math.min(anchor.current, i) + offset,
          )
        : [i],
    );
    if(reveal)controls.film.current?.reveal(i, true);
  };
  const adoptSlot = (slot: number) => {
    setInspectionSlot(slot);
    setSelected([slot]);
    anchor.current = slot;
  };
  const inspectTick = (tick: number) => {
    const exact = Math.max(0, Math.min(totalTicks(holds) - 1, tick));
    wasPlaying.current = false;
    clock.setPlaying(false);
    clock.selectTick(exact);
    adoptSlot(slotAtTick(holds, exact, false));
  };
  const pausePlayback = () => {
    wasPlaying.current = false;
    clock.setPlaying(false);
    adoptSlot(clock.slot);
  };
  const togglePlayback = (surface: "main" | "modal" = "main") => {
    if (clock.playing) {
      pausePlayback();
      return;
    }
    if (!(surface === "main" ? playbackReady : candidateReady)) return;
    if (surface === "main") setViewMode("playback");
    if (
      !Boolean((b.contract.action as { loop?: boolean }).loop) &&
      clock.tick >= totalTicks(holds) - 1
    )
      clock.selectTick(0);
    clock.setPlaying(true);
  };
  const returnToFilm = () => {
    pausePlayback();
    setViewMode("playback");
    controls.film.current?.reveal(clock.slot, true);
  };
  const annotations=useAnnotations({value:visual,onChange:setVisual,slot:inspectionSlot,onSlot:focus,pause:pausePlayback,onDraw:()=>{returnToFilm();setTab('correction');},resetKey:id,fit:()=>projection.current?.fit()});
  useEffect(() => {
    // Inspection follows deliberate pauses/one-shot completion, never a running playhead.
    if (
      wasPlaying.current &&
      !clock.playing &&
      (tab === "film" ||
        (viewMode === "playback" && (!tab || tab === "evidence")))
    )
      adoptSlot(clock.slot);
    wasPlaying.current = clock.playing;
  }, [clock.playing]);
  useEffect(() => {
    const keyboard = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (
        e.defaultPrevented ||
        (target.closest("dialog,input,textarea,select")||(target.closest("button")&&!target.closest(".reel-camera,.film-projector")))
      )
        return;
      if (e.code === "Space") {
        e.preventDefault();
        togglePlayback();
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
                    (clock.playing?clock.slot:inspectionSlot) + (e.key === "ArrowRight" ? 1 : -1),
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
    const image = media.imgs.get(stageFrame?.asset_url);
    if (image) {
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(image, 0, 0, width, height);
    }
    if (roi) {
      ctx.strokeStyle = "#e95725";
      ctx.lineWidth = Math.max(1, width / 128);
      ctx.strokeRect(
        roi[0] + 0.5,
        roi[1] + 0.5,
        roi[2] - roi[0],
        roi[3] - roi[1],
      );
    }
  }, [stageFrame, media.imgs, roi, tab, width, height]);
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
      wasPlaying.current = false;
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
        note: note.trim(),visual_annotations:visual,
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
  const checks = [...b.evaluation.results].sort(
    (a, z) =>
      Number(["pass", "not_applicable"].includes(a.outcome)) -
      Number(["pass", "not_applicable"].includes(z.outcome)),
  );
  const evidencePanel = (
    <>
      <div className="reference-line">
        {[
          ["Identity", contractRefs?.identity],
          ["Style", contractRefs?.style],
          [
            "Phase",
            phaseRefs.find((p) => p.slot === inspectionSlot)
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
              {asset && (
                <img src={api.assetUrl(asset)} alt={name || undefined} />
              )}
              <figcaption>{name}</figcaption>
            </figure>
          ))}
        <div>
          <strong>{words(b.evaluation.coverage_status)} coverage</strong>
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
          selected={scopeSlot(c) === inspectionSlot}
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
            {width} × {height} px · {timing.ticks_per_second || 60} ticks/s
          </dd>
          <dt>Packet</dt>
          <dd>{id}</dd>
          <dt>Revision</dt>
          <dd>{revision}</dd>
          <dt>Evaluation</dt>
          <dd>{b.evaluation.id}</dd>
          <dt>Evidence digest</dt>
          <dd>{b.evaluation.evidence_manifest_sha256 || "Unavailable"}</dd>
        </dl>
      </details>
    </>
  );
  return (
    <>
      <div className={"packet-workspace" + (expanded ? " expanded-film" : "")}>
        <section className="film-window">
          <header className="pane-title viewer-title">
            <span className="file-icon">
              <Icon name="film" />
            </span>
            <h1
              id="packet-title"
              data-packet-id={id}
              data-revision-id={revision}
              data-evaluation-id={b.evaluation.id}
            >
              {actionName(b)}{" "}
              <small>{revision.match(/r\d+$/i)?.[0] || revision}</small>
              <span className="sr-only"> {revision}</span>
            </h1>
            <div className="title-grip" aria-hidden="true" />
            <div className="sequence-status">
              <span className={"badge " + b.evaluation.technical_status}>
                Technical {words(b.evaluation.technical_status)}
              </span>
              <span
                className={
                  "badge coverage " +
                  (b.evaluation.coverage_status === "complete"
                    ? ""
                    : "incomplete")
                }
              >
                {words(b.evaluation.coverage_status)} coverage
              </span>
              <span className="sr-only">
                {words(b.current_decision.acceptance || "unreviewed")}
              </span>
            </div>
            <ViewerExpansion expanded={expanded} onToggle={expansion.toggle} onFeedback={()=>{setTab('correction');expansion.showFeedback();}}/>
          </header>
          <div className="viewer-toolbar">
            <select
              aria-label="Compare candidate with"
              value={compare}
              onChange={(e) => {
                pausePlayback();
                setCompare(e.target.value as typeof compare);
              }}
            >
              <option value="reference">Phase reference</option>
              {base && (
                <option value="baseline" disabled={!baselineReady}>
                  Previous revision
                  {comparison.data && !baselineReady ? " · timing differs" : ""}
                </option>
              )}
            </select>
            {base && comparison.data && !baselineReady && (
              <button
                className="text-button"
                onClick={() => nav({ name: "compare", base, other: revision })}
              >
                Compare timing
              </button>
            )}

          </div>
          <AnnotationTools controls={annotations}/>
          <Err e={comparison.err} />
          <div
            className={
              "film-stage"
            }
            data-view-mode={viewMode}
          >
            <Film
              ref={controls.film}
              filmKey={"packet-" + id}
              count={b.frames.length}
              sequence
              labels={[
                compare === "baseline" && baselineReady
                  ? "Previous"
                  : "Reference",
                "Candidate",
                "Checks",
              ]}
              selected={inspectionSlot}
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
                    <small>
                      {tickOfSlot(holds, i)}–
                      {tickOfSlot(holds, i) + f.hold_ticks - 1}
                    </small>
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
                    {row.map((url, i) => (
                      <div className="reel-frame-unit" key={i}>
                        <button
                          className={
                            "reel-frame " +
                            (inspectionSlot === i ? "is-current" : "")
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
                                  lane && inspectionSlot === i
                                    ? "frame-img"
                                    : undefined
                                }
                                src={url}
                                alt={`${lane ? "Candidate" : "Reference"} frame ${i + 1}`}
                              />
                            ) : (
                              <span className="missing-reference">
                                Reference unavailable
                              </span>
                            )}
                            {Boolean(lane)&&<AnnotationSurface slot={i} width={width} height={height} value={visual} controls={annotations} onChange={setVisual} onStart={()=>focus(i,false,false)}/>}
                          </span>
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              <div
                className="measurement-track"
                aria-label="Frame measurements"
              >
                <div className="measurement-row">
                  {b.frames.map((f, i) => {
                    const attached = frameIssues(
                      issues,
                      b,
                      tickOfSlot(holds, i),
                      tickOfSlot(holds, i) + f.hold_ticks - 1,
                    );
                    const scoped = b.evaluation.results.filter(
                      (c) => scopeSlot(c) === i,
                    );
                    const metrics = scoped
                      .filter(
                        (c) =>
                          c.constraint_id.includes("silhouette") ||
                          ["fail", "error", "unmeasured"].includes(c.outcome),
                      )
                      .sort(
                        (a, z) =>
                          Number(z.constraint_id.includes("silhouette")) -
                          Number(a.constraint_id.includes("silhouette")),
                      );
                    const attention = scoped.some((c) =>
                      ["fail", "error", "unmeasured"].includes(c.outcome),
                    );
                    return (
                      <div
                        className={
                          "measurement-cell" +
                          (inspectionSlot === i ? " is-current" : "") +
                          (attention ? " needs-attention" : "")
                        }
                        key={i}
                        aria-label={`Frame ${i + 1} measurements`}
                      >
                        <div className="measurement-values">
                          {metrics.map((m, n) => (
                            <button
                              className={"frame-measure " + m.outcome}
                              key={n}
                              title={`${m.reason} · allowed ${boundLabel(m)}`}
                              aria-label={`${words(m.constraint_id)}, frame ${i + 1}: ${valueLabel(m)}`}
                              onClick={() => {
                                focus(i);
                                open("evidence", i);
                              }}
                            >
                              <span className="measurement-label">
                                {words(
                                  m.constraint_id.replace("silhouette-", ""),
                                )}
                                {m.constraint_id.startsWith("silhouette-")
                                  ? " Δ"
                                  : ""}
                              </span>
                              <strong>
                                {m.outcome === "unmeasured"
                                  ? "Unmeasured"
                                  : valueLabel(m)}
                              </strong>
                              <small>
                                {m.expected_interval?.[1] != null
                                  ? `/ ${m.units === "fraction" ? Math.round(m.expected_interval[1] * 100) + "%" : m.expected_interval[1]}`
                                  : words(m.outcome)}
                              </small>
                            </button>
                          ))}
                        </div>
                        {attached.length > 0 && (
                          <button
                            className={
                              "frame-issue " +
                              (attached[0].task_status === "resolved"
                                ? "resolved"
                                : "open")
                            }
                            title={attached
                              .map(
                                (issue) =>
                                  `${issue.note} · ${issue.task_status} · ${issue.clip_revision_id}`,
                              )
                              .join("\n")}
                            onClick={() => {
                              focus(i);
                              setIssueId(attached[0].event_id);
                              open("tasks", i);
                            }}
                          >
                            <span className="issue-dot" />
                            <span className="correction-note">
                              {attached[0].note}
                            </span>
                            <small>
                              {attached.length > 1
                                ? attached.length
                                : words(attached[0].task_status || "open")}
                            </small>
                          </button>
                        )}
                        <span
                          className="measurement-signal"
                          aria-hidden="true"
                        />
                      </div>
                    );
                  })}
                </div>
              </div>
            </Film>
            {<FilmPlayback ref={projection} lanes={[{title:compare==='baseline'&&baselineReady?'Previous':'Reference',urls:rowFrames},{title:'Candidate',urls}]} holds={holds} loop={Boolean((b.contract.action as {loop?:boolean}).loop)} clock={clock} onInspect={(i,shift)=>{setViewMode('playback');focus(i,shift);}} overlay={lane=>lane.title==='Candidate'&&!clock.playing&&<AnnotationSurface slot={clock.slot} width={width} height={height} value={visual} controls={annotations} onChange={setVisual} onStart={()=>focus(clock.slot,false,false)}/>}/>}
          </div>
          <PlaybackControls clock={clock} holds={holds} tps={timing.ticks_per_second||60} loop={Boolean((b.contract.action as {loop?:boolean}).loop)} onToggle={()=>togglePlayback()} onInspect={(i,shift)=>{setViewMode('playback');focus(i,shift);}} onScrub={inspectTick} disabled={!playbackReady}/>

        </section>
        <aside
          className={
            "frame-inspector" + (tab === "evidence" ? " showing-evidence" : "")
          }
          aria-label="Selected frame details"
        >
          <header className="pane-title inspector-heading">
            <strong>
              {tab === "evidence"
                ? "Evaluation checks"
                : `Frame ${String(inspectionSlot + 1).padStart(2, "0")}`}
            </strong>
            <div className="title-grip" aria-hidden="true" />
            {tab === "evidence" ? (
              <button
                className="window-control"
                aria-label="Close evidence"
                onClick={() => setTab(null)}
              >
                <Icon name="close" />
              </button>
            ) : (
              <span>
                {width} × {height}
              </span>
            )}
          </header>
          {tab === "evidence" ? (
            <div className="frame-inspector-content evidence-panel">
              {evidencePanel}
            </div>
          ) : (
            <>
              <div className="frame-inspector-content">
                <div
                  className="selected-stage"
                  style={{ aspectRatio: `${width}/${height}` }}
                >
                  <button
                    aria-label="Open frame preview"
                    onClick={() => open("film")}
                  >
                    <img
                      draggable={false}
                      src={current.asset_url}
                      alt="Selected candidate frame"
                    />
                  </button>
                  {overlapping
                    .filter(
                      (iss) =>
                        iss.roi &&
                        !["resolved", "cancelled"].includes(
                          iss.task_status || "open",
                        ),
                    )
                    .map((iss) => (
                      <span
                        className="region-box"
                        key={iss.event_id}
                        title={iss.note}
                        style={{
                          left: `${(iss.roi!.left / width) * 100}%`,
                          top: `${(iss.roi!.top / height) * 100}%`,
                          width: `${((iss.roi!.right - iss.roi!.left) / width) * 100}%`,
                          height: `${((iss.roi!.bottom - iss.roi!.top) / height) * 100}%`,
                        }}
                      />
                    ))}
                </div>
                {media.errors.has(current.asset_url) && (
                  <p className="error" role="alert">
                    {media.errors.get(current.asset_url)}
                  </p>
                )}
                <section className="frame-findings">
                  <header>
                    <h2>Checks</h2>
                    <button
                      className="text-button"
                      onClick={() => open("evidence")}
                    >
                      {checks.length} checks ↗
                    </button>
                  </header>
                  {b.evaluation.results
                    .filter(
                      (c) =>
                        scopeSlot(c) === inspectionSlot &&
                        c.constraint_id !== "registration",
                    )
                    .map((check, i) => (
                      <Measure key={i} check={check} />
                    ))}
                </section>
                <section className="frame-corrections">
                  <header>
                    <h2>Corrections</h2>
                    <span>{overlapping.length}</span>
                  </header>
                  {overlapping.map((iss) => (
                    <button
                      className="inspector-correction"
                      key={iss.event_id}
                      onClick={() => {
                        setIssueId(iss.event_id);
                        open("tasks");
                      }}
                    >
                      <strong>{iss.note}</strong>
                      <small>
                        {words(iss.task_status || "open")} ·{" "}
                        {iss.frame_range?.join("–") || "all"} ticks
                        {iss.clip_revision_id !== revision
                          ? ` · ${iss.clip_revision_id}`
                          : ""}
                      </small>
                    </button>
                  ))}
                  <button
                    className="correction-action"
                    aria-label="Request correction"
                    onClick={() => open("correction")}
                  >
                    <Icon name="plus" />
                    Correction
                  </button>
                </section>
                <section
                  className="reference-stills"
                  aria-label="Frozen visual references"
                >
                  {[
                    ["Identity", contractRefs?.identity],
                    ["Style", contractRefs?.style],
                  ]
                    .filter(([, asset]) => Boolean(asset))
                    .map(([label, asset]) => (
                      <button
                        key={label}
                        onClick={() => {
                          pausePlayback();
                          setReferenceAsset({ label: label!, id: asset! });
                        }}
                      >
                        <img
                          src={api.assetUrl(asset!)}
                          alt={`Frozen ${label?.toLowerCase()} reference`}
                        />
                        <span>{label}</span>
                      </button>
                    ))}
                </section>
              </div>
              <div className="review-actions">
                <div className="review-state">
                  <span>Human review</span>
                  <strong>
                    {words(b.current_decision.acceptance || "unreviewed")}
                  </strong>
                </div>
                <button className="primary" onClick={() => open("decision")}>
                  Decision <Icon name="right" />
                </button>
              </div>
            </>
          )}
        </aside>
      </div>
      {referenceAsset && (
        <Modal
          title={`${referenceAsset.label} reference`}
          onClose={() => setReferenceAsset(null)}
        >
          <div className="reference-enlarged">
            <img
              src={api.assetUrl(referenceAsset.id)}
              alt={`${referenceAsset.label} reference`}
            />
          </div>
        </Modal>
      )}
      {tab && tab !== "evidence" && (
        <Modal
          wide
          onKeyDown={(e) => {
            const target = e.target as HTMLElement;
            if (target.matches("input,textarea,select")) return;
            if (tab !== "film") return;
            if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
              e.preventDefault();
              wasPlaying.current = false;
              clock.setPlaying(false);
              if (e.key === "Home") inspectTick(0);
              else if (e.key === "End") inspectTick(totalTicks(holds) - 1);
              else inspectTick(clock.tick + (e.key === "ArrowRight" ? 1 : -1));
            }
            if (e.code === "Space" && target.tagName !== "BUTTON") {
              e.preventDefault();
              if (tab === "film") togglePlayback("modal");
            }
          }}
          title={`${actionName(b)} / ${revision}`}
          onClose={() => {
            if (tab === "film") {
              pausePlayback();
              controls.film.current?.reveal(clock.slot, true);
            } else clock.setPlaying(false);
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
                  open(t, tab === "film" ? clock.slot : inspectionSlot);
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
                  {tab === "film" && (
                    <>
                      <div className="playback-controls">
                        <button
                          aria-label={clock.playing ? "Pause" : "Play"}
                          onClick={() => togglePlayback("modal")}
                          disabled={!clock.playing && !candidateReady}
                        >
                          <Icon name={clock.playing ? "pause" : "play"} />
                        </button>
                        <button
                          onClick={() => {
                            inspectTick(clock.tick - 1);
                          }}
                        >
                          −1 tick
                        </button>
                        <button
                          onClick={() => {
                            inspectTick(clock.tick + 1);
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
                          inspectTick(Number(e.target.value));
                        }}
                      />
                      <p id="tick-readout">
                        tick {clock.tick} / {totalTicks(holds)} · frame{" "}
                        {clock.slot + 1} · {words(stageFrame.phase)} · hold{" "}
                        {stageFrame.hold_ticks}
                      </p>
                    </>
                  )}
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
                    <button className="primary" disabled={busy || !note.trim()}>
                      {busy ? "Recording…" : "Send to model"}
                      <Icon name="right" />
                    </button>
                  </form>
                )}
              </div>
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
                                  busy || iss.task_status === "resolved"
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
                        disabled={busy}
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
                  <button disabled={busy} onClick={() => decide("reject")}>
                    Reject
                  </button>
                  <button
                    disabled={busy}
                    onClick={() => decide("needs_changes")}
                  >
                    Needs work
                  </button>
                  <button
                    className="primary"
                    disabled={busy}
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

function Measure({ check }: { check: EvalResultDto }) {
  const label =
    (
      {
        "silhouette-area": "Area drift",
        "silhouette-width": "Width drift",
        "visible-torso-span": "Torso span",
      } as Record<string, string>
    )[check.constraint_id] || words(check.constraint_id);
  const ratio =
    check.units === "fraction" && typeof check.observed_value === "number";
  const max = check.expected_interval?.[1];
  return (
    <div className={"measure " + check.outcome}>
      <div className="measure-title">
        <span title={words(check.constraint_id)}>{label}</span>
        <strong>
          {check.outcome === "unmeasured"
            ? "Unmeasured"
            : check.outcome === "not_applicable"
              ? "N/A"
              : valueLabel(check)}
          {max != null && (
            <small title="Maximum allowed">
              {" "}
              / {ratio ? Math.round(max * 100) + "%" : max}
            </small>
          )}
        </strong>
      </div>
      {ratio && max != null ? (
        <div
          className="measure-bar"
          style={
            {
              "--value": `${Math.min(100, Number(check.observed_value) * 100)}%`,
              "--limit": `${max * 100}%`,
            } as React.CSSProperties
          }
          aria-label={`${label} ${valueLabel(check)}, allowed ${boundLabel(check)}`}
        >
          <i />
        </div>
      ) : (
        check.outcome !== "pass" && (
          <p title={check.reason}>
            {check.outcome === "unmeasured"
              ? "Needs annotation"
              : check.outcome === "not_applicable"
                ? "Occluded in contract"
                : check.reason}
          </p>
        )
      )}
    </div>
  );
}
