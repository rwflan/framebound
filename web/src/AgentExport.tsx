import { useMemo, useState } from 'react';
import { req } from './api';
import { Err } from './shared';
import type { AgentDeskData } from './agent-model';
type Preview={counts:Record<string,number>;trajectories:number;destination:string;exclusions:{frame_instance_id:string;reasons:string[]}[];withheld:{asset_id:string;reason:string}[];validation:string};
type Result={destination:string;validation:{ok:boolean;issues:string[];counts:Record<string,number>}};
export function AgentExport({data}:{data:AgentDeskData}){
  const [selected,setSelected]=useState<string[]>([]),[name,setName]=useState('training-export');
  const [automatic,setAutomatic]=useState(false),[procedural,setProcedural]=useState(false),[destination,setDestination]=useState('');
  const [preview,setPreview]=useState<Preview|null>(null),[result,setResult]=useState<Result|null>(null);
  const [error,setError]=useState<unknown>(null),[busy,setBusy]=useState(false);
  const selection=useMemo(()=>({name,run_ids:selected,include_automatically_verified:automatic,
    include_procedural_positives:procedural,policy_id:'agent-training-v1',destination:destination||null}),[name,selected,automatic,procedural,destination]);
  const [previewIdentity,setPreviewIdentity]=useState('');
  const freshPreview=previewIdentity===JSON.stringify(selection);
  async function execute(build=false){setBusy(true);setError(null);try{
    if(build){const value=await req<Result>('/v3/exports',{method:'POST',body:JSON.stringify(selection)});setResult(value);}
    else {const value=await req<Preview>('/v3/exports/preview',{method:'POST',body:JSON.stringify(selection)});setPreview(value);setPreviewIdentity(JSON.stringify(selection));setResult(null);}
  }catch(e){setError(e);}finally{setBusy(false);}}
  return <section className="agent-export"><header><h2>Export training data</h2><small>agent-training-v1</small></header><Err e={error}/>
    <form onSubmit={e=>{e.preventDefault();void execute();}}><div className="agent-export-selection">{data.projects.map(project=><fieldset key={project.id}><legend>{project.name}</legend>{data.runs.filter(run=>run.project_id===project.id).map(run=><label key={run.id}><input type="checkbox" disabled={!run.current_revision_id} checked={selected.includes(run.id)} onChange={e=>setSelected(s=>e.target.checked?[...s,run.id]:s.filter(id=>id!==run.id))}/><strong>{run.animation_id}</strong><small>{run.submission_ids.length} revisions · {run.lifecycle.replace(/_/g,' ')}</small></label>)}</fieldset>)}</div>
    <label>Snapshot name<input aria-label="Snapshot name" value={name} pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,63}" onChange={e=>setName(e.target.value)} required/></label>
    <label>Destination<input aria-label="Export destination" value={destination} onChange={e=>setDestination(e.target.value)} placeholder="Project exports directory"/></label>
    <label><input type="checkbox" checked={automatic} onChange={e=>setAutomatic(e.target.checked)}/>Include automatically verified examples in their separate view</label>
    <label><input type="checkbox" checked={procedural} onChange={e=>setProcedural(e.target.checked)}/>Include procedural fixtures as labeled training examples</label>
    <div className="toolbar"><button disabled={busy||!selected.length}>Preview export</button><button type="button" disabled={busy||!freshPreview||!preview} onClick={()=>void execute(true)}>Export snapshot</button></div></form>
    {preview && freshPreview && <section aria-label="Export preview"><dl className="facts">{Object.entries(preview.counts).map(([key,value])=><div key={key}><dt>{key.replace(/_/g,' ')}</dt><dd>{value}</dd></div>)}<div><dt>Correction trajectories</dt><dd>{preview.trajectories}</dd></div></dl><p>Destination: <code>{preview.destination}</code></p><p>{preview.validation}</p><details><summary>Exclusions and withheld pixels</summary>{preview.exclusions.map((e,i)=><p key={i}>{e.frame_instance_id}: {e.reasons.join(', ')}</p>)}{preview.withheld.map(e=><p key={e.asset_id}>{e.asset_id}: {e.reason}</p>)}</details></section>}
    {result && <section role="status" aria-label="Export validation"><strong>{result.validation.ok?'Snapshot validated':'Snapshot validation failed'}</strong><p>{result.destination}</p>{result.validation.issues.map((issue,i)=><p key={i}>{issue}</p>)}</section>}
  </section>;
}
