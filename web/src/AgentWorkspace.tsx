import { useEffect, useMemo, useRef, useState } from 'react';
import {AnnotationPlayer,Stroke} from './AnnotationPlayer';
import { req } from './api';
import { Film, useFilm } from './Film';
import { Handoff } from './Handoff';
import { Provenance } from './Provenance';
import { Err, Icon, words } from './shared';
import { tickOfSlot, toNative } from './playback';
import { usePresentationClock } from './useClock';
import { firstActionable, formatMeasurement } from './agent-model';
import type { AgentBundle, Run, Roi, Mark } from './agent-model';

export function AgentWorkspace({bundle:b,run,onChange,onRevision}:{bundle:AgentBundle;run:Run;onChange:()=>void;onRevision:(rid:string)=>void}) {
  const [visual,setVisual]=useState<Stroke[]>([]);
  const spec=b.task.spec, initial=useRef(firstActionable(b));
  const [slot,setSlot]=useState(initial.current), [selected,setSelected]=useState([initial.current]);
  const anchor=useRef(initial.current), controls=useFilm();
  const holds=useMemo(()=>b.frames.map(f=>f.hold_ticks),[b.frames]);
  const clock=usePresentationClock({holds,tps:spec.timing.ticks_per_second,loop:spec.loop,
    resetKey:b.revision.id,initialTick:tickOfSlot(holds,initial.current),autoPlay:false});
  const wasPlaying=useRef(false);
  const [playback,setPlayback]=useState(false),[tab,setTab]=useState<'evidence'|'correction'|'decision'>('evidence');
  const [note,setNote]=useState(''),[roi,setRoi]=useState<Roi|null>(null),[grant,setGrant]=useState(false);
  const [rangeStart,setRangeStart]=useState(tickOfSlot(holds,initial.current));
  const [rangeEnd,setRangeEnd]=useState(tickOfSlot(holds,initial.current)+holds[initial.current]);
  const [eligibility,setEligibility]=useState<{eligible:boolean;policy?:string;revision_id?:string;reasons:string[]}|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState<unknown>(null),[message,setMessage]=useState('');
  const [saved,setSaved]=useState<string|null>(null),[compare,setCompare]=useState<AgentBundle|null>(null);
  const [compareSource,setCompareSource]=useState(false),[preferPrevious,setPreferPrevious]=useState(false);
  const operation=useRef(crypto.randomUUID());
  const drag=useRef<{x:number;y:number}|null>(null),canvas=useRef<HTMLCanvasElement>(null);
  const live=b.revision.id===run.current_revision_id && b.task.id===run.task_id;
  const writable=live && run.lifecycle!=='cancelled';
  const targets=b.feedback.targets.filter(t=>t.slots.includes(slot));
  const frame=b.frames[slot],marks=run.interventions.filter(m=>m.slots.includes(slot));
  useEffect(()=>{
    if(wasPlaying.current && !clock.playing) { setSlot(clock.slot);setSelected([clock.slot]);anchor.current=clock.slot; }
    wasPlaying.current=clock.playing;
  },[clock.playing,clock.slot]);
  useEffect(()=>{
    let active=true;
    const load=()=>req<{eligible:boolean;policy?:string;revision_id?:string;reasons:string[]}>(`/v3/runs/${encodeURIComponent(run.id)}/eligibility`)
      .then(value=>{if(active)setEligibility(value);}).catch(()=>{if(active)setEligibility(null);});
    void load();window.addEventListener('focus',load);
    return()=>{active=false;window.removeEventListener('focus',load);};
  },[run.id,run.version,b.revision.id]);
  useEffect(()=>{ setCompare(null); },[b.revision.id]);
  useEffect(()=>setPreferPrevious(false),[compare?.revision.id]);
  const focus=(index:number,shift=false)=>{
    clock.setPlaying(false);wasPlaying.current=false;clock.selectSlot(index);setSlot(index);
    if(!shift)anchor.current=index;
    const selection=shift?Array.from({length:Math.abs(anchor.current-index)+1},(_,i)=>Math.min(anchor.current,index)+i):[index];
    setSelected(selection);setRangeStart(tickOfSlot(holds,Math.min(...selection)));
    setRangeEnd(tickOfSlot(holds,Math.max(...selection))+holds[Math.max(...selection)]);
    controls.film.current?.reveal(index,true);
  };
  async function comparePrevious(){
    if(compare){setCompare(null);return;}
    const rid=b.revision.parent_revision_id;if(!rid)return;
    setCompareSource(false);
    try{
      const other=await req<AgentBundle>(`/v3/desk/revisions/${encodeURIComponent(rid)}`);
      if(JSON.stringify(other.task.spec.timing)!==JSON.stringify(spec.timing))throw new Error('No compatible authored-time mapping for this comparison');
      setCompare(other);
    }catch(e){setError(e);}
  }
  async function save(action?:string){
    if(busy || !writable)return;
    setBusy(true);setError(null);setMessage('');
    try{
      const result=await req<{feedback:{id:string}}>(`/v3/runs/${encodeURIComponent(run.id)}/${action?'decisions':'interventions'}`,{
        method:'POST',body:JSON.stringify(action?{id:operation.current,revision_id:b.revision.id,
          evaluation_id:b.evaluation.id,action,note,...(action==='approve' && preferPrevious && compare && compare.task.id===b.task.id?{comparison_revision_id:compare.revision.id,comparison_evaluation_id:compare.evaluation.id}:{})}:{id:operation.current,revision_id:b.revision.id,
          evaluation_id:b.evaluation.id,desired_outcome:note,visual_annotations:visual,tick_range:[rangeStart,rangeEnd],roi,authorize_edit_scope:grant})});
      setSaved(result.feedback.id);setVisual([]);setNote('');setRoi(null);setGrant(false);operation.current=crypto.randomUUID();
      setMessage(action?'Decision saved':'Correction saved');onChange();
    }catch(e){setError(e);}finally{setBusy(false);}
  }
  async function generate(){
    setBusy(true);setError(null);
    try{
      await req(`/v3/runs/${encodeURIComponent(run.id)}/review`,{method:'POST'});
      await req(`/v3/studio/${encodeURIComponent(run.id)}/feedback`,{method:'POST',body:JSON.stringify({id:operation.current,version_id:b.revision.id,text:note,strokes:visual})});
      setVisual([]);setNote('');onChange();
    }catch(e){setError(e);}finally{setBusy(false);}
  }
  async function resolve(mark:Mark,reopen=false){
    setBusy(true);setError(null);
    try{
      const result=await req<{feedback:{id:string}}>(`/v3/interventions/${encodeURIComponent(mark.id)}/${reopen?'reopen':'resolve'}`,{
        method:'POST',body:JSON.stringify({expected_version:mark.version,revision_id:b.revision.id,evaluation_id:b.evaluation.id,note})});
      setSaved(result.feedback.id);setVisual([]);setNote('');onChange();
    }catch(e){setError(e);}finally{setBusy(false);}
  }
  function point(e:React.PointerEvent<HTMLCanvasElement>){const r=e.currentTarget.getBoundingClientRect();const p=toNative(e.clientX,e.clientY,r,spec.canvas.width,spec.canvas.height,{scaleX:r.width/spec.canvas.width,scaleY:r.height/spec.canvas.height,offsetX:0,offsetY:0,mirrored:false});return [Math.floor(p.x),Math.floor(p.y)];}
  useEffect(()=>{
    if(tab!=='correction' || !canvas.current)return;
    let active=true;const image=new Image();image.src=frame.asset_url;
    image.onload=()=>{if(active){const c=canvas.current;c?.getContext('2d')?.drawImage(image,0,0);}};
    return()=>{active=false;};
  },[tab,frame.asset_url]);
  const projectedSource=b.source_comparison?.frames.map(f=>({id:'source-'+f.output_slot,asset_url:f.asset_url,correspondence:f.correspondence}));
  const sourceAtSlot=b.source_comparison?.frames[slot];
  const rows:{title:string;frames:{id:string;asset_url:string;correspondence?:string}[]}[]=compareSource && projectedSource?
    [{title:'Known-good source',frames:projectedSource},{title:'Candidate',frames:b.frames}]:compare?[{title:'Previous revision',frames:compare.frames},{title:'Candidate',frames:b.frames}]:[{title:'Candidate',frames:b.frames}];
  if(b.intake&&!b.intake.eligible)return <div className="packet-workspace agent-workspace"><section className="film-window"><header className="pane-title viewer-title"><strong>{run.animation_id}</strong><span className="title-grip"/><span className="badge">Intake rejected</span></header><div className="review-intake-empty"><strong>Outside the isolated 2D MVP</strong><p>{b.intake.principle}</p><p>{[...new Set(b.intake.frames.flatMap(f=>f.reasons))].join('; ')}</p><button onClick={()=>req(`/v3/runs/${encodeURIComponent(run.id)}/review`,{method:'POST'}).then(onChange).catch(setError)}>Prepare isolated replacement</button><Err e={error}/></div></section></div>;
  return <div className="packet-workspace agent-workspace" data-revision={b.revision.id}>
    <section className="film-window">
      <header className="pane-title viewer-title"><span className="file-icon"><Icon name="film"/></span><strong>{run.animation_id}</strong><span className="title-grip"/>
        <span className={"badge "+b.evaluation.technical_status}>{words(b.evaluation.technical_status)}</span><span className="badge">{words(b.evaluation.coverage)} coverage</span></header>
      <div className="viewer-toolbar"><span title={b.revision.id}>Revision {run.submission_ids.indexOf(b.revision.id)+1}</span>
        <span>{live?'Current revision':b.revision.id===run.current_revision_id?'Task revised · awaiting new submission':'Historical revision'}</span>
        {b.revision.id!==run.current_revision_id && run.current_revision_id && <button onClick={()=>onRevision(run.current_revision_id!)}>Open current</button>}
        {b.source_comparison && <button aria-pressed={compareSource} onClick={()=>{setCompare(null);setCompareSource(v=>!v);}}>Compare known-good source</button>}
        {b.revision.parent_revision_id && <button aria-pressed={Boolean(compare)} onClick={()=>void comparePrevious()}>Compare previous</button>}
        <div className="control-zoom"><button aria-label="Zoom out" onClick={()=>controls.film.current?.zoom(-1)}>−</button><output>{controls.zoom}%</output><button aria-label="Zoom in" onClick={()=>controls.film.current?.zoom(1)}>+</button><button onClick={()=>controls.film.current?.fit()}>Fit</button></div>
      </div>
      <div className={'film-stage agent-film-stage'+((compare||compareSource)?' has-comparison':'')+(playback?' agent-playback-mode':'')}>
        <Film ref={controls.film} filmKey={'agent-'+b.revision.id} count={b.frames.length} sequence selected={slot}
          onZoom={controls.setZoom} onPosition={controls.setPosition} onStep={focus}>
          <div className="reel-ruler">{b.frames.map((f,i)=><button key={f.id} aria-label={`Frame ${i+1}`} aria-pressed={selected.includes(i)} onClick={e=>focus(i,e.shiftKey)}>{String(i+1).padStart(2,'0')}<small>{tickOfSlot(holds,i)}–{tickOfSlot(holds,i)+holds[i]}</small></button>)}</div>
          {rows.map(row=><div className="reel-stock reel-lane candidate" key={row.title}><div className="reel-shot-row">{row.frames.map((f,i)=><div className="reel-frame-unit" key={f.id}><button className={'reel-frame '+(slot===i?'is-current':'')} title={f.correspondence?`Authored-time correspondence: ${words(f.correspondence)}`:undefined} aria-label={`${row.title}, frame ${i+1}`} aria-pressed={selected.includes(i)} onClick={e=>focus(i,e.shiftKey)}><span className="frame-aperture"><img draggable={false} src={f.asset_url} alt={`${row.title} frame ${i+1}`}/></span></button></div>)}</div></div>)}
          <div className="measurement-track" aria-label="Checks and corrections"><div className="measurement-row">{b.frames.map((f,i)=>{const issues=b.feedback.targets.filter(t=>t.slots.includes(i));return <button key={f.id} onClick={()=>focus(i)} className={'agent-check-cell '+(issues.length?'has-issue':'')} aria-label={`Frame ${i+1}: ${issues.length?issues.length+' corrections':'checks pass'}`}><strong>{issues.length?issues.length+' corrections':'Pass'}</strong>{issues.slice(0,2).map(t=><small key={t.id}>{words(t.check_id)}</small>)}</button>;})}</div></div>
        </Film>
        <div className="agent-lane-tabs" aria-hidden="true">{rows.map(row=><strong key={row.title}>{row.title}</strong>)}<strong>Checks</strong></div>
        {playback && <div className="agent-main-playback" aria-label="Main playback">{rows.map(row=><figure key={row.title}><img src={row.frames[clock.slot]?.asset_url} alt={row.title+' playback'} draggable={false}/><figcaption>{row.title}{row.frames[clock.slot]?.correspondence?' · '+words(row.frames[clock.slot].correspondence!):''}</figcaption></figure>)}</div>}
      </div>
      <footer className="review-controls"><div className="control-transport"><button aria-label="Previous frame" onClick={()=>focus(Math.max(0,slot-1))}><Icon name="left"/></button><button aria-label={clock.playing?'Pause':'Play'} onClick={()=>{setPlayback(true);clock.setPlaying(!clock.playing);}}><Icon name={clock.playing?'pause':'play'}/></button><button aria-label="Next frame" onClick={()=>focus(Math.min(holds.length-1,slot+1))}><Icon name="right"/></button></div>
        <output aria-label="Inspected frame">Frame {slot+1} / {holds.length}</output><button onClick={()=>{clock.setPlaying(false);setPlayback(false);}}>Film</button>
        <select aria-label="Playback speed" value={clock.speed} onChange={e=>clock.setSpeed(Number(e.target.value))}>{[0.25,0.5,1,2].map(s=><option key={s} value={s}>{s}×</option>)}</select>
        <span>{words(run.lifecycle)} · {words(run.creative_status)}</span>
      </footer>
      <div className="agent-revisions" aria-label="Revision history">{run.submission_ids.map(rid=><button key={rid} aria-pressed={rid===b.revision.id} onClick={()=>onRevision(rid)}>{rid}{rid===run.best_revision_id?' · best':''}{rid===run.current_revision_id?' · current':''}</button>)}</div>
    </section>
    <aside className="frame-inspector agent-inspector"><header className="pane-title inspector-heading"><strong>Frame {slot+1}</strong><span className="title-grip"/><span>{live?'Current':'Historical'}</span></header>
      <nav className="agent-inspector-tabs">{(['evidence','correction','decision'] as const).map(t=><button key={t} aria-pressed={tab===t} onClick={()=>{clock.setPlaying(false);setTab(t);}}>{t==='correction'?'Feedback':words(t)}</button>)}</nav>
      <div className="frame-inspector-content"><Err e={error}/>{message && <p role="status">{message}</p>}
        {tab==='evidence' && <><p>{spec.intent}</p><details><summary>Generation provenance</summary><Provenance value={b.provenance}/></details>{sourceAtSlot && <section className="agent-finding"><strong>Source correspondence</strong><small>{words(sourceAtSlot.correspondence)} · source frame {sourceAtSlot.source_slot+1}</small><p>Source tick {sourceAtSlot.source_tick[0]}/{sourceAtSlot.source_tick[1]} → output tick {sourceAtSlot.output_tick}</p><small>Designated by {b.source_comparison!.designation.designated_by}: {b.source_comparison!.designation.designation_basis}</small></section>}{targets.length?targets.map(target=><section className="agent-finding" key={target.id}><strong>{words(target.check_id)}</strong><small>{target.observation_source} · ticks [{target.tick_range.join(', ')})</small><p>{target.desired_outcome}</p><dl><dt>Observed</dt><dd>{formatMeasurement(target.observed)}</dd><dt>Expected</dt><dd>{formatMeasurement(target.expected)}</dd></dl>{target.roi && <small>Native ROI {JSON.stringify(target.roi)}</small>}<details><summary>Source evidence ({target.evidence_assets.length})</summary>{target.evidence_assets.map((asset,index)=><a key={asset.id} href={asset.http_path} target="_blank" rel="noreferrer">Frame evidence {index+1}</a>)}</details></section>):<p>Supported checks pass for this frame.</p>}
        {b.task.requirements.filter(r=>r.applicability!=='supported').map(r=><p key={r.check}>{words(r.check)}: {r.limitation}</p>)}
        <details><summary>Contextual inputs</summary>{spec.inputs.map(i=><figure key={i.asset_id}><img className="agent-context-image" src={'/api/asset/'+encodeURIComponent(i.asset_id)} alt={i.role}/><figcaption>{words(i.role)} · {i.provenance}</figcaption></figure>)}</details>
        <small>{spec.scene?.limitation || (spec.profile==='structural-v1'?'Structural only; animation quality not verified.':'Declared regions and events only; broader anatomy and action quality remain judgment.')}</small>
        <section className="agent-finding" aria-label="Output policy"><strong>Output policy</strong>{eligibility?<><small>{eligibility.policy||'Not evaluated'} · {eligibility.eligible?'Eligible':'Withheld'}</small>{eligibility.revision_id && eligibility.revision_id!==b.revision.id && <small>Applies to current best {eligibility.revision_id}</small>}{eligibility.reasons.map((reason,index)=><small key={index}>{reason}</small>)}</>:<small>Current eligibility unavailable</small>}</section>
        <details><summary>Agent instructions</summary><Handoff feedbackId={b.feedback.id}/></details></>}
        {tab==='correction' && <><AnnotationPlayer urls={b.frames.map(f=>f.asset_url)} holds={holds} tps={spec.timing.ticks_per_second} loop={spec.loop} width={spec.canvas.width} height={spec.canvas.height} value={visual} onChange={setVisual}/></>}{tab==='correction' && <form onSubmit={e=>{e.preventDefault();void save();}}><label>Desired correction<textarea aria-label="Desired correction" value={note} onChange={e=>setNote(e.target.value)} required maxLength={1000}/></label>
          <details><summary>Edit scope and timing</summary><div className="agent-tick-range"><label>Start tick<input aria-label="Start tick" type="number" min={0} value={rangeStart} onChange={e=>setRangeStart(Number(e.target.value))}/></label><label>End tick (exclusive)<input aria-label="End tick" type="number" min={rangeStart+1} value={rangeEnd} onChange={e=>setRangeEnd(Number(e.target.value))}/></label></div>
          <div className="agent-mark-stage"><canvas ref={canvas} width={spec.canvas.width} height={spec.canvas.height} aria-label="Mark correction region" onPointerDown={e=>{e.currentTarget.setPointerCapture(e.pointerId);const [x,y]=point(e);drag.current={x,y};}} onPointerMove={e=>{if(!drag.current)return;const [x,y]=point(e),start=drag.current;setRoi({left:Math.min(start.x,x),top:Math.min(start.y,y),right:Math.max(start.x,x)+1,bottom:Math.max(start.y,y)+1});}} onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}/>{roi && <div className="region-box" style={{left:100*roi.left/spec.canvas.width+'%',top:100*roi.top/spec.canvas.height+'%',width:100*(roi.right-roi.left)/spec.canvas.width+'%',height:100*(roi.bottom-roi.top)/spec.canvas.height+'%'}}/>}</div>
          {roi && <button type="button" onClick={()=>setRoi(null)}>Clear region</button>}
          <label><input type="checkbox" checked={grant} onChange={e=>setGrant(e.target.checked)}/>Authorize edits only within this range/region</label></details>
          <button type="button" disabled={busy||!writable||(!note.trim()&&!visual.length)} onClick={()=>void generate()}>Submit & generate</button><details><summary>Advanced: scoped agent correction</summary><button disabled={busy||!writable||!note.trim()}>Save correction for external agent</button></details></form>}
        {tab==='decision' && <>{compare && compare.task.id===b.task.id && <label><input type="checkbox" checked={preferPrevious} onChange={e=>setPreferPrevious(e.target.checked)}/>Explicitly prefer this revision over {compare.revision.id}</label>}<label>Decision note<textarea aria-label="Decision note" value={note} onChange={e=>setNote(e.target.value)} maxLength={1000}/></label><div className="review-actions">{['approve','needs_changes','reject'].map(action=><button key={action} disabled={busy||!writable} onClick={()=>void save(action)}>{words(action)}</button>)}</div></>}
        {marks.map(mark=><section className="agent-finding" key={mark.id}><strong>{mark.correction.desired_outcome}</strong><small>{words(mark.correction.status)} · {mark.owner}</small>{live && <button disabled={busy||!writable||(mark.correction.status!=='resolved' && mark.candidate_revision_id!==b.revision.id)} onClick={()=>void resolve(mark,mark.correction.status==='resolved')}>{mark.correction.status==='resolved'?'Reopen':'Resolve'}</button>}<Handoff feedbackId={mark.handoff_id}/></section>)}
        {saved && <section aria-label="Saved action instructions"><Handoff feedbackId={saved}/></section>}
      </div>
    </aside>
  </div>;
}
