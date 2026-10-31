import { useCallback, useEffect, useRef, useState } from 'react';
import {UtilitiesMenu,UtilityWindow} from './DeskUtilities';
import {DeskStatus} from './DeskStatus';
import {ReferencesView} from './Operations';
import {KeyboardGuide} from './KeyboardGuide';
import {InterventionReview} from './InterventionReview';
import {ReviewTag,reviewTag} from './ReviewReason';
import type {ReviewContext} from './ReviewReason';
import { req } from './api';
import { Handoff } from './Handoff';
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

function route(){const [path,query]=location.hash.replace(/^#\/?/,'').split('?'),parts=path.split('/');return {legacyCase:parts[0]==='studio'?new URLSearchParams(query).get('case')||'':'',utility:['export','status','reviewed-guides','references'].includes(parts[0])?(parts[0]==='references'?'reviewed-guides':parts[0]) as 'export'|'status'|'reviewed-guides':null,run:parts[0]==='run'?decodeURIComponent(parts[1]||''):'',revision:new URLSearchParams(query).get('revision')};}
export function AgentDesk({data,onChange}:{data:AgentDeskData;onChange:()=>void}) {
  const [studioCases,setStudioCases]=useState<{id:string;title:string;reason:string;review?:ReviewContext;activity?:string;status:string;thumbnail_url?:string|null}[]>([]);
  useEffect(()=>{let active=true;const load=()=>req<{cases:typeof studioCases;work:{case_id:string;state:string}[]}>('/v3/studio').then(x=>{if(active)setStudioCases(x.cases.map(c=>({...c,activity:x.work?.filter(w=>w.case_id===c.id).slice(-1)[0]?.state})));}).catch(()=>{});load();const t=setInterval(load,3000);return()=>{active=false;clearInterval(t);};},[]);
  const [selection,setSelection]=useState(route),[navigation,setNavigation]=useState<'interventions'|'timeline'>('interventions');
  const returnToReview=useRef('#/');
  useEffect(()=>{if(selection.run)returnToReview.current=location.hash;},[selection.run,selection.revision]);
  const search=useRef<HTMLInputElement>(null),queueView=useRef<HTMLDivElement>(null);
  const [source,setSource]=useState('all'),[query,setQuery]=useState('');
  const [bundle,setBundle]=useState<AgentBundle|null>(null),[error,setError]=useState<unknown>(null);
  const interventions=data.runs.filter(r=>r.needs_intervention&&!studioCases.some(c=>c.id===r.id));
  const reviewCases=studioCases.filter(c=>c.status!=='approved').sort((a,b)=>Number(a.status==='excluded')-Number(b.status==='excluded')||a.title.localeCompare(b.title));
  const fallbackRun=reviewCases.find(c=>c.status==='review')?.id||reviewCases[0]?.id||interventions[0]?.id;
  const caseId=selection.legacyCase||selection.run||fallbackRun;
  const reviewCase=studioCases.find(c=>c.id===caseId);
  useEffect(()=>{if(!selection.run&&!selection.legacyCase&&!selection.utility&&fallbackRun)location.hash='/run/'+encodeURIComponent(fallbackRun);},[selection.run,selection.legacyCase,selection.utility,fallbackRun]);
  useEffect(()=>{queueView.current?.querySelector('[aria-current="true"]')?.scrollIntoView({block:'nearest'});},[caseId,navigation,studioCases.length,query]);
  const run=data.runs.find(r=>r.id===caseId);
  // Freeze the first inspected revision. Live updates never replace inspection or unsaved edits.
  const [inspected,setInspected]=useState(selection.revision||run?.current_revision_id||null);
  useEffect(()=>{const update=()=>{const next=route();setSelection(next);setInspected(next.revision);};window.addEventListener('hashchange',update);return()=>window.removeEventListener('hashchange',update);},[]);
  useEffect(()=>{if(!inspected && run?.current_revision_id)setInspected(run.current_revision_id);},[run?.id,run?.current_revision_id,inspected]);
  useEffect(()=>{
    if(!inspected||reviewCase){setBundle(null);return;}
    const controller=new AbortController();
    req<AgentBundle>(`/v3/desk/revisions/${encodeURIComponent(inspected)}`,{signal:controller.signal}).then(result=>{setBundle(result);setError(null);}).catch(e=>{if(!controller.signal.aborted)setError(e);});
    return()=>controller.abort();
  },[inspected,run?.version,reviewCase?.id]);
  function open(r:Run,rid:string|null=r.current_revision_id){location.hash=`/run/${encodeURIComponent(r.id)}${rid?'?revision='+encodeURIComponent(rid):''}`;}
  const rows=navigation==='interventions'?interventions.map(r=>({id:r.id,run:r,revision:r.current_revision_id,title:r.animation_id,detail:r.stop_reason||words(r.lifecycle),at:'',source:'framework'})):
    data.events.filter(e=>source==='all'||e.source===source).map(e=>({id:e.id,run:data.runs.find(r=>r.id===e.run_id)!,revision:e.revision_id,title:words(e.event),detail:e.note||e.animation_id,at:e.created_at,source:e.source}));
  const filtered=rows.filter(row=>`${row.run.animation_id} ${row.detail} ${row.revision}`.toLowerCase().includes(query.toLowerCase()));
  const groups=new Map<string,typeof rows>();filtered.forEach(row=>groups.set(row.run.project_id,[...(groups.get(row.run.project_id)||[]),row]));
  useEffect(()=>{
    const keyboard=(e:KeyboardEvent)=>{
      const target=e.target as HTMLElement,key=e.key.toLowerCase();
      if((e.metaKey||e.ctrlKey)&&key==='k'){e.preventDefault();search.current?.focus();search.current?.select();return;}
      if(e.defaultPrevented||e.metaKey||e.ctrlKey||e.altKey||target.closest('input,textarea,select,[contenteditable="true"],dialog,[role="dialog"]'))return;
      if(selection.utility||(key!=='j'&&key!=='k'))return;
      const matching=reviewCases.filter(c=>`${c.title} ${reviewTag(c.review,c.activity).label} ${c.review?.label||c.reason} ${c.review?.summary||''}`.toLowerCase().includes(query.toLowerCase()));
      const queue=[...matching.map(c=>c.id),...interventions.filter(r=>`${r.animation_id} ${r.stop_reason||''}`.toLowerCase().includes(query.toLowerCase())).map(r=>r.id)];
      if(!queue.length)return;
      e.preventDefault();const index=queue.indexOf(caseId||'');const next=queue[Math.max(0,Math.min(queue.length-1,index+(key==='j'?1:-1)))];
      setNavigation('interventions');location.hash='/run/'+encodeURIComponent(next);
    };
    window.addEventListener('keydown',keyboard);return()=>window.removeEventListener('keydown',keyboard);
  },[caseId,query,reviewCases,interventions,selection.utility]);
  return <div className="desk-shell"><div className="desk-window"><header className="app-header"><button className="brand" onClick={()=>{setNavigation('interventions');location.hash='/';}}><Icon name="frame"/><span>Framebound</span></button>
    <label className="agent-search-wrap"><Icon name="search"/><input ref={search} className="agent-search" aria-label="Find animation or event" aria-keyshortcuts="Meta+K Control+K" placeholder="Find animation or event" onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();if(query)setQuery('');else e.currentTarget.blur();}}} value={query} onChange={e=>setQuery(e.target.value)}/><kbd aria-hidden="true">{/Mac/.test(navigator.platform)?'⌘':'Ctrl'} K</kbd></label>
    <UtilitiesMenu active={selection.utility||undefined}/></header>
    <div className="desktop-body"><aside className="review-sidebar"><nav className="review-navigation" aria-label="Review views"><button aria-current={navigation==='interventions'&&!selection.utility?'page':undefined} onClick={()=>{setNavigation('interventions');location.hash='/';}}><span className="nav-symbol"><Icon name="inbox"/></span><span>Interventions</span><span className="nav-count">{interventions.length+reviewCases.length}</span></button><button aria-current={navigation==='timeline'&&!selection.utility?'page':undefined} onClick={()=>{setNavigation('timeline');location.hash='/';}}><span className="nav-symbol"><Icon name="history"/></span><span>Timeline</span></button></nav>
      {navigation==='timeline' && <div className="timeline-tools"><select aria-label="Activity source" value={source} onChange={e=>setSource(e.target.value)}><option value="all">All activity</option><option value="framework">Framework</option><option value="human">Human</option><option value="external_agent">Parent agent</option></select></div>}
      <div ref={queueView} className="review-queue" aria-label={navigation==='interventions'?'Intervention queue':'Project timeline'}>{navigation==='interventions'&&reviewCases.length>0&&<section className="queue-project animation-review-queue"><header className="queue-heading"><Icon name="folder"/><span>Animation review</span><small>{reviewCases.length}</small></header>{reviewCases.filter(c=>`${c.title} ${reviewTag(c.review,c.activity).label} ${c.review?.label||c.reason} ${c.review?.summary||''}`.toLowerCase().includes(query.toLowerCase())).map(c=><div className="queue-row" key={c.id}><button className="queue-item" aria-current={c.id===caseId?'true':undefined} onClick={()=>{location.hash='/run/'+encodeURIComponent(c.id);}}><span className="queue-thumb">{c.thumbnail_url?<img src={c.thumbnail_url} alt=""/>:<Icon name="film"/>}</span><span><strong title={c.title}>{c.title}</strong><ReviewTag context={c.review} activity={c.activity}/></span></button></div>)}</section>}{[...groups].map(([pid,entries])=><section className="queue-project" key={pid}><header className="queue-heading"><Icon name="folder"/><span>{data.projects.find(p=>p.id===pid)?.name||pid}</span><small>{entries.length}</small></header>{entries.map(row=><div className="queue-row" key={row.id}><button className="queue-item" aria-label={`${row.title} ${row.revision||''}`} aria-current={row.run.id===run?.id && row.revision===inspected?'true':undefined} onClick={()=>open(row.run,row.revision)}><span className="queue-thumb"><Icon name="film"/></span><span><strong>{row.title}</strong><small>{row.detail}</small>{row.at && <time dateTime={row.at}>{stamp(row.at)} · {words(row.source)}</time>}</span><span className="queue-revision">{row.revision}</span></button></div>)}</section>)}{!filtered.length&&!(navigation==='interventions'&&reviewCases.length)&&<p className="queue-empty">{navigation==='interventions'?'No interventions':'No activity'}</p>}</div>
    </aside><main className={selection.utility?"operations-desk":"film-desk"} data-film-view="agent-run"><Err e={error}/>{selection.utility?<UtilityWindow view={selection.utility} back={returnToReview.current}>{selection.utility==='export'?<AgentExport data={data}/>:selection.utility==='status'?<DeskStatus data={data}/>:<ReferencesView/>}</UtilityWindow>:reviewCase?<InterventionReview key={reviewCase.id} caseId={reviewCase.id} versionId={selection.revision||undefined}/>:run && bundle && bundle.revision.id===inspected && bundle.revision.run_id===run.id?<AgentWorkspace key={bundle.revision.id} bundle={bundle} run={run} onChange={onChange} onRevision={rid=>open(run,rid)}/>:<section className="agent-export"><p>{run?(run.current_revision_id?'Loading animation…':run.stop_reason||'Awaiting the first agent submission.'):'Select a run from the timeline.'}</p>{run?.feedback_id && !run.current_revision_id && <Handoff feedbackId={run.feedback_id}/>}</section>}</main></div>
    <KeyboardGuide/>
  </div></div>;
}
