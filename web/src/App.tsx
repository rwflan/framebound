import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api, ApiError, clearSession, getReviewer, getToken, setSession } from './api';
import type { CompareBundleDto, IssueDetailDto, PacketBundleDto, TaskStatusDto } from './api-types';
import { slotAtTick, toNative, totalTicks } from './playback';
import { usePresentationClock } from './useClock';

type View =
  | { name: 'inbox' }
  | { name: 'packet'; id: string }
  | { name: 'compare'; base: string; other: string }
  | { name: 'issues'; revision?: string }
  | { name: 'corrections' }
  | { name: 'export' }
  | { name: 'activity' }
  | { name: 'status' }
  | { name: 'references' };

function parseHash(): View {
  const h = window.location.hash.replace(/^#/, '');
  const [path, query] = h.split('?');
  const q = new URLSearchParams(query || '');
  const seg = path.split('/').filter(Boolean);
  if (seg[0] === 'packet' && seg[1]) return { name: 'packet', id: decodeURIComponent(seg[1]) };
  if (seg[0] === 'compare') {
    const base = q.get('base') || '';
    const other = q.get('other') || '';
    if (base && other) return { name: 'compare', base, other };
  }
  if (seg[0] === 'issues') return { name: 'issues', revision: q.get('revision') || undefined };
  if (seg[0] === 'corrections') return { name: 'corrections' };
  if (seg[0] === 'export') return { name: 'export' };
  if (seg[0] === 'activity') return { name: 'activity' };
  if (seg[0] === 'references') return { name: 'references' };
  if (seg[0] === 'status') return { name: 'status' };
  return { name: 'inbox' };
}

function nav(v: View) {
  if (v.name === 'inbox') window.location.hash = '#/';
  else if (v.name === 'packet') window.location.hash = `#/packet/${encodeURIComponent(v.id)}`;
  else if (v.name === 'compare') window.location.hash = `#/compare?base=${encodeURIComponent(v.base)}&other=${encodeURIComponent(v.other)}`;
  else if (v.name === 'issues') window.location.hash = `#/issues${v.revision ? `?revision=${encodeURIComponent(v.revision)}` : ''}`;
  else window.location.hash = `#/${v.name}`;
}

function useHashView(): View {
  const [view, setView] = useState<View>(() => (typeof window === 'undefined' ? { name: 'inbox' } : parseHash()));
  useEffect(() => {
    const onChange = () => setView(parseHash());
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, []);
  return view;
}

function Err({ e }: { e: unknown }) {
  if (!e) return null;
  return <p role="alert" style={{ color: '#a00' }}>{e instanceof ApiError ? `${e.status} ${e.code}: ${e.message}` : String(e)}</p>;
}

export default function App() {
  const view = useHashView();
  const [reviewer, setReviewer] = useState<string | null>(() => getReviewer());
  return (
    <div style={{ fontFamily: 'system-ui,sans-serif', margin: 16, maxWidth: 1200 }}>
      <header style={{ display: 'flex', gap: 12, alignItems: 'baseline', flexWrap: 'wrap' }}>
        <h1 style={{ fontSize: 20, margin: 0 }}>Framebound review desk</h1>
        <button onClick={() => nav({ name: 'inbox' })}>Inbox</button>
        <button onClick={() => nav({ name: 'corrections' })}>Corrections</button>
        <button onClick={() => nav({ name: 'issues' })}>Issues</button>
        <button onClick={() => nav({ name: 'export' })}>Export</button>
        <button onClick={() => nav({ name: 'activity' })}>Activity</button>
        <button onClick={() => nav({ name: 'references' })}>References</button>
        <button onClick={() => nav({ name: 'status' })}>Status</button>
        <span style={{ color: '#666' }}>decisions bind exact revisions — never slots</span>
        <span style={{ marginLeft: 'auto' }}>
          {reviewer ? <>reviewer: <b>{reviewer}</b> <button onClick={() => { clearSession(); setReviewer(null); }}>forget</button></>
            : <LoginPanel onLogin={(r) => setReviewer(r)} />}
        </span>
      </header>
      {!reviewer && <p><small>Read-only as orchestrator. Pair as a reviewer to mark issues and decide.</small></p>}
      {view.name === 'inbox' && <Inbox />}
      {view.name === 'packet' && <PacketView id={view.id} />}
      {view.name === 'compare' && <CompareView base={view.base} other={view.other} />}
      {view.name === 'issues' && <IssuesView revision={view.revision} />}
      {view.name === 'corrections' && <CorrectionsView />}
      {view.name === 'export' && <ExportView />}
      {view.name === 'activity' && <ActivityView />}
      {view.name === 'status' && <StatusView />}
      {view.name === 'references' && <ReferencesView />}
    </div>
  );
}

function LoginPanel({ onLogin }: { onLogin: (r: string) => void }) {
  // Reviewer bootstrap is operator-issued: the human pastes the single-use
  // pairing code from `framebound reviewer-pair` (operator console). The
  // browser never mints reviewer authority itself (anonymous pairing is 403).
  const [code, setCode] = useState('');
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const login = async () => {
    setErr(null); setBusy(true);
    try {
      const o = await api.reviewerOpen(code.trim());
      setSession(o.session_token, o.reviewer_id);
      onLogin(o.reviewer_id);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <span>
      <label>pairing code <input value={code} onChange={(e) => setCode(e.target.value)} size={24} /></label>{' '}
      <button onClick={login} disabled={busy || !code.trim()}>{busy ? '…' : 'open session'}</button>
      <Err e={err} />
    </span>
  );
}

function useLoad<T>(key: string, fn: () => Promise<T>): { data: T | null; err: unknown; reload: () => void } {
  const [data, setData] = useState<T | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let live = true;
    setErr(null);
    fn().then((d) => { if (live) setData(d); }).catch((e) => { if (live) setErr(e); });
    return () => { live = false; };
  }, [key, n]);
  return { data, err, reload: () => setN((x) => x + 1) };
}

function Inbox() {
  const packets = useLoad('packets', api.packets);
  const project = useLoad('project', api.project);
  const corrections = useLoad('corrections-open', () => api.corrections('open'));
  if (packets.err) return <Err e={packets.err} />;
  if (!packets.data) return <p>Loading…</p>;
  const list = packets.data.packets ?? [];
  return (
    <section>
      <h2>Project inbox</h2>
      <p>{String(project.data?.summary?.clip_revisions ?? '?')} revisions · {list.length} packets ·{' '}
        {String(project.data?.summary?.open_corrections ?? corrections.data?.open?.length ?? '?')} open corrections</p>
      {list.length === 0 && <p>No review packets yet. Evaluate a clip, then create a packet.</p>}
      <ul>
        {list.map((p: Record<string, unknown>) => {
          const pid = String(p.id);
          const cmp = typeof p.comparison_revision_id === 'string' ? p.comparison_revision_id : '';
          const issues = Array.isArray(p.issue_ids) ? p.issue_ids.length : 0;
          const uncovered = Array.isArray(p.unresolved_coverage) ? p.unresolved_coverage.length : 0;
          return (
            <li key={pid}>
              <button onClick={() => nav({ name: 'packet', id: pid })}>{pid}</button>{' '}
              <small>{String(p.intent)} · revision {String(p.clip_revision_id)} ·
                issues {issues} · uncovered {uncovered}</small>
              {cmp !== '' && (
                <button onClick={() => nav({ name: 'compare', base: cmp, other: String(p.clip_revision_id) })}>
                  compare
                </button>)}
            </li>);
        })}
      </ul>
      <h3>Open corrections</h3>
      {corrections.err ? <Err e={corrections.err} /> : <pre>{JSON.stringify(corrections.data?.open ?? corrections.data, null, 1)}</pre>}
    </section>
  );
}

/** Preload + cache decoded media; guard stale callbacks; surface media errors. */
function usePreload(urls: string[]): { imgs: Map<string, HTMLImageElement>; errors: Map<string, string> } {
  const [imgs, setImgs] = useState<Map<string, HTMLImageElement>>(new Map());
  const [errors, setErrors] = useState<Map<string, string>>(new Map());
  const key = useMemo(() => [...new Set(urls)].sort().join('|'), [urls.join('|')]);
  useEffect(() => {
    let live = true;
    const next = new Map<string, HTMLImageElement>();
    const errs = new Map<string, string>();
    const list = [...new Set(urls)];
    if (list.length === 0) { setImgs(next); setErrors(errs); return; }
    let done = 0;
    list.forEach((u) => {
      const img = new Image();
      img.onload = () => {
        if (!live) return;
        if ((img.naturalWidth || 0) === 0) errs.set(u, 'zero-size image');
        else next.set(u, img);
        if (++done === list.length) { setImgs(new Map(next)); setErrors(new Map(errs)); }
      };
      img.onerror = () => {
        if (!live) return;
        errs.set(u, 'failed to load media');
        if (++done === list.length) { setImgs(new Map(next)); setErrors(new Map(errs)); }
      };
      img.src = u;
    });
    return () => { live = false; };
  }, [key]);
  return { imgs, errors };
}

function StageCanvas({ nativeW, nativeH, draw, overlayLabel }: {
  nativeW: number; nativeH: number;
  draw: (ctx: CanvasRenderingContext2D, w: number, h: number) => void;
  overlayLabel?: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const ctx = c.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, nativeW, nativeH);
    draw(ctx, nativeW, nativeH);
  });
  return (
    <div>
      <canvas ref={ref} width={nativeW} height={nativeH}
        style={{ width: '100%', maxWidth: 560, aspectRatio: `${nativeW} / ${nativeH}`, imageRendering: 'pixelated', border: '1px solid #999', background: '#111' }} />
      {overlayLabel && <p><small>{overlayLabel}</small></p>}
    </div>
  );
}

function PacketView({ id }: { id: string }) {
  const { data: d, err, reload } = useLoad<PacketBundleDto>(`packet-${id}`, () => api.packet(id));
  const contract = (d?.contract ?? {}) as { timing?: { holds?: number[]; ticks_per_second?: number }; action?: { loop?: boolean }; canvas?: { width?: number; height?: number } };
  const holds = useMemo(() => contract.timing?.holds ?? [4], [d]);
  const tps = useMemo(() => contract.timing?.ticks_per_second ?? 60, [d]);
  const loop = useMemo(() => contract.action?.loop ?? true, [d]);
  const nativeW = useMemo(() => contract.canvas?.width ?? 64, [d]);
  const nativeH = useMemo(() => contract.canvas?.height ?? 64, [d]);
  const clock = usePresentationClock({ holds, tps, loop, resetKey: id });
  const frames = d?.frames ?? [];
  const urls = useMemo(() => frames.map((f) => f.asset_url), [d]);
  const { imgs, errors } = usePreload(urls);
  const [note, setNote] = useState('');
  const [category, setCategory] = useState('torso-pulse');
  const [roi, setRoi] = useState<[number, number, number, number] | null>(null);
  const [rangeText, setRangeText] = useState('');
  const [msg, setMsg] = useState('');
  const [opErr, setOpErr] = useState<unknown>(null);
  const drag = useRef<{ x0: number; y0: number } | null>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const total = totalTicks(holds);
  useEffect(() => { setRangeText(`${clock.tick}-${clock.tick}`); }, [id]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return;
      if (e.code === 'Space') { e.preventDefault(); clock.setPlaying(!clock.playing); }
      else if (e.key === 'ArrowRight') { clock.setPlaying(false); clock.stepTick(e.shiftKey ? holds[clock.slot] ?? 1 : 1); }
      else if (e.key === 'ArrowLeft') { clock.setPlaying(false); clock.stepTick(-(e.shiftKey ? holds[Math.max(0, clock.slot - 1)] ?? 1 : 1)); }
      else if (e.key === 'Home') { clock.setPlaying(false); clock.selectTick(0); }
      else if (e.key === 'End') { clock.setPlaying(false); clock.selectTick(total - 1); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  });

  if (err) return <Err e={err} />;
  if (!d) return <p>Loading packet…</p>;
  const cur = frames[clock.slot] ?? frames[0];
  const evalRes = d.evaluation?.results ?? [];
  const slotIssues = evalRes.filter((r) => r.scope === `slot ${clock.slot}` && r.outcome !== 'pass');
  const img = cur ? imgs.get(cur.asset_url) : undefined;
  const mediaErr = cur ? errors.get(cur.asset_url) : undefined;

  const onPointer = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = e.currentTarget;
    const rect = canvas.getBoundingClientRect();
    const p = toNative(e.clientX, e.clientY, rect, nativeW, nativeH,
      { scaleX: rect.width / nativeW, scaleY: rect.height / nativeH, offsetX: 0, offsetY: 0, mirrored: false });
    if (e.type === 'pointerdown') {
      clock.setPlaying(false); // pause while marking the issue
      drag.current = { x0: p.x, y0: p.y };
    }
    if (e.type === 'pointerup' && drag.current) {
      const l = Math.min(drag.current.x0, p.x), t = Math.min(drag.current.y0, p.y);
      const r = Math.max(drag.current.x0, p.x), b = Math.max(drag.current.y0, p.y);
      if (r - l >= 1 && b - t >= 1)
        setRoi([Math.floor(l), Math.floor(t), Math.ceil(Math.min(nativeW, r)), Math.ceil(Math.min(nativeH, b))]);
      drag.current = null;
    }
  };

  const parseRange = (): [number, number] | null => {
    const m = rangeText.match(/(\d+)\s*-\s*(\d+)/);
    if (!m) return null;
    const a = parseInt(m[1], 10), b = parseInt(m[2], 10);
    if (a > b || b >= total) return null;
    return [a, b];
  };

  const submitIssue = async () => {
    setMsg(''); setOpErr(null);
    const fr = parseRange();
    if (!fr) { setOpErr(new Error(`frame range must be start-end within 0..${total - 1}`)); return; }
    try {
      const out = await api.markIssue({
        clip_revision_id: d.revision.id as string, packet_id: id,
        frame_instance_id: cur?.frame_instance_id,
        frame_range: fr,
        roi: roi ? { left: roi[0], top: roi[1], right: roi[2], bottom: roi[3] } : null,
        note, category,
      });
      setMsg(`Issue recorded → correction task ${out.task_id}. Reload-safe.`);
      reload();
    } catch (e) { setOpErr(e); }
  };

  const decide = async (action: 'approve' | 'reject' | 'needs_changes') => {
    setMsg(''); setOpErr(null);
    try {
      await api.decide({
        action, clip_revision_id: d.revision.id as string, packet_id: id,
        expected_revision_id: d.revision.id, expected_evaluation_id: d.evaluation?.id, note,
      });
      setMsg(`Decision ${action} recorded for exactly ${d.revision.id}.`);
      reload();
    } catch (e) { setOpErr(e); }
  };

  return (
    <section>
      <h2 id="packet-title">Packet {id}</h2>
      <p><small>{String(d.packet.intent)} · revision {String(d.revision.id)} ·
        technical {d.evaluation?.technical_status} · coverage {d.evaluation?.coverage_status} ·
        decision {String(d.current_decision.acceptance ?? 'unreviewed')}</small></p>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 420px', maxWidth: 600 }}>
          <canvas
            ref={canvasRef}
            width={nativeW} height={nativeH}
            style={{ width: '100%', aspectRatio: `${nativeW} / ${nativeH}`, imageRendering: 'pixelated', border: '1px solid #999', cursor: 'crosshair', background: '#111' }}
            onPointerDown={onPointer} onPointerUp={onPointer}
          />
          <DrawOnCanvas canvasRef={canvasRef} img={img} roi={roi} nativeW={nativeW} nativeH={nativeH} />
          <div style={{ marginTop: 8 }}>
            <button onClick={() => clock.setPlaying(!clock.playing)}>{clock.playing ? 'Pause' : 'Play'}</button>
            <button onClick={() => { clock.setPlaying(false); clock.selectSlot((clock.slot + frames.length - 1) % frames.length); }}>Prev</button>
            <button onClick={() => { clock.setPlaying(false); clock.selectSlot((clock.slot + 1) % frames.length); }}>Next</button>
            <label> Speed <input type="number" value={clock.speed} min={0.1} max={4} step={0.1}
              onChange={(e) => clock.setSpeed(parseFloat(e.target.value) || 1)} style={{ width: 60 }} />×</label>
            <button onClick={() => { clock.setPlaying(false); clock.stepTick(-1); }}>-1 tick</button>
            <button onClick={() => { clock.setPlaying(false); clock.stepTick(1); }}>+1 tick</button>
          </div>
          <p id="tick-readout">tick {clock.tick} / {total} · frame {clock.slot}{cur ? ` · phase ${cur.phase} · hold ${cur.hold_ticks}` : ''}</p>
          {mediaErr ? <p role="alert">Media error on frame {clock.slot}: {mediaErr}</p>
            : !img && cur ? <p>Loading frame media…</p> : null}
          <p><small>Drag on the stage to set an ROI (native px). Playback pauses while marking. Space/arrows step.</small></p>
          {cur && <p><small>frame pixels: <img id="frame-img" src={cur.asset_url} alt={`frame ${clock.slot}`} width={64} height={64} style={{ imageRendering: 'pixelated', verticalAlign: 'middle' }} /> {cur.asset_id}</small></p>}
        </div>
        <div style={{ minWidth: 300, flex: '1 1 300px' }}>
          <h3>Findings · frame {clock.slot}</h3>
          {slotIssues.length === 0 ? <p>No failing findings on this frame.</p> : (
            <ul>{slotIssues.map((r, i) => (
              <li key={i}><b>{r.constraint_id}</b> ({r.outcome}): {r.reason}</li>))}</ul>)}
          <h3>Coverage</h3>
          <p><small>{d.evaluation?.coverage_status} · unresolved: {((d.packet.unresolved_coverage as string[] | undefined) ?? []).join(', ') || 'none'}</small></p>
          <h3>Mark an issue</h3>
          <label>Category <input value={category} onChange={(e) => setCategory(e.target.value)} /></label><br />
          <label>Frame range <input value={rangeText} onChange={(e) => setRangeText(e.target.value)} style={{ width: 90 }} /></label>
          <span> ROI {roi ? roi.join(',') : '(drag on stage)'}</span><br />
          <label>Note <input value={note} onChange={(e) => setNote(e.target.value)} size={36} /></label><br />
          <button onClick={submitIssue} disabled={!getToken()}>Send to model</button>
          {!getToken() && <small> pair as reviewer first</small>}
          <h3>Decision (exact revision {String(d.revision.id)})</h3>
          <button onClick={() => decide('approve')} disabled={!getToken()}>Approve</button>{' '}
          <button onClick={() => decide('reject')} disabled={!getToken()}>Reject</button>{' '}
          <button onClick={() => decide('needs_changes')} disabled={!getToken()}>Needs work</button>
          {typeof d.packet.comparison_revision_id === 'string' && d.packet.comparison_revision_id && (
            <button onClick={() => nav({ name: 'compare', base: d.packet.comparison_revision_id as string, other: String(d.revision.id) })}>
              Compare with baseline
            </button>)}
          {msg && <p>{msg}</p>}
          <Err e={opErr} />
          <p><button onClick={() => nav({ name: 'issues', revision: String(d.revision.id) })}>Open issue detail</button></p>
          <p><img src={api.contactSheetUrl(id)} alt="contact sheet" style={{ maxWidth: '100%', imageRendering: 'pixelated' }} /></p>
        </div>
      </div>
      <h3>Frames</h3>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {frames.map((f, i) => (
          <img key={f.frame_instance_id} src={f.asset_url} alt={`frame ${i}`} width={48} height={48}
            style={{ imageRendering: 'pixelated', border: i === clock.slot ? '2px solid #f0a020' : '1px solid #ccc', cursor: 'pointer', aspectRatio: '1 / 1' }}
            onClick={() => { clock.setPlaying(false); clock.selectSlot(i); }} />
        ))}
      </div>
    </section>
  );
}

function DrawOnCanvas({ canvasRef, img, roi, nativeW, nativeH }: {
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  img: HTMLImageElement | undefined;
  roi: [number, number, number, number] | null;
  nativeW: number; nativeH: number;
}) {
  useEffect(() => {
    const c = canvasRef.current;
    if (!c) return;
    const ctx = c.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, nativeW, nativeH);
    if (img && img.naturalWidth > 0) ctx.drawImage(img, 0, 0, nativeW, nativeH);
    if (roi) {
      ctx.strokeStyle = '#ff5a5a'; ctx.lineWidth = Math.max(1, nativeW / 128);
      ctx.strokeRect(roi[0] + 0.5, roi[1] + 0.5, roi[2] - roi[0], roi[3] - roi[1]);
    }
  });
  return null;
}

function CompareView({ base, other }: { base: string; other: string }) {
  const { data: d, err, reload } = useLoad<CompareBundleDto>(`compare-${base}-${other}`, () => api.compare(base, other));
  const [mode, setMode] = useState<'side' | 'blink' | 'diff'>('side');
  const [slot, setSlot] = useState(0);
  const [blinkOn, setBlinkOn] = useState(true);
  const [diffPct, setDiffPct] = useState<string>('');
  const [diffErr, setDiffErr] = useState('');
  useEffect(() => {
    if (mode !== 'blink') return;
    const t = setInterval(() => setBlinkOn((v) => !v), 500);
    return () => clearInterval(t);
  }, [mode]);
  const urls = useMemo(() => [...(d?.base.frames ?? []).map((f) => f.asset_url), ...(d?.other.frames ?? []).map((f) => f.asset_url)], [d]);
  const { imgs, errors } = usePreload(urls);

  useEffect(() => {
    setDiffPct(''); setDiffErr('');
    if (mode !== 'diff' || !d) return;
    const bf = d.base.frames[slot], of = d.other.frames[slot];
    const bi = bf ? imgs.get(bf.asset_url) : undefined;
    const oi = of ? imgs.get(of.asset_url) : undefined;
    if (!bi || !oi) { if (bf && of && (errors.get(bf.asset_url) || errors.get(of.asset_url))) setDiffErr('media failed to load'); return; }
    try {
      const w = bi.naturalWidth, h = bi.naturalHeight;
      const c = document.createElement('canvas');
      c.width = w; c.height = h;
      const ctx = c.getContext('2d', { willReadFrequently: true });
      if (!ctx) return;
      ctx.drawImage(bi, 0, 0);
      ctx.globalCompositeOperation = 'difference';
      ctx.drawImage(oi, 0, 0, w, h);
      const px = ctx.getImageData(0, 0, w, h).data;
      let sum = 0;
      for (let i = 0; i < px.length; i += 4) sum += px[i] + px[i + 1] + px[i + 2];
      setDiffPct(`${((sum / (px.length / 4)) / (3 * 255) * 100).toFixed(2)}%`);
    } catch (e) { setDiffErr(String(e)); }
  }, [mode, d, slot, imgs, errors]);

  if (err) return <Err e={err} />;
  if (!d) return <p>Loading comparison…</p>;
  const slots = Math.max(d.base.frames.length, d.other.frames.length);
  const bf = d.base.frames[Math.min(slot, d.base.frames.length - 1)];
  const of = d.other.frames[Math.min(slot, d.other.frames.length - 1)];
  return (
    <section>
      <h2 id="compare-title">Compare</h2>
      <p><small>baseline {base} ({d.base.technical_status}) vs candidate {other} ({d.other.technical_status}) ·
        {d.timing_equal ? 'identical timing: frame index equality is synchronization' : d.timing_note}</small></p>
      {!d.timing_equal && <p role="alert">{d.timing_note}</p>}
      <label>Mode <select value={mode} onChange={(e) => setMode(e.target.value as 'side' | 'blink' | 'diff')}>
        <option value="side">side-by-side</option><option value="blink">blink</option><option value="diff">difference</option>
      </select></label>{' '}
      <label>Frame <input id="compare-slot" type="number" value={slot} min={0} max={slots - 1}
        onChange={(e) => setSlot(Math.max(0, Math.min(slots - 1, parseInt(e.target.value) || 0)))} /></label>{' '}
      <button onClick={() => nav({ name: 'inbox' })}>Back</button>
      <div style={{ display: 'flex', gap: 16, marginTop: 12, flexWrap: 'wrap' }}>
        {(mode === 'side' || (mode === 'blink' && blinkOn) || mode === 'diff') && bf && (
          <figure style={{ margin: 0 }}>
            <img id="compare-base-img" src={bf.asset_url} alt={`baseline frame ${slot}`} style={{ imageRendering: 'pixelated', width: 256, aspectRatio: '1 / 1', border: '1px solid #999' }} />
            <figcaption><small>baseline {bf.asset_id} · slot {bf.slot} · phase {bf.phase}</small></figcaption>
          </figure>)}
        {(mode === 'side' || (mode === 'blink' && !blinkOn)) && of && (
          <figure style={{ margin: 0 }}>
            <img id="compare-other-img" src={of.asset_url} alt={`candidate frame ${slot}`} style={{ imageRendering: 'pixelated', width: 256, aspectRatio: '1 / 1', border: '1px solid #999' }} />
            <figcaption><small>candidate {of.asset_id} · slot {of.slot} · phase {of.phase}</small></figcaption>
          </figure>)}
        {mode === 'diff' && <p id="diff-readout">mean abs diff {diffPct || '…'} {diffErr && `(error: ${diffErr})`}</p>}
      </div>
    </section>
  );
}

function IssuesView({ revision }: { revision?: string }) {
  const [rev, setRev] = useState(revision ?? '');
  const { data, err, reload } = useLoad<IssueDetailDto[]>(`issues-${rev}`, () => api.issues(rev || undefined));
  const [packets, setPackets] = useState<Record<string, unknown>[]>([]);
  useEffect(() => { api.packets().then((p) => setPackets(p.packets)).catch(() => {}); }, []);
  const [msg, setMsg] = useState('');
  const [opErr, setOpErr] = useState<unknown>(null);
  if (err) return <Err e={err} />;
  const packetFor = (clipId: string) => packets.find((p) => p.clip_revision_id === clipId) as Record<string, unknown> | undefined;
  const act = async (fn: () => Promise<unknown>, ok: string) => {
    setMsg(''); setOpErr(null);
    try { await fn(); setMsg(ok); reload(); } catch (e) { setOpErr(e); }
  };
  return (
    <section>
      <h2>Issues {rev && <>on {rev}</>}</h2>
      <label>Revision <input value={rev} onChange={(e) => setRev(e.target.value)} size={20} /></label>
      {msg && <p>{msg}</p>}
      <Err e={opErr} />
      {!data ? <p>Loading…</p> : data.length === 0 ? <p>No issues recorded{rev ? ' on this revision' : ''}.</p> : (
        <ul>
          {data.map((iss) => (
            <li key={iss.event_id} style={{ marginBottom: 12 }}>
              <b>{iss.category}</b> · {iss.task_status ?? 'no task'} · acceptance {iss.current_acceptance}<br />
              <small>ROI {iss.roi ? [iss.roi.left, iss.roi.top, iss.roi.right, iss.roi.bottom].join(',') : '—'} ·
                range {iss.frame_range && iss.frame_range.length === 2 ? iss.frame_range.join('-') : '—'} ·
                coverage {iss.coverage} · {iss.note}</small>
              {iss.findings.length > 0 && (
                <ul>{iss.findings.map((f, i) => <li key={i}><small>{f.constraint_id} ({f.outcome}): {f.reason}</small></li>)}</ul>)}
              {iss.attempts.length > 0 && (
                <p><small>attempts: {iss.attempts.map((a) => `${a.id.slice(0, 12)}…=${a.result}`).join(' · ')}</small></p>)}
              {iss.candidate_revisions.length > 0 && (
                <ul>{iss.candidate_revisions.map((c, i) => {
                  const pkt = packetFor(String(c.revision_id));
                  return (
                    <li key={i}><small>candidate {String(c.revision_id)} ({String(c.technical_status)})
                      {pkt ? <> · <button disabled={!getToken()} onClick={() => act(
                        () => api.resolveIssue(iss.event_id, { replacement_revision_id: String(c.revision_id), packet_id: String(pkt.id) }),
                        `Resolved against ${c.revision_id}.`)}>Resolve with this</button></> : ' · no comparison packet yet'}</small></li>);
                })}</ul>)}
              {iss.task_status === 'resolved' && (
                <button disabled={!getToken()} onClick={() => act(
                  () => api.reopenIssue(iss.event_id, { note: 'reopened from desk' }), 'Reopened.')}>Reopen</button>)}
              {iss.resolution_event_id && <small> resolution {iss.resolution_event_id}</small>}
            </li>))}
        </ul>)}
    </section>
  );
}

function CorrectionsView() {
  const [status, setStatus] = useState('all');
  const { data, err, reload } = useLoad(`corrections-${status}`, () => api.corrections(status));
  const [detail, setDetail] = useState<string | null>(null);
  const det = useLoad<TaskStatusDto | null>(`task-${detail}`, () => (detail ? api.correctionGet(detail) : Promise.resolve(null)));
  return (
    <section>
      <h2>Correction queue</h2>
      <label>Status <select value={status} onChange={(e) => setStatus(e.target.value)}>
        {['all', 'open', 'reopened', 'claimed', 'attempting', 'awaiting_comparison', 'blocked', 'resolved', 'cancelled'].map((s) => (
          <option key={s} value={s}>{s}</option>))}
      </select></label>{' '}
      <button onClick={reload}>Refresh</button>
      {err ? <Err e={err} /> : !data ? <p>Loading…</p> : (
        <ul id="task-list">
          {((data.tasks ?? data.open ?? []) as Record<string, unknown>[]).map((t) => (
            <li key={String(t.id)}>{String(t.id)} · {String(t.status)} · baseline {String(t.baseline_revision_id)}{' '}
              <button onClick={() => setDetail(String(t.id))}>status</button></li>))}
        </ul>)}
      {det.data ? <pre>{JSON.stringify(det.data, null, 1)}</pre> : null}
      {det.err ? <Err e={det.err} /> : null}
    </section>
  );
}

function ExportView() {
  const [name, setName] = useState('desk-snapshot');
  const [revisions, setRevisions] = useState('');
  const [procedural, setProcedural] = useState(false);
  const [result, setResult] = useState<unknown>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const build = async () => {
    setErr(null); setResult(null); setBusy(true);
    try {
      const revs = revisions.split(',').map((s) => s.trim()).filter(Boolean);
      const r = await api.buildExport(name.trim(), revs, { include_procedural_positives: procedural });
      setResult(r);
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <section>
      <h2>Training export</h2>
      <label>Name <input value={name} onChange={(e) => setName(e.target.value)} /></label><br />
      <label>Revisions (comma-separated) <input value={revisions} onChange={(e) => setRevisions(e.target.value)} size={50} /></label><br />
      <label><input type="checkbox" checked={procedural} onChange={(e) => setProcedural(e.target.checked)} /> include procedural positives (labeled research otherwise)</label><br />
      <button onClick={build} disabled={busy}>{busy ? 'building…' : 'Build + validate'}</button>
      <Err e={err} />
      {result ? <pre>{JSON.stringify(result, null, 1)}</pre> : null}
    </section>
  );
}

function ActivityView() {
  const [events, setEvents] = useState<{ id: string; action: string; actor_id: string; clip_revision_id: string; created_at: string; note: string }[]>([]);
  const [cursor, setCursor] = useState<string | undefined>(() => {
    try { return localStorage.getItem('fb.activity_cursor') || undefined; } catch { return undefined; }
  });
  const [live, setLive] = useState(true);
  const [err, setErr] = useState<unknown>(null);
  const poll = useCallback(async () => {
    try {
      const page = await api.activity(cursor, 200);
      if (page.events.length > 0) {
        setEvents((prev) => [...prev, ...page.events.filter((e) => !prev.some((p) => p.id === e.id))].slice(-300));
        if (page.cursor) {
          setCursor(page.cursor);
          try { localStorage.setItem('fb.activity_cursor', page.cursor); } catch { /* noop */ }
        }
      }
      setErr(null);
    } catch (e) { setErr(e); setLive(false); }
  }, [cursor]);
  useEffect(() => {
    poll();
    const t = setInterval(() => { if (live) poll(); }, 5000);
    return () => clearInterval(t);
  }, [poll, live]);
  return (
    <section>
      <h2>Activity</h2>
      <p><small>{live ? 'live (polling, DB-backed — survives restarts)' : 'polling paused after an error'} · cursor {cursor ?? '—'}</small>{' '}
        <button onClick={() => { setLive(true); poll(); }}>Resume</button></p>
      <Err e={err} />
      <ul>{events.slice(-50).reverse().map((e) => (
        <li key={e.id}><small>{e.created_at} · {e.action} · {e.actor_id} · {e.clip_revision_id} · {e.note}</small></li>))}</ul>
    </section>
  );
}

function StatusView() {
  // Concise capability truth + pending model work with evidence links.
  // A review tool, not a manual editor: open items go to the model's queue.
  const caps = useLoad('capabilities', api.capabilities);
  const open = useLoad('corrections-open', () => api.corrections('open'));
  const awaiting = useLoad('corrections-awaiting', () => api.corrections('awaiting_comparison,blocked,attempting,claimed'));
  return (
    <section>
      <h2>Status</h2>
      <Err e={caps.err} />
      <Err e={open.err} />
      <h3>Pending model work</h3>
      {!open.data ? <p>Loading…</p> : ((open.data.open ?? []) as Record<string, unknown>[]).length === 0
        ? <p><small>No open correction tasks.</small></p>
        : <ul>{((open.data.open ?? []) as Record<string, unknown>[]).map((t) => (
          <li key={String(t.id)}><small><button onClick={() => nav({ name: 'corrections' })}>{String(t.id)}</button> open</small></li>))}</ul>}
      {!awaiting.data ? null : ((awaiting.data.tasks ?? []) as Record<string, unknown>[]).length === 0 ? null : (
        <ul>{((awaiting.data.tasks ?? []) as Record<string, unknown>[]).map((t) => (
          <li key={String(t.id)}><small><button onClick={() => nav({ name: 'corrections' })}>{String(t.id)}</button> {String(t.status)}</small></li>))}</ul>)}
      <h3>Evidence</h3>
      <p><small>Checked-in release evidence. Test reviewers do not represent entrant artistic acceptance.</small></p>
      {caps.data && <table><thead><tr><th>Capability</th><th>Implemented</th><th>Counterexamples</th><th>Public workflow</th><th>Participant live</th><th>Entrant review</th></tr></thead>
        <tbody>{caps.data.evidence.map(e => <tr key={e.capability}><td>{e.capability}</td>
          {[e.implemented,e.negative_tested,e.public_integrated,e.live_observed,e.human_reviewed].map((value,i) => <td key={i}>{value === null ? 'N/A' : value ? 'Demonstrated' : 'Pending'}</td>)}
        </tr>)}</tbody></table>}
      <h3>Capabilities</h3>
      {!caps.data ? <p>Loading…</p> : (
        <table><thead><tr><th>transport</th><th>operation</th><th>status</th><th>note</th></tr></thead>
          <tbody>{caps.data.rows.map((r, i) => (
            <tr key={i}><td><small>{r.transport}</small></td><td><small>{r.operation}</small></td>
              <td><small>{r.status}</small></td><td><small>{r.note}</small></td></tr>))}</tbody>
        </table>)}
    </section>
  );
}

function ReferencesView() {
  const [data,setData] = useState<Awaited<ReturnType<typeof api.references>> | null>(null);
  const [error,setError] = useState<unknown>(null);
  const [busy,setBusy] = useState<string | null>(null);
  const refresh = useCallback(() => api.references().then(setData).catch(setError),[]);
  useEffect(() => { void refresh(); },[refresh]);
  return <section aria-label="Reference proposals"><h2>Reference proposals</h2><Err e={error}/>
    {!data && <p>Loading references…</p>}
    {data && data.motion_guides.length === 0 && <p>No guide proposals.</p>}
    {data?.motion_guides.map(guide => {
      const char=data.character_revisions.find(c=>c.id===guide.character_revision_id);
      const approval=data.reference_approvals.find(a=>a.character_revision_id===guide.character_revision_id && a.motion_guide_id===guide.id && data.active_approval_ids.includes(a.id));
      const approved=Boolean(approval);
      return <article key={guide.id} style={{borderTop:'1px solid #ccc',padding:'20px 0'}}>
        <h3>{guide.character_revision_id} · {guide.id}</h3>
        <h4>Automatic repair authority</h4>
        {guide.repair_policy ? <dl style={{display:'grid',gridTemplateColumns:'max-content 1fr',gap:'6px 20px',fontSize:14}}>
          <dt>Allowed operations</dt><dd>{Array.isArray(guide.repair_policy.operators) ? guide.repair_policy.operators.join(', ') : 'None'}</dd>
          <dt>Translation limit</dt><dd>{String(guide.repair_policy.translation_budget_px)} native pixels</dd>
          <dt>Attempts per phase</dt><dd>{String(guide.repair_policy.max_local_attempts)}</dd>
          <dt>Compute steps</dt><dd>{String(guide.repair_policy.max_compute_steps)}</dd>
          <dt>Provider dispatches</dt><dd>{guide.repair_policy.generation_allowed ? String(guide.repair_policy.max_provider_dispatches) : 'Disabled'}</dd>
        </dl> : <p>Manual work only</p>}
        {guide.source_calibration && <p>Fixed source conversion: {String(guide.source_calibration.source_width)} × {String(guide.source_calibration.source_height)}, crop {JSON.stringify(guide.source_calibration.crop)}, nearest neighbour.</p>}
        <div style={{display:'flex',gap:12,flexWrap:'wrap',margin:'16px 0'}}>{guide.entries.map(entry => <div key={'scope-'+entry.phase} style={{display:'grid',gridTemplateColumns:'64px 64px',gap:4,border:'1px solid #ddd',padding:8}}>
          <small style={{gridColumn:'1 / -1'}}>{entry.phase} · editable / protected</small>
          {entry.editable_mask_asset_id && <img width={64} height={64} style={{imageRendering:'pixelated'}} src={api.assetUrl(entry.editable_mask_asset_id)} alt={entry.phase+' editable mask'} />}
          {entry.protected_mask_asset_id && <img width={64} height={64} style={{imageRendering:'pixelated'}} src={api.assetUrl(entry.protected_mask_asset_id)} alt={entry.phase+' protected mask'} />}
        </div>)}</div>
        <div style={{display:'flex',gap:24,flexWrap:'wrap'}}>
          {char && [['Identity',char.identity_asset_ids],['Style',char.style_asset_ids]].map(([label,ids]) =>
            <div key={String(label)}><h4>{String(label)}</h4>{(ids as string[]).map(id =>
              <figure key={id} style={{display:'inline-block',margin:8}}><img alt={`${label}: ${id}`} src={api.assetUrl(id)} width={128} height={128} style={{objectFit:'contain',imageRendering:'pixelated',background:'#eee'}}/><figcaption>{id}</figcaption></figure>)}</div>)}
          <div><h4>Phase guide</h4>{guide.entries.map(entry => <figure key={entry.phase} style={{display:'inline-block',margin:8}}>
            <img alt={`Phase ${entry.phase}`} src={api.assetUrl(entry.asset_id)} width={128} height={128} style={{objectFit:'contain',imageRendering:'pixelated',background:'#eee'}}/><figcaption>{entry.phase}</figcaption></figure>)}</div>
        </div>
        <button disabled={approved || !getReviewer() || busy!==null} onClick={async()=>{
          setBusy(guide.id);setError(null);
          try { await api.approveReferences(guide.character_revision_id,guide.id,`ref-${crypto.randomUUID()}`);await refresh(); }
          catch(e){setError(e);}finally{setBusy(null);}
        }}>{approved?'References approved':busy===guide.id?'Recording…':'Approve these references'}</button>
        {approval && <button disabled={!getReviewer() || busy===guide.id} onClick={async()=>{
          setBusy(guide.id);setError(null);
          try {await api.revokeReference(approval.id,`revoke-${crypto.randomUUID()}`);await refresh();}
          catch(e){setError(e);}finally{setBusy(null);}
        }}>Revoke reference approval</button>}

      </article>;
    })}
  </section>;
}
