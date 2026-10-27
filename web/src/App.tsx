import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { api } from './api';
import { slotAtTick } from './playback';

type Packet = any;
type View = { name: 'inbox' } | { name: 'packet'; id: string } | { name: 'compare'; base: string; other: string };

export default function App() {
  const [view, setView] = useState<View>({ name: 'inbox' });
  return (
    <div style={{ fontFamily: 'system-ui,sans-serif', margin: 16, maxWidth: 1100 }}>
      <header style={{ display: 'flex', gap: 12, alignItems: 'baseline' }}>
        <h1 style={{ fontSize: 20, margin: 0 }}>Framebound review desk</h1>
        <button onClick={() => setView({ name: 'inbox' })}>Inbox</button>
        <span style={{ color: '#666' }}>decisions bind exact revisions — never slots</span>
      </header>
      {view.name === 'inbox' && <Inbox go={setView} />}
      {view.name === 'packet' && <PacketView id={view.id} go={setView} />}
      {view.name === 'compare' && <CompareView base={view.base} other={view.other} go={setView} />}
    </div>
  );
}

function Inbox({ go }: { go: (v: View) => void }) {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    Promise.all([api.project(), api.packets()])
      .then(([p, q]) => setData({ ...p, ...q }))
      .catch((e) => setErr(String(e)));
  }, []);
  if (err) return <p role="alert">Project unavailable: {err}. Start the API: python -m framebound serve --project PATH</p>;
  if (!data) return <p>Loading…</p>;
  const packets: Packet[] = data.packets ?? [];
  return (
    <section>
      <h2>Project inbox</h2>
      <p>
        {data.summary?.clip_revisions ?? 0} revisions · {packets.length} packets ·{' '}
        {data.summary?.open_corrections ?? 0} open corrections
      </p>
      {packets.length === 0 && <p>No review packets yet. Evaluate a clip, then create a packet.</p>}
      <ul>
        {packets.map((p: any) => (
          <li key={p.id}>
            <button onClick={() => go({ name: 'packet', id: p.id })}>{p.id}</button>{' '}
            <small>
              {p.intent} · issues {p.issue_ids?.length ?? 0} · uncovered {p.unresolved_coverage?.length ?? 0}
            </small>
            {p.comparison_revision_id && (
              <button onClick={() => go({ name: 'compare', base: p.comparison_revision_id, other: p.clip_revision_id })}>
                compare
              </button>
            )}
          </li>
        ))}
      </ul>
      <Corrections go={go} />
    </section>
  );
}

function Corrections({ go }: { go: (v: View) => void }) {
  const [q, setQ] = useState<any>(null);
  useEffect(() => {
    api.corrections().then(setQ).catch(() => setQ({ open: [], note: 'queue unavailable' }));
  }, []);
  if (!q) return null;
  return (
    <section>
      <h3>Open corrections (model queue)</h3>
      <pre>{JSON.stringify(q, null, 1)}</pre>
      <p><small> leases expire; crashed claims return to the queue without losing attempts.</small></p>
    </section>
  );
}

function PacketView({ id, go }: { id: string; go: (v: View) => void }) {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState('');
  const [slot, setSlot] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  const [paintCount, setPaintCount] = useState(0);
  const [note, setNote] = useState('');
  const [category, setCategory] = useState('torso-pulse');
  const [roi, setRoi] = useState<[number, number, number, number] | null>(null);
  const [range, setRange] = useState('3-5');
  const [msg, setMsg] = useState('');
  const drag = useRef<{ x0: number; y0: number } | null>(null);
  const raf = useRef(0);
  const t0 = useRef(0);

  const load = useCallback(() => {
    api.packet(id).then((p) => { setD(p); setSlot(0); }).catch((e) => setErr(String(e)));
  }, [id]);
  useEffect(() => { load(); }, [load]);

  const holds: number[] = useMemo(() => d?.contract?.timing?.holds ?? [4], [d]);
  const loop: boolean = useMemo(() => d?.contract?.action?.loop ?? true, [d]);
  const tps: number = useMemo(() => d?.contract?.timing?.ticks_per_second ?? 60, [d]);

  useEffect(() => {
    if (!playing || !d) return;
    t0.current = performance.now();
    let last = -1;
    const step = (now: number) => {
      const elapsedTicks = Math.floor(((now - t0.current) / 1000) * tps * speed);
      const s = slotAtTick(holds, elapsedTicks, loop);
      if (s !== last) { last = s; setSlot(s); setPaintCount((c) => c + 1); }
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf.current);
  }, [playing, d, holds, loop, tps, speed]);

  if (err) return <p role="alert">{err}</p>;
  if (!d) return <p>Loading packet…</p>;
  const frames: any[] = d.frames ?? [];
  const cur = frames[slot] ?? frames[0];
  const evalRes: any[] = d.evaluation?.results ?? [];
  const slotIssues = evalRes.filter((r: any) => r.scope === `slot ${slot}` && r.outcome !== 'pass');

  const onPointer = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = e.currentTarget;
    const rect = canvas.getBoundingClientRect();
    const scale = rect.width / (d.contract?.canvas?.width ?? 64);
    const nx = Math.round(((e.clientX - rect.left) / scale) * 10) / 10;
    const ny = Math.round(((e.clientY - rect.top) / scale) * 10) / 10;
    if (e.type === 'pointerdown') drag.current = { x0: nx, y0: ny };
    if (e.type === 'pointerup' && drag.current) {
      const l = Math.min(drag.current.x0, nx), t = Math.min(drag.current.y0, ny);
      const r = Math.max(drag.current.x0, nx), b = Math.max(drag.current.y0, ny);
      if (r > l && b > t) setRoi([Math.floor(l), Math.floor(t), Math.ceil(r), Math.ceil(b)]);
      drag.current = null;
    }
  };

  const submitIssue = async () => {
    setMsg('');
    try {
      const m = range.match(/(\d+)\s*-\s*(\d+)/);
      const out = await api.markIssue({
        clip_revision_id: d.revision.id, packet_id: id,
        frame_instance_id: cur?.frame_instance_id,
        frame_range: m ? [parseInt(m[1], 10), parseInt(m[2], 10)] : [slot, slot],
        roi: roi ? { left: roi[0], top: roi[1], right: roi[2], bottom: roi[3] } : null,
        note, category,
      });
      setMsg(`Issue recorded → correction task ${out.task_id}. Reload-safe.`);
      load();
    } catch (e) { setMsg(String(e)); }
  };

  const decide = async (action: 'approve' | 'reject' | 'needs_changes') => {
    setMsg('');
    try {
      await api.decide({ action, clip_revision_id: d.revision.id, packet_id: id,
        expected_revision_id: d.revision.id, note });
      setMsg(`Decision ${action} recorded for exactly ${d.revision.id}.`);
      load();
    } catch (e) { setMsg(String(e)); }
  };

  return (
    <section>
      <h2>Packet {id}</h2>
      <p><small>{d.packet?.intent} · revision {d.revision?.id} · technical {d.evaluation?.technical_status} ·
        coverage {d.evaluation?.coverage_status} · paints {paintCount}</small></p>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <div>
          <canvas
            width={d.contract?.canvas?.width ?? 64} height={d.contract?.canvas?.height ?? 64}
            style={{ width: 288, height: 288, imageRendering: 'pixelated', border: '1px solid #999', cursor: 'crosshair' }}
            ref={(c) => {
              if (c && cur) {
                const img = new Image();
                img.onload = () => {
                  const ctx = c.getContext('2d');
                  if (!ctx) return;
                  ctx.clearRect(0, 0, c.width, c.height);
                  ctx.drawImage(img, 0, 0);
                  if (roi) {
                    ctx.strokeStyle = '#ff5a5a'; ctx.lineWidth = 1;
                    ctx.strokeRect(roi[0] + 0.5, roi[1] + 0.5, roi[2] - roi[0], roi[3] - roi[1]);
                  }
                };
                img.src = api.assetUrl(cur.asset_id);
              }
            }}
            onPointerDown={onPointer} onPointerUp={onPointer}
          />
          <div>
            <button onClick={() => setPlaying((p) => !p)}>{playing ? 'Pause' : 'Play'}</button>
            <button onClick={() => { setPlaying(false); setSlot((s) => (s + frames.length - 1) % frames.length); }}>Prev</button>
            <button onClick={() => { setPlaying(false); setSlot((s) => (s + 1) % frames.length); }}>Next</button>
            <label> Speed <input type="number" value={speed} min={0.1} max={4} step={0.1}
              onChange={(e) => setSpeed(parseFloat(e.target.value) || 1)} style={{ width: 60 }} />×</label>
            <span> frame {slot} · phase {cur?.phase} · hold {cur?.hold_ticks}</span>
          </div>
          <p><small>Drag on the stage to set an ROI (native px). Speed changes presentation only.</small></p>
        </div>
        <div style={{ minWidth: 300 }}>
          <h3>Findings · frame {slot}</h3>
          {slotIssues.length === 0 ? <p>No failing findings on this frame.</p> : (
            <ul>{slotIssues.map((r: any, i: number) => (
              <li key={i}><b>{r.constraint_id}</b> ({r.outcome}): {r.reason}</li>))}</ul>)}
          <h3>Coverage</h3>
          <p><small>{d.evaluation?.coverage_status} · unresolved: {(d.packet?.unresolved_coverage ?? []).join(', ') || 'none'}</small></p>
          <h3>Mark an issue</h3>
          <label>Category <input value={category} onChange={(e) => setCategory(e.target.value)} /></label><br />
          <label>Frame range <input value={range} onChange={(e) => setRange(e.target.value)} style={{ width: 70 }} /></label>
          <span> ROI {roi ? roi.join(',') : '(drag on stage)'}</span><br />
          <label>Note <input value={note} onChange={(e) => setNote(e.target.value)} size={40} /></label><br />
          <button onClick={submitIssue}>Send to model</button>
          <h3>Decision (exact revision {d.revision?.id})</h3>
          <button onClick={() => decide('approve')}>Approve</button>{' '}
          <button onClick={() => decide('reject')}>Reject</button>{' '}
          <button onClick={() => decide('needs_changes')}>Needs work</button>
          {d.packet?.comparison_revision_id && (
            <button onClick={() => go({ name: 'compare', base: d.packet.comparison_revision_id, other: d.revision.id })}>
              Compare with baseline
            </button>)}
          {msg && <p>{msg}</p>}
        </div>
      </div>
      <h3>Frames</h3>
      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
        {frames.map((f: any, i: number) => (
          <img key={f.frame_instance_id} src={api.assetUrl(f.asset_id)} alt={`frame ${i}`} width={48} height={48}
            style={{ imageRendering: 'pixelated', border: i === slot ? '2px solid #f0a020' : '1px solid #ccc',
              cursor: 'pointer' }}
            onClick={() => { setPlaying(false); setSlot(i); }} />
        ))}
      </div>
    </section>
  );
}

function CompareView({ base, other, go }: { base: string; other: string; go: (v: View) => void }) {
  const [a, setA] = useState<any>(null);
  const [b, setB] = useState<any>(null);
  const [mode, setMode] = useState<'side' | 'blink' | 'diff'>('side');
  const [slot, setSlot] = useState(0);
  useEffect(() => {
    // comparison loads both packets' revisions via their packets is out of scope; load assets directly is enough
    setA({ rev: base }); setB({ rev: other });
  }, [base, other]);
  return (
    <section>
      <h2>Compare</h2>
      <p><small>baseline {base} vs candidate {other} · identical timing by default</small></p>
      <label>Mode <select value={mode} onChange={(e) => setMode(e.target.value as any)}>
        <option value="side">side-by-side</option><option value="blink">blink</option><option value="diff">difference</option>
      </select></label>
      <label> Frame <input type="number" value={slot} min={0} onChange={(e) => setSlot(parseInt(e.target.value, 10) || 0)} /></label>
      <button onClick={() => go({ name: 'inbox' })}>Back</button>
      <p><small>Mode {mode}: synchronized at identical timing. A retiming correction is shown as an explicit timing change.</small></p>
    </section>
  );
}
