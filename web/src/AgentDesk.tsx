import { useCallback, useEffect, useState } from 'react';
import { req } from './api';
import { AgentExport } from './AgentExport';
import { AgentWorkspace } from './AgentWorkspace';
import { Err, Icon, stamp, words } from './shared';
import { useAutomaticUpdates } from './useAutomaticUpdates';
import type { AgentBundle, AgentDeskData, Run } from './agent-model';
import './agent.css';

export function useAgentDesk() {
  const [data,setData]=useState<AgentDeskData|null>(null),[error,setError]=useState<unknown>(null);
  const [version,setVersion]=useState(0);
  const refresh=useCallback(()=>setVersion(v=>v+1),[]);
  useAutomaticUpdates(refresh);
  useEffect(()=>{const controller=new AbortController();req<AgentDeskData>('/v3/desk',{signal:controller.signal}).then(value=>{setData(value);setError(null);}).catch(e=>{if(!controller.signal.aborted)setError(e);});return()=>controller.abort();},[version]);
  return {data,error,refresh};
}

function route(){const [path,query]=location.hash.replace(/^#\/?/,'').split('?'),parts=path.split('/');return {export:parts[0]==='export',run:parts[0]==='run'?decodeURIComponent(parts[1]||''):'',revision:new URLSearchParams(query).get('revision')};}
export function AgentDesk({data,onChange}:{data:AgentDeskData;onChange:()=>void}) {
  const [selection,setSelection]=useState(route),[navigation,setNavigation]=useState<'interventions'|'timeline'>('interventions');
  const [source,setSource]=useState('all'),[query,setQuery]=useState('');
  const [bundle,setBundle]=useState<AgentBundle|null>(null),[error,setError]=useState<unknown>(null);
  const interventions=data.runs.filter(r=>r.needs_intervention);
  const [fallbackRun]=useState(()=>interventions[0]?.id||data.runs[data.runs.length-1]?.id);
  const run=data.runs.find(r=>r.id===(selection.run||fallbackRun));
  // Freeze the first inspected revision. Live updates never replace inspection or unsaved edits.
  const [inspected,setInspected]=useState(selection.revision||run?.current_revision_id||null);
  useEffect(()=>{const update=()=>{const next=route();setSelection(next);setInspected(next.revision);};window.addEventListener('hashchange',update);return()=>window.removeEventListener('hashchange',update);},[]);
  useEffect(()=>{if(!inspected && run?.current_revision_id)setInspected(run.current_revision_id);},[run?.id,run?.current_revision_id,inspected]);
  useEffect(()=>{
    if(!inspected){setBundle(null);return;}
    const controller=new AbortController();
    req<AgentBundle>(`/v3/desk/revisions/${encodeURIComponent(inspected)}`,{signal:controller.signal}).then(result=>{setBundle(result);setError(null);}).catch(e=>{if(!controller.signal.aborted)setError(e);});
    return()=>controller.abort();
  },[inspected,run?.version]);
  function open(r:Run,rid:string|null=r.current_revision_id){location.hash=`/run/${encodeURIComponent(r.id)}${rid?'?revision='+encodeURIComponent(rid):''}`;}
  const rows=navigation==='interventions'?interventions.map(r=>({id:r.id,run:r,revision:r.current_revision_id,title:r.animation_id,detail:r.stop_reason||words(r.lifecycle),at:'',source:'framework'})):
    data.events.filter(e=>source==='all'||e.source===source).map(e=>({id:e.id,run:data.runs.find(r=>r.id===e.run_id)!,revision:e.revision_id,title:words(e.event),detail:e.note||e.animation_id,at:e.created_at,source:e.source}));
  const filtered=rows.filter(row=>`${row.run.animation_id} ${row.detail} ${row.revision}`.toLowerCase().includes(query.toLowerCase()));
  const groups=new Map<string,typeof rows>();filtered.forEach(row=>groups.set(row.run.project_id,[...(groups.get(row.run.project_id)||[]),row]));
  return <div className="desk-shell"><div className="desk-window"><header className="app-header"><button className="brand" onClick={()=>{setNavigation('interventions');location.hash='/';}}><Icon name="frame"/><span>Framebound</span></button>
    <input className="agent-search" aria-label="Find animation or event" placeholder="Find animation or event" value={query} onChange={e=>setQuery(e.target.value)}/>
    <details className="workspace-switcher"><summary aria-label="More workspaces">•••</summary><nav><a href="#/export">Export</a><a href="#/status">Status</a><a href="#/reviewed-guides">Reviewed guides</a></nav></details></header>
    <div className="desktop-body"><aside className="review-sidebar"><nav className="review-navigation" aria-label="Review views"><button aria-current={navigation==='interventions'?'page':undefined} onClick={()=>setNavigation('interventions')}><span className="nav-symbol"><Icon name="inbox"/></span><span>Interventions</span><span className="nav-count">{interventions.length}</span></button><button aria-current={navigation==='timeline'?'page':undefined} onClick={()=>setNavigation('timeline')}><span className="nav-symbol"><Icon name="history"/></span><span>Timeline</span></button></nav>
      {navigation==='timeline' && <div className="timeline-tools"><select aria-label="Activity source" value={source} onChange={e=>setSource(e.target.value)}><option value="all">All activity</option><option value="framework">Framework</option><option value="human">Human</option><option value="external_agent">Parent agent</option></select></div>}
      <div className="review-queue" aria-label={navigation==='interventions'?'Intervention queue':'Project timeline'}>{[...groups].map(([pid,entries])=><section className="queue-project" key={pid}><header className="queue-heading"><Icon name="folder"/><span>{data.projects.find(p=>p.id===pid)?.name||pid}</span><small>{entries.length}</small></header>{entries.map(row=><div className="queue-row" key={row.id}><button className="queue-item" aria-label={`${row.title} ${row.revision||''}`} aria-current={row.revision===inspected?'true':undefined} onClick={()=>open(row.run,row.revision)}><span className="queue-thumb"><Icon name="film"/></span><span><strong>{row.title}</strong><small>{row.detail}</small>{row.at && <time dateTime={row.at}>{stamp(row.at)} · {words(row.source)}</time>}</span><span className="queue-revision">{row.revision}</span></button></div>)}</section>)}{!filtered.length&&<p className="queue-empty">{navigation==='interventions'?'No interventions':'No activity'}</p>}</div>
      <div className="sidebar-footer"><a href="#/export">Export training data</a></div>
    </aside><main className={selection.export?"operations-desk":"film-desk"} data-film-view="agent-run"><Err e={error}/>{selection.export?<AgentExport data={data}/>:run && bundle && bundle.revision.id===inspected && bundle.revision.run_id===run.id?<AgentWorkspace key={bundle.revision.id} bundle={bundle} run={run} onChange={onChange} onRevision={rid=>open(run,rid)}/>:<p>{run?(run.current_revision_id?'Loading animation…':'Awaiting the first agent submission.'):'Select a run from the timeline.'}</p>}</main></div>
  </div></div>;
}
