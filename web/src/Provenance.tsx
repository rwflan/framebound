import type { ProvenanceRecord } from './agent-model';

export function Provenance({ value }: { value?: ProvenanceRecord | null }) {
  const parent=value?.parent;
  const generators=value?.generations || [];
  return <section className="agent-finding" aria-label="Generation provenance">
    <strong>Generation provenance</strong>
    <dl><dt>Parent</dt><dd>{parent?.observed_model || 'Unknown'}{parent?.observed_version ? ` · ${parent.observed_version}` : ''}</dd>
      {parent && <><dt>Requested parent</dt><dd>{parent.requested_model}</dd>
        <dt>Harness</dt><dd>{[parent.harness,parent.harness_version].filter(Boolean).join(' ') || 'Unknown'}</dd>
        <dt>Contributor</dt><dd>{parent.contributor_effective} (requested {parent.contributor_requested})</dd>
        <dt>Parent evidence</dt><dd>{parent.evidence_source}</dd></>}
      <dt>Style board</dt><dd>{value?.style_board?.name || 'Unknown'}</dd>
      <dt>Image model</dt><dd>{generators.length ? [...new Set(generators.map(g=>g.observed_model || 'Unknown'))].join(', ') : 'Unknown'}</dd>
    </dl>
    {generators.map(g=><details key={g.id}><summary>{g.id} · {g.outcome} · {g.evidence_source}</summary>
      <p>Requested: {g.requested_model}<br/>Observed: {g.observed_model || 'Unknown'}{g.observed_version ? ` · ${g.observed_version}` : ''}</p>
      <p>Response: {g.response_id || 'Unknown'}</p>
      <strong>Supplied references ({g.conditioning.length})</strong>
      {g.conditioning.map((ref,index)=><figure key={`${g.id}:${index}`}>
        <a href={'/api/asset/'+encodeURIComponent(ref.asset_id)} target="_blank" rel="noreferrer">{index+1}. {ref.asset_id}</a>
        <figcaption>{ref.role} · {ref.conditioning_eligibility}<br/><small title={ref.byte_sha256}>SHA-256 {ref.byte_sha256.slice(0,16)}…</small></figcaption>
      </figure>)}
      {!g.conditioning.length && <p>No supplied reference images recorded.</p>}
    </details>)}
    {!value && <small>Attribution was not recorded for this revision.</small>}
  </section>;
}
