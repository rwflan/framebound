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

export function StatusView({showPending=true}:{showPending?:boolean}={}) {
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
      {showPending&&<><h3>Pending model work</h3>
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
      </>}
      <Err e={awaiting.err}/><h3>Evidence</h3>
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
  const [data,setData]=useState<Awaited<ReturnType<typeof api.references>>|null>(null),[error,setError]=useState<unknown>(null),[busy,setBusy]=useState<string|null>(null),[selected,setSelected]=useState('');
  const refresh=useCallback(()=>api.references().then(setData).catch(setError),[]);
  useEffect(()=>{void refresh();const changed=()=>{void refresh();};window.addEventListener('framebound:changed',changed);return()=>window.removeEventListener('framebound:changed',changed);},[refresh]);
  const guide=data?.motion_guides.find(g=>g.id===selected)||data?.motion_guides[0];
  const char=data?.character_revisions.find(c=>c.id===guide?.character_revision_id);
  const approval=guide&&data?.reference_approvals.find(a=>a.character_revision_id===guide.character_revision_id&&a.motion_guide_id===guide.id&&data.active_approval_ids.includes(a.id));
  async function approve(revoke=false){if(!guide||busy)return;setBusy(guide.id);setError(null);try{if(revoke&&approval)await api.revokeReference(approval.id,`revoke-${crypto.randomUUID()}`);else await api.approveReferences(guide.character_revision_id,guide.id,`ref-${crypto.randomUUID()}`);await refresh();}catch(e){setError(e);}finally{setBusy(null);}}
  return <div className="utility-guides" aria-label="Reference proposals"><section className="utility-section"><header><h2>Reference library</h2><span className="utility-caption">{data?.motion_guides.length??'…'} guides</span></header><p className="utility-intro">Frozen identity, style and phase references. Reference approval grants scoped authority; it does not approve an animation.</p><Err e={error}/>{!data?error?<button onClick={()=>void refresh()}>Reload references</button>:<p role="status">Loading references…</p>:!guide?<div className="utility-empty"><strong>No guide proposals</strong><p>This workspace has no authored phase guides. Image-only review does not require invented references.</p><a href="#/">Return to review →</a></div>:<div className="utility-guide-layout"><nav className="utility-guide-list" aria-label="Reference guides">{data.motion_guides.map(g=>{const approved=data.reference_approvals.some(a=>a.character_revision_id===g.character_revision_id&&a.motion_guide_id===g.id&&data.active_approval_ids.includes(a.id));return <button key={g.id} aria-current={g.id===guide.id?'page':undefined} onClick={()=>setSelected(g.id)}>{g.entries[0]&&<img src={api.assetUrl(g.entries[0].asset_id)} alt=""/>}<span><strong>{g.id}</strong><small>{g.character_revision_id} · {approved?'Approved':'Proposed'}</small></span></button>;})}</nav><article className="utility-guide-detail"><header><h3>{guide.id}</h3><span className={'badge '+(approval?'pass':'')}>{approval?'References approved':'Proposed references'}</span></header>{char&&<div className="utility-reference-images">{[['Identity',char.identity_asset_ids],['Style',char.style_asset_ids]].map(([label,ids])=><section key={String(label)}><h4>{String(label)}</h4><div className="utility-thumbnails">{(ids as string[]).map(id=><figure key={id}><a href={api.assetUrl(id)} target="_blank" rel="noreferrer"><img src={api.assetUrl(id)} alt={`${label}: ${id}`}/></a><figcaption title={id}>{id}</figcaption></figure>)}</div></section>)}</div>}<h4>Phase guide</h4><div className="utility-thumbnails">{guide.entries.map(entry=><figure key={entry.phase}><a href={api.assetUrl(entry.asset_id)} target="_blank" rel="noreferrer"><img src={api.assetUrl(entry.asset_id)} alt={`Phase ${entry.phase}`}/></a><figcaption>{entry.phase}</figcaption></figure>)}</div><details className="utility-disclosure"><summary>Repair authority and masks</summary>{guide.repair_policy?<dl className="utility-definition"><dt>Operations</dt><dd>{Array.isArray(guide.repair_policy.operators)?guide.repair_policy.operators.join(', '):'None'}</dd><dt>Translation</dt><dd>{String(guide.repair_policy.translation_budget_px)} native pixels</dd><dt>Attempts / phase</dt><dd>{String(guide.repair_policy.max_local_attempts)}</dd><dt>Compute steps</dt><dd>{String(guide.repair_policy.max_compute_steps)}</dd><dt>Provider sends</dt><dd>{guide.repair_policy.generation_allowed?String(guide.repair_policy.max_provider_dispatches):'Disabled'}</dd></dl>:<p>No automatic repair authority.</p>}<div className="utility-mask-list">{guide.entries.map(entry=><section key={entry.phase}><strong>{entry.phase}</strong><div>{[['Editable',entry.editable_mask_asset_id],['Protected',entry.protected_mask_asset_id]].map(([label,id])=><figure key={label}><figcaption>{label}</figcaption>{id?<img src={api.assetUrl(id)} alt={`${entry.phase} ${label} mask`}/>:<small>Not supplied</small>}</figure>)}</div></section>)}</div></details>{guide.source_calibration&&<details className="utility-disclosure"><summary>Source conversion</summary><p>{String(guide.source_calibration.source_width)} × {String(guide.source_calibration.source_height)} · nearest neighbour</p><code>Crop {JSON.stringify(guide.source_calibration.crop)}</code></details>}<div className="utility-actions"><button disabled={Boolean(approval)||busy!==null} onClick={()=>void approve()}>{approval?'References approved':busy===guide.id?'Recording…':'Approve references'}</button>{approval&&<button className="utility-danger" disabled={busy!==null} onClick={()=>void approve(true)}>Revoke approval</button>}</div></article></div>}</section></div>;
}
