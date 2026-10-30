import { useEffect, useRef, useState } from "react";

export type HandoffData = {
  text: string;
  bundle: Record<string, unknown>;
  stale: boolean;
  reason: string | null;
  current_revision_id: string | null;
  current_feedback_id: string;
};

export function Handoff({ feedbackId }: { feedbackId: string }) {
  const [data, setData] = useState<HandoffData | null>(null);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [expanded, setExpanded] = useState(false);
  const text = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError(""); setStatus(""); setExpanded(false);
    fetch(`/v3/feedback/${encodeURIComponent(feedbackId)}`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error((await response.text()) || "Instructions unavailable");
        return response.json() as Promise<HandoffData>;
      }).then(setData).catch(error => {
        if (!controller.signal.aborted) setError(String(error));
      });
    return () => controller.abort();
  }, [feedbackId]);
  useEffect(() => {
    if (status !== "Copied") return;
    const timer = setTimeout(() => setStatus(""), 2500);
    return () => clearTimeout(timer);
  }, [status]);
  async function copy() {
    if (!data || data.stale) return;
    try {
      // Revalidate immediately before copying; a live submission may have arrived.
      const response = await fetch(`/v3/feedback/${encodeURIComponent(feedbackId)}`);
      if (!response.ok) throw new Error("Could not verify saved instructions");
      const fresh = await response.json() as HandoffData;
      setData(fresh);
      if (fresh.stale) { setStatus("Instructions changed — fetch current feedback"); return; }
      await navigator.clipboard.writeText(fresh.text);
      setStatus("Copied");
    } catch {
      setExpanded(true); setStatus("Copy unavailable — select the text or download");
      requestAnimationFrame(() => { text.current?.focus(); text.current?.select(); });
    }
  }
  if (error) return <p role="alert">{error}</p>;
  if (!data) return <small>Loading saved instructions…</small>;
  return <div className="saved-handoff">
    <div className="toolbar">
      <button type="button" onClick={() => void copy()} disabled={data.stale}>Copy instructions</button>
      <a href={`/v3/feedback/${encodeURIComponent(feedbackId)}/text`} download>Download text</a>
      {Boolean(data.bundle.baseline_revision_id) && <a href={`/v3/feedback/${encodeURIComponent(feedbackId)}/portable`} download>Download portable handoff</a>}
      <button type="button" onClick={() => setExpanded(value => !value)} aria-expanded={expanded}>View instructions</button>
      <span role="status" aria-live="polite">{status}</span>
    </div>
    {data.stale && <p role="alert">{data.reason}</p>}
    {expanded && <div>
      <textarea ref={text} aria-label="Saved instructions" value={data.text} readOnly rows={12} />
      <details><summary>Structured JSON</summary><pre>{JSON.stringify(data.bundle, null, 2)}</pre></details>
    </div>}
  </div>;
}
