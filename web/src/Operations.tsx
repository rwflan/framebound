import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type {
  CompareBundleDto,
  ExportResultDto,
  IssueDetailDto,
  TaskStatusDto,
} from "./api-types";
import { Err, nav, useLoad, usePreload, words } from "./shared";

export function CompareView({ base, other }: { base: string; other: string }) {
  const {
    data: d,
    err,
    reload,
  } = useLoad<CompareBundleDto>(`compare-${base}-${other}`, () =>
    api.compare(base, other),
  );
  const [mode, setMode] = useState<"side" | "blink" | "diff">("side");
  const [slot, setSlot] = useState(0);
  const [blinkOn, setBlinkOn] = useState(true);
  const [diffPct, setDiffPct] = useState<string>("");
  const [diffErr, setDiffErr] = useState("");
  const difference = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (mode !== "blink") return;
    const t = setInterval(() => setBlinkOn((v) => !v), 500);
    return () => clearInterval(t);
  }, [mode]);
  const urls = useMemo(
    () => [
      ...(d?.base.frames ?? []).map((f) => f.asset_url),
      ...(d?.other.frames ?? []).map((f) => f.asset_url),
    ],
    [d],
  );
  const { imgs, errors } = usePreload(urls);

  useEffect(() => {
    setDiffPct("");
    setDiffErr("");
    if (mode !== "diff" || !d) return;
    const bf = d.base.frames[slot],
      of = d.other.frames[slot];
    const bi = bf ? imgs.get(bf.asset_url) : undefined;
    const oi = of ? imgs.get(of.asset_url) : undefined;
    if (!bi || !oi) {
      if (bf && of && (errors.get(bf.asset_url) || errors.get(of.asset_url)))
        setDiffErr("media failed to load");
      return;
    }
    try {
      const w = bi.naturalWidth,
        h = bi.naturalHeight;
      const c = document.createElement("canvas");
      c.width = w;
      c.height = h;
      const ctx = c.getContext("2d", { willReadFrequently: true });
      if (!ctx) return;
      ctx.drawImage(bi, 0, 0);
      const left = ctx.getImageData(0, 0, w, h);
      ctx.clearRect(0, 0, w, h);
      ctx.drawImage(oi, 0, 0, w, h);
      const right = ctx.getImageData(0, 0, w, h),
        output = ctx.createImageData(w, h);
      let sum = 0;
      for (let i = 0; i < left.data.length; i += 4) {
        const alpha = Math.abs(left.data[i + 3] - right.data[i + 3]);
        for (let j = 0; j < 3; j++) {
          const delta = Math.abs(left.data[i + j] - right.data[i + j]);
          sum += delta;
          output.data[i + j] = Math.max(delta, alpha);
        }
        output.data[i + 3] = 255;
      }
      const target = difference.current;
      if (target) {
        target.width = w;
        target.height = h;
        target.getContext("2d")?.putImageData(output, 0, 0);
      }
      setDiffPct(`${((sum / (w * h * 3 * 255)) * 100).toFixed(2)}%`);
    } catch (e) {
      setDiffErr(String(e));
    }
  }, [mode, d, slot, imgs, errors]);

  if (err) return <Err e={err} />;
  if (!d) return <p>Loading comparison…</p>;
  const slots = Math.max(d.base.frames.length, d.other.frames.length);
  const bf = d.base.frames[Math.min(slot, d.base.frames.length - 1)];
  const of = d.other.frames[Math.min(slot, d.other.frames.length - 1)];
  return (
    <section>
      <h2 id="compare-title">Compare</h2>
      <p>
        <small>
          baseline {base} ({d.base.technical_status}) vs candidate {other} (
          {d.other.technical_status}) ·
          {d.timing_equal
            ? "identical timing: frame index equality is synchronization"
            : d.timing_note}
        </small>
      </p>
      {!d.timing_equal && <p role="alert">{d.timing_note}</p>}
      <label>
        Mode{" "}
        <select
          aria-label="Mode"
          value={mode}
          onChange={(e) => setMode(e.target.value as "side" | "blink" | "diff")}
        >
          <option value="side">side-by-side</option>
          <option value="blink">blink</option>
          <option value="diff">difference</option>
        </select>
      </label>{" "}
      <label>
        Frame{" "}
        <input
          id="compare-slot"
          type="number"
          value={slot}
          min={0}
          max={slots - 1}
          onChange={(e) =>
            setSlot(
              Math.max(0, Math.min(slots - 1, parseInt(e.target.value) || 0)),
            )
          }
        />
      </label>{" "}
      <button onClick={() => nav({ name: "inbox" })}>Back</button>
      <div className="comparison-stage">
        {(mode === "side" ||
          (mode === "blink" && blinkOn) ||
          mode === "diff") &&
          bf && (
            <figure style={{ margin: 0 }}>
              <img
                id="compare-base-img"
                src={bf.asset_url}
                alt={`baseline frame ${slot}`}
              />
              <figcaption>
                <small>
                  baseline {bf.asset_id} · slot {bf.slot} · phase {bf.phase}
                </small>
              </figcaption>
            </figure>
          )}
        {(mode === "side" || (mode === "blink" && !blinkOn)) && of && (
          <figure style={{ margin: 0 }}>
            <img
              id="compare-other-img"
              src={of.asset_url}
              alt={`candidate frame ${slot}`}
            />
            <figcaption>
              <small>
                candidate {of.asset_id} · slot {of.slot} · phase {of.phase}
              </small>
            </figcaption>
          </figure>
        )}
        {mode === "diff" && (
          <figure>
            <canvas ref={difference} aria-label="Pixel difference" />
            <figcaption id="diff-readout">
              mean abs diff {diffPct || "…"} {diffErr && `(error: ${diffErr})`}
            </figcaption>
          </figure>
        )}
      </div>
    </section>
  );
}

export function IssuesView({ revision }: { revision?: string }) {
  const [rev, setRev] = useState(revision ?? "");
  const { data, err, reload } = useLoad<IssueDetailDto[]>(`issues-${rev}`, () =>
    api.issues(rev || undefined),
  );
  const [packets, setPackets] = useState<Record<string, unknown>[]>([]);
  useEffect(() => {
    api
      .packets()
      .then((p) => setPackets(p.packets))
      .catch(() => {});
  }, []);
  const [msg, setMsg] = useState("");
  const [opErr, setOpErr] = useState<unknown>(null);
  if (err) return <Err e={err} />;
  const packetFor = (clipId: string) =>
    packets.find((p) => p.clip_revision_id === clipId) as
      | Record<string, unknown>
      | undefined;
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg("");
    setOpErr(null);
    try {
      await fn();
      setMsg(ok);
      reload();
    } catch (e) {
      setOpErr(e);
    }
  };
  return (
    <section>
      <h2>Issues {rev && <>on {rev}</>}</h2>
      <label>
        Revision{" "}
        <input value={rev} onChange={(e) => setRev(e.target.value)} size={20} />
      </label>
      {msg && <p>{msg}</p>}
      <Err e={opErr} />
      {!data ? (
        <p>Loading…</p>
      ) : data.length === 0 ? (
        <p>No issues recorded{rev ? " on this revision" : ""}.</p>
      ) : (
        <ul>
          {data.map((iss) => (
            <li key={iss.event_id} style={{ marginBottom: 12 }}>
              <b>{iss.category}</b> · {iss.task_status ?? "no task"} ·
              acceptance {iss.current_acceptance}
              <br />
              <small>
                ROI{" "}
                {iss.roi
                  ? [
                      iss.roi.left,
                      iss.roi.top,
                      iss.roi.right,
                      iss.roi.bottom,
                    ].join(",")
                  : "—"}{" "}
                · range{" "}
                {iss.frame_range && iss.frame_range.length === 2
                  ? iss.frame_range.join("-")
                  : "—"}{" "}
                · coverage {iss.coverage} · {iss.note}
              </small>
              {iss.findings.length > 0 && (
                <ul>
                  {iss.findings.map((f, i) => (
                    <li key={i}>
                      <small>
                        {f.constraint_id} ({f.outcome}): {f.reason}
                      </small>
                    </li>
                  ))}
                </ul>
              )}
              {iss.attempts.length > 0 && (
                <p>
                  <small>
                    attempts:{" "}
                    {iss.attempts
                      .map((a) => `${a.id.slice(0, 12)}…=${a.result}`)
                      .join(" · ")}
                  </small>
                </p>
              )}
              {iss.candidate_revisions.length > 0 && (
                <ul>
                  {iss.candidate_revisions.map((c, i) => {
                    const pkt = packetFor(String(c.revision_id));
                    return (
                      <li key={i}>
                        <small>
                          candidate {String(c.revision_id)} (
                          {String(c.technical_status)})
                          {pkt ? (
                            <>
                              {" "}
                              ·{" "}
                              <button
                                disabled={false}
                                onClick={() =>
                                  act(
                                    () =>
                                      api.resolveIssue(iss.event_id, {
                                        replacement_revision_id: String(
                                          c.revision_id,
                                        ),
                                        packet_id: String(pkt.id),
                                      }),
                                    `Resolved against ${c.revision_id}.`,
                                  )
                                }
                              >
                                Resolve with this
                              </button>
                            </>
                          ) : (
                            " · no comparison packet yet"
                          )}
                        </small>
                      </li>
                    );
                  })}
                </ul>
              )}
              {iss.task_status === "resolved" && (
                <button
                  disabled={false}
                  onClick={() =>
                    act(
                      () =>
                        api.reopenIssue(iss.event_id, {
                          note: "reopened from desk",
                        }),
                      "Reopened.",
                    )
                  }
                >
                  Reopen
                </button>
              )}
              {iss.resolution_event_id && (
                <small> resolution {iss.resolution_event_id}</small>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function CorrectionsView() {
  const [status, setStatus] = useState("all");
  const { data, err, reload } = useLoad(`corrections-${status}`, () =>
    api.corrections(status),
  );
  const [detail, setDetail] = useState<string | null>(null);
  const det = useLoad<TaskStatusDto | null>(`task-${detail}`, () =>
    detail ? api.correctionGet(detail) : Promise.resolve(null),
  );
  return (
    <section>
      <h2>Correction queue</h2>
      <label>
        Status{" "}
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          {[
            "all",
            "open",
            "reopened",
            "claimed",
            "attempting",
            "awaiting_comparison",
            "blocked",
            "resolved",
            "cancelled",
          ].map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </label>{" "}
      {err ? (
        <Err e={err} />
      ) : !data ? (
        <p>Loading…</p>
      ) : (
        <ul id="task-list">
          {((data.tasks ?? data.open ?? []) as Record<string, unknown>[]).map(
            (t) => (
              <li key={String(t.id)}>
                {String(t.id)} · {String(t.status)} · baseline{" "}
                {String(t.baseline_revision_id)}{" "}
                <button onClick={() => setDetail(String(t.id))}>status</button>
              </li>
            ),
          )}
        </ul>
      )}
      {det.data && (
        <article className="task-detail">
          <h3>{words(det.data.task.status)}</h3>
          <dl className="facts">
            <dt>Task</dt>
            <dd>{String(det.data.task.id)}</dd>
            <dt>Baseline</dt>
            <dd>{String(det.data.task.baseline_revision_id)}</dd>
            <dt>Lease</dt>
            <dd>{det.data.lease_valid ? "Active" : "Inactive"}</dd>
            <dt>Version</dt>
            <dd>{det.data.version}</dd>
            <dt>Attempts</dt>
            <dd>{det.data.attempts.length}</dd>
          </dl>
          {det.data.attempts.map((a) => (
            <p key={a.id}>
              {words(a.result)} · {a.candidates.join(", ") || "No candidates"}
            </p>
          ))}
          <details>
            <summary>Recorded task data</summary>
            <pre>{JSON.stringify(det.data, null, 2)}</pre>
          </details>
        </article>
      )}
      {det.err ? <Err e={det.err} /> : null}
    </section>
  );
}

export function ExportView() {
  const [name, setName] = useState("desk-snapshot");
  const [revisions, setRevisions] = useState("");
  const [procedural, setProcedural] = useState(false);
  const [result, setResult] = useState<ExportResultDto | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const build = async () => {
    setErr(null);
    setResult(null);
    setBusy(true);
    try {
      const revs = revisions
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const r = await api.buildExport(name.trim(), revs, {
        include_procedural_positives: procedural,
      });
      setResult(r);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section>
      <h2>Training export</h2>
      <div className="export-fields">
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label>
          Revisions (comma-separated)
          <input
            value={revisions}
            onChange={(e) => setRevisions(e.target.value)}
          />
        </label>
        <label className="checkbox-field">
          <input
            type="checkbox"
            checked={procedural}
            onChange={(e) => setProcedural(e.target.checked)}
          />{" "}
          include procedural positives (labeled research otherwise)
        </label>
        <button
          className="primary"
          onClick={build}
          disabled={busy || !name.trim() || !revisions.trim()}
        >
          {busy ? "Building…" : "Build + validate"}
        </button>
      </div>
      <Err e={err} />
      {result && (
        <div className="export-result" role="status">
          <h3>{result.ok ? "Export validated" : "Validation failed"}</h3>
          <dl className="facts">
            {Object.entries(result.counts).map(([key, count]) => (
              <div key={key}>
                <dt>{words(key)}</dt>
                <dd>{count}</dd>
              </div>
            ))}
          </dl>
          {result.issues.map((i) => (
            <p key={i}>{i}</p>
          ))}
          {result.exclusions.length > 0 && (
            <>
              <h4>Exclusions</h4>
              <ul>
                {result.exclusions.map((e, i) => (
                  <li key={i}>
                    {Object.entries(e).map(([key, value]) => (
                      <span key={key}>
                        {words(key)}:{" "}
                        {typeof value === "object"
                          ? JSON.stringify(value)
                          : String(value)}{" "}
                        ·{" "}
                      </span>
                    ))}
                  </li>
                ))}
              </ul>
            </>
          )}
          <details>
            <summary>Export manifest</summary>
            <pre>{JSON.stringify(result, null, 2)}</pre>
          </details>
        </div>
      )}
    </section>
  );
}

export function StatusView() {
  // Concise capability truth + pending model work with evidence links.
  // A review tool, not a manual editor: open items go to the model's queue.
  const caps = useLoad("capabilities", api.capabilities);
  const open = useLoad("corrections-open", () => api.corrections("open"));
  const awaiting = useLoad("corrections-awaiting", () =>
    api.corrections("awaiting_comparison,blocked,attempting,claimed"),
  );
  return (
    <section>
      <h2>Status</h2>
      <Err e={caps.err} />
      <Err e={open.err} />
      <h3>Pending model work</h3>
      {!open.data ? (
        <p>Loading…</p>
      ) : ((open.data.open ?? []) as Record<string, unknown>[]).length === 0 ? (
        <p>
          <small>No open correction tasks.</small>
        </p>
      ) : (
        <ul>
          {((open.data.open ?? []) as Record<string, unknown>[]).map((t) => (
            <li key={String(t.id)}>
              <small>
                <button onClick={() => nav({ name: "corrections" })}>
                  {String(t.id)}
                </button>{" "}
                open
              </small>
            </li>
          ))}
        </ul>
      )}
      {!awaiting.data ? null : (
          (awaiting.data.tasks ?? []) as Record<string, unknown>[]
        ).length === 0 ? null : (
        <ul>
          {((awaiting.data.tasks ?? []) as Record<string, unknown>[]).map(
            (t) => (
              <li key={String(t.id)}>
                <small>
                  <button onClick={() => nav({ name: "corrections" })}>
                    {String(t.id)}
                  </button>{" "}
                  {String(t.status)}
                </small>
              </li>
            ),
          )}
        </ul>
      )}
      <h3>Evidence</h3>
      <p>
        <small>
          Checked-in release evidence. Test reviewers do not represent entrant
          artistic acceptance.
        </small>
      </p>
      {caps.data && (
        <table>
          <thead>
            <tr>
              <th>Capability</th>
              <th>Implemented</th>
              <th>Counterexamples</th>
              <th>Public workflow</th>
              <th>Participant live</th>
              <th>Entrant review</th>
            </tr>
          </thead>
          <tbody>
            {caps.data.evidence.map((e) => (
              <tr key={e.capability}>
                <td>{e.capability}</td>
                {[
                  e.implemented,
                  e.negative_tested,
                  e.public_integrated,
                  e.live_observed,
                  e.human_reviewed,
                ].map((value, i) => (
                  <td key={i}>
                    {value === null
                      ? "N/A"
                      : value
                        ? "Demonstrated"
                        : "Pending"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <h3>Capabilities</h3>
      {!caps.data ? (
        <p>Loading…</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>transport</th>
              <th>operation</th>
              <th>status</th>
              <th>note</th>
            </tr>
          </thead>
          <tbody>
            {caps.data.rows.map((r, i) => (
              <tr key={i}>
                <td>
                  <small>{r.transport}</small>
                </td>
                <td>
                  <small>{r.operation}</small>
                </td>
                <td>
                  <small>{r.status}</small>
                </td>
                <td>
                  <small>{r.note}</small>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export function ReferencesView() {
  const [data, setData] = useState<Awaited<
    ReturnType<typeof api.references>
  > | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const refresh = useCallback(
    () => api.references().then(setData).catch(setError),
    [],
  );
  useEffect(() => {
    void refresh();
    const changed = () => {
      void refresh();
    };
    window.addEventListener("framebound:changed", changed);
    return () => window.removeEventListener("framebound:changed", changed);
  }, [refresh]);
  return (
    <section aria-label="Reference proposals">
      <h2>Reference proposals</h2>
      <Err e={error} />
      {!data && <p>Loading references…</p>}
      {data && data.motion_guides.length === 0 && <p>No guide proposals.</p>}
      {data?.motion_guides.map((guide) => {
        const char = data.character_revisions.find(
          (c) => c.id === guide.character_revision_id,
        );
        const approval = data.reference_approvals.find(
          (a) =>
            a.character_revision_id === guide.character_revision_id &&
            a.motion_guide_id === guide.id &&
            data.active_approval_ids.includes(a.id),
        );
        const approved = Boolean(approval);
        return (
          <article
            key={guide.id}
            style={{ borderTop: "1px solid #ccc", padding: "20px 0" }}
          >
            <h3>
              {guide.character_revision_id} · {guide.id}
            </h3>
            <h4>Automatic repair authority</h4>
            {guide.repair_policy ? (
              <dl
                style={{
                  display: "grid",
                  gridTemplateColumns: "max-content 1fr",
                  gap: "6px 20px",
                  fontSize: 14,
                }}
              >
                <dt>Allowed operations</dt>
                <dd>
                  {Array.isArray(guide.repair_policy.operators)
                    ? guide.repair_policy.operators.join(", ")
                    : "None"}
                </dd>
                <dt>Translation limit</dt>
                <dd>
                  {String(guide.repair_policy.translation_budget_px)} native
                  pixels
                </dd>
                <dt>Attempts per phase</dt>
                <dd>{String(guide.repair_policy.max_local_attempts)}</dd>
                <dt>Compute steps</dt>
                <dd>{String(guide.repair_policy.max_compute_steps)}</dd>
                <dt>Provider dispatches</dt>
                <dd>
                  {guide.repair_policy.generation_allowed
                    ? String(guide.repair_policy.max_provider_dispatches)
                    : "Disabled"}
                </dd>
              </dl>
            ) : (
              <p>Manual work only</p>
            )}
            {guide.source_calibration && (
              <p>
                Fixed source conversion:{" "}
                {String(guide.source_calibration.source_width)} ×{" "}
                {String(guide.source_calibration.source_height)}, crop{" "}
                {JSON.stringify(guide.source_calibration.crop)}, nearest
                neighbour.
              </p>
            )}
            <div
              style={{
                display: "flex",
                gap: 12,
                flexWrap: "wrap",
                margin: "16px 0",
              }}
            >
              {guide.entries.map((entry) => (
                <div
                  key={"scope-" + entry.phase}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "64px 64px",
                    gap: 4,
                    border: "1px solid #ddd",
                    padding: 8,
                  }}
                >
                  <small style={{ gridColumn: "1 / -1" }}>
                    {entry.phase} · editable / protected
                  </small>
                  {entry.editable_mask_asset_id && (
                    <img
                      width={64}
                      height={64}
                      style={{ imageRendering: "pixelated" }}
                      src={api.assetUrl(entry.editable_mask_asset_id)}
                      alt={entry.phase + " editable mask"}
                    />
                  )}
                  {entry.protected_mask_asset_id && (
                    <img
                      width={64}
                      height={64}
                      style={{ imageRendering: "pixelated" }}
                      src={api.assetUrl(entry.protected_mask_asset_id)}
                      alt={entry.phase + " protected mask"}
                    />
                  )}
                </div>
              ))}
            </div>
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
              {char &&
                [
                  ["Identity", char.identity_asset_ids],
                  ["Style", char.style_asset_ids],
                ].map(([label, ids]) => (
                  <div key={String(label)}>
                    <h4>{String(label)}</h4>
                    {(ids as string[]).map((id) => (
                      <figure
                        key={id}
                        style={{ display: "inline-block", margin: 8 }}
                      >
                        <img
                          alt={`${label}: ${id}`}
                          src={api.assetUrl(id)}
                          width={128}
                          height={128}
                          style={{
                            objectFit: "contain",
                            imageRendering: "pixelated",
                            background: "#eee",
                          }}
                        />
                        <figcaption>{id}</figcaption>
                      </figure>
                    ))}
                  </div>
                ))}
              <div>
                <h4>Phase guide</h4>
                {guide.entries.map((entry) => (
                  <figure
                    key={entry.phase}
                    style={{ display: "inline-block", margin: 8 }}
                  >
                    <img
                      alt={`Phase ${entry.phase}`}
                      src={api.assetUrl(entry.asset_id)}
                      width={128}
                      height={128}
                      style={{
                        objectFit: "contain",
                        imageRendering: "pixelated",
                        background: "#eee",
                      }}
                    />
                    <figcaption>{entry.phase}</figcaption>
                  </figure>
                ))}
              </div>
            </div>
            <button
              disabled={approved || busy !== null}
              onClick={async () => {
                setBusy(guide.id);
                setError(null);
                try {
                  await api.approveReferences(
                    guide.character_revision_id,
                    guide.id,
                    `ref-${crypto.randomUUID()}`,
                  );
                  await refresh();
                } catch (e) {
                  setError(e);
                } finally {
                  setBusy(null);
                }
              }}
            >
              {approved
                ? "References approved"
                : busy === guide.id
                  ? "Recording…"
                  : "Approve these references"}
            </button>
            {approval && (
              <button
                disabled={busy === guide.id}
                onClick={async () => {
                  setBusy(guide.id);
                  setError(null);
                  try {
                    await api.revokeReference(
                      approval.id,
                      `revoke-${crypto.randomUUID()}`,
                    );
                    await refresh();
                  } catch (e) {
                    setError(e);
                  } finally {
                    setBusy(null);
                  }
                }}
              >
                Revoke reference approval
              </button>
            )}
          </article>
        );
      })}
    </section>
  );
}
