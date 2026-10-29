/* Shared evidence and local prototype review records, not a shared page layout. */
window.Review = (() => {
  const fixture = window.FRAMEBOUND_REVIEW_FIXTURE;
  const records = fixture.records;
  const storageKey = 'framebound.review-concepts.v4';
  let saved;
  try { saved = JSON.parse(localStorage.getItem(storageKey) || 'null'); } catch {}
  if (!saved || !Array.isArray(saved.events) || !Array.isArray(saved.issues)) saved = { events: [], issues: [] };
  const state = { id: fixture.default_revision, frame: 3, tick: 12, playing: false, speed: 1, roi: null, range: null, mode: 'candidate', marking: false, step: 0, selectedColumns: [3] };
  const images = new Map();
  const listeners = new Set();
  let raf = 0, stamp = 0, drag = null, inspectTab = 'film';
  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;' }[c]));
  const label = s => String(s ?? '').replaceAll('_',' ').replaceAll('-',' ');
  const num = n => String(n).padStart(2,'0');
  const record = () => records.find(r => r.id === state.id);
  const base = () => records.find(r => r.id === record().baseline);
  const start = (s, r = record()) => r.contract.timing.holds.slice(0,s).reduce((a,b) => a+b,0);
  const total = (r = record()) => r.contract.timing.holds.reduce((a,b) => a+b,0);
  const slot = (tick, r = record()) => { let n=0; return Math.max(0,r.contract.timing.holds.findIndex(h => { const on=tick>=n && tick<n+h; n+=h; return on; })); };
  const findings = (r = record()) => r.evaluation.results.filter(x => x.outcome !== 'pass');
  const scoped = result => { const m=result.scope.match(/^slot (\d+)$/); return m ? Number(m[1]) : null; };
  const decision = (r = record()) => saved.events.filter(e => e.clip_revision_id === r.id && e.expected_evaluation_id === r.evaluation.id).at(-1);
  const issues = (r = record()) => saved.issues.filter(i => i.clip_revision_id === r.id || i.replacement_revision_id === r.id || r.baseline === i.clip_revision_id);
  const replacement = issue => records.find(r => r.baseline === issue.clip_revision_id && r.id !== issue.clip_revision_id && r.evaluation.technical_status === 'pass' && r.evaluation.coverage_status === 'complete');
  const canResolve = issue => { const source=records.find(r=>r.id===issue.clip_revision_id),r=replacement(issue); return !!r && source?.evaluation.id===issue.baseline_evaluation_id && decision(r)?.action === 'approve'; };
  function emit(full = true) { listeners.forEach(fn => fn(full)); if (full) updateInspector(); paint(); updateTransport(); }
  function persist() { try { localStorage.setItem(storageKey,JSON.stringify(saved)); } catch { notify('Storage unavailable. This review lasts until reload.'); } }
  function notify(text) { $('[data-announcement]').textContent=text; }
  function load(url) { if(images.has(url))return; const i=new Image();images.set(url,i);i.onload=()=>{paint();updateTransport();};i.onerror=()=>{paint();updateTransport();};i.src=url; }
  records.forEach(r => { r.frames.forEach(f => load(f.url)); r.references.forEach(f => load(f.url)); });
  [fixture.identity,fixture.style,fixture.editable,fixture.protected].forEach(load);
  const ready = image => image?.complete && image.naturalWidth > 0;
  const status = r => `<span class="signal ${r.evaluation.technical_status}">${esc(r.evaluation.technical_status)}</span>`;
  const acceptance = r => decision(r) ? label(decision(r).action) : 'Unreviewed';
  const picture = (url, alt, cls = '') => `<img class="${cls}" src="${url}" alt="${esc(alt)}">`;
  function checkValue(x) { if(x.observed_value==null)return '—';if(typeof x.observed_value!=='number')return esc(x.observed_value);return x.units==='fraction'?`${(x.observed_value*100).toFixed(1)}%`:`${Number(x.observed_value.toFixed(2))}${['pixels','native_px'].includes(x.units)?' px':''}`; }
  function bound(x) { if(!x.expected_interval)return '—'; const factor=x.units==='fraction'?100:1;return x.expected_interval.map(v=>Number((v*factor).toFixed(1))).join('–')+(factor===100?'%':''); }
  function blockers(r=record()) { const b=[];if(r.evaluation.technical_status!=='pass')b.push('Technical '+r.evaluation.technical_status);if(r.evaluation.coverage_status!=='complete')b.push('Coverage '+r.evaluation.coverage_status);const count=issues(r).filter(i=>i.status!=='resolved').length;if(count)b.push(count+' open correction'+(count===1?'':'s'));return b; }
  function pause(render=true) { state.playing=false;cancelAnimationFrame(raf);if(render)emit(false); }
  function selectFrame(frame, full=true) { pause(false);state.frame=Math.max(0,Math.min(record().frames.length-1,frame));state.tick=start(state.frame);state.roi=null;emit(full); }
  function selectRecord(id) { if(!records.some(r=>r.id===id))return;pause(false);state.id=id;state.frame=Math.min(3,record().frames.length-1);state.tick=start(state.frame);state.roi=null;state.range=null;state.selectedColumns=[state.frame];state.marking=false;state.mode='candidate';emit(); }
  function play() { if(state.playing)return pause();if(!record().contract.action.loop && state.tick>=total()-1)state.tick=0;state.playing=true;stamp=performance.now();const step=now=>{state.tick+=(now-stamp)/1000*record().contract.timing.ticks_per_second*state.speed;stamp=now;if(state.tick>=total()){if(record().contract.action.loop)state.tick%=total();else{state.tick=total()-1;state.playing=false;}}state.frame=slot(state.tick);emit(false);if(state.playing)raf=requestAnimationFrame(step);};emit(false);raf=requestAnimationFrame(step); }
  function setTick(t) { pause(false);state.tick=Math.max(0,Math.min(total()-1,t));state.frame=slot(state.tick);state.roi=null;emit(false); }
  function setMode(mode) { if(mode!=='candidate'&&!base())return;state.mode=mode;paint();$$('[data-mode]').forEach(el=>el.setAttribute('aria-pressed',String(el.dataset.mode===mode))); }
  function mark() { pause(false);state.marking=!state.marking;$$('[data-mark]').forEach(el=>el.setAttribute('aria-pressed',String(state.marking)));paint();if(state.marking&&document.body.dataset.concept==='matrix'&&$('[data-inspector]')?.open)$('[data-inspector] [data-raster=candidate]')?.scrollIntoView({block:'center'}); }
  function decide(action) { pause(false);saved.events.push({id:crypto.randomUUID(),action,clip_revision_id:record().id,packet_id:record().packet.id,expected_revision_id:record().id,expected_evaluation_id:record().evaluation.id,evidence_manifest_sha256:record().evaluation.evidence_manifest_sha256,created_at:new Date().toISOString(),origin:'local-design-prototype'});persist();notify(label(action)+' · '+record().id+' · saved locally');emit(); }
  function submitIssue(form) { const from=Number(form.elements.from.value),to=Number(form.elements.to.value),note=form.elements.note.value.trim();if(!Number.isInteger(from)||!Number.isInteger(to)||from<0||to<from||to>=total()){notify('Tick range must be within 0–'+(total()-1));return;}if(!note){form.elements.note.focus();return;}saved.issues.push({id:'local-'+crypto.randomUUID().slice(0,8),status:'open',clip_revision_id:record().id,packet_id:record().packet.id,baseline_evaluation_id:record().evaluation.id,frame_instance_id:record().frames[slot(from)].id,frame_range:[from,to],roi:state.roi?{...state.roi}:null,category:form.elements.category.value,note,created_at:new Date().toISOString(),origin:'local-design-prototype'});persist();notify('Correction saved locally · '+record().id);state.marking=false;state.roi=null;state.range=null;form.elements.note.value='';emit(); }
  function resolve(id) { const i=saved.issues.find(i=>i.id===id);if(!i||!canResolve(i))return;const r=replacement(i);i.status='resolved';i.replacement_revision_id=r.id;i.replacement_evaluation_id=r.evaluation.id;persist();emit(); }
  function reopen(id) { const i=saved.issues.find(i=>i.id===id);if(!i)return;i.status='reopened';for(const id of [i.clip_revision_id,i.replacement_revision_id].filter(Boolean)){const r=records.find(r=>r.id===id);saved.events.push({id:crypto.randomUUID(),action:'needs_changes',clip_revision_id:id,packet_id:r.packet.id,expected_evaluation_id:r.evaluation.id,origin:'local-design-prototype',created_at:new Date().toISOString()});}persist();emit(); }
  function reset() { pause(false);saved={events:[],issues:[]};state.roi=null;state.range=null;persist();emit();notify('Local review reset'); }
  function download() {const url=URL.createObjectURL(new Blob([JSON.stringify({schema:'review-concept-prototype-4',...saved},null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='framebound-local-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}

  function transport(extra='') {return `<div class="transport"><button data-step="-1" aria-label="Previous frame">←</button><button class="play" data-play>Play</button><button data-step="1" aria-label="Next frame">→</button><span data-position>04 / 08</span><input type="range" min="0" max="${total()-1}" value="${Math.floor(state.tick)}" data-scrub aria-label="Authored tick"><span data-tick>12t</span><label class="speed"><select data-speed aria-label="Playback speed"><option value="0.5" ${state.speed===.5?'selected':''}>0.5×</option><option value="1" ${state.speed===1?'selected':''}>1×</option><option value="2" ${state.speed===2?'selected':''}>2×</option></select></label>${extra}</div>`;}
  function modes() {return `<div class="modes">${['candidate','compare','diff','blink'].map((m,i)=>`<button data-mode="${m}" aria-pressed="${state.mode===m}" ${i&&!base()?'disabled':''}>${['Frame','Compare','Difference','Blink'][i]}</button>`).join('')}</div>`;}
  function stage(cls='') {return `<div class="stage ${cls}" data-view="${state.mode}"><figure class="base-picture"><figcaption>Baseline <span>${base()?.id||'—'}</span></figcaption><div class="raster"><canvas width="96" height="96" data-raster="base" aria-label="Baseline frame"></canvas></div></figure><figure><figcaption>Candidate <span>${record().id}</span></figcaption><div class="raster"><canvas width="96" height="96" data-raster="candidate" aria-label="Candidate frame; mark native-pixel region"></canvas></div></figure><span class="stage-error" data-media-error role="alert"></span></div>`;}
  function references() {return `<div class="reference-trio">${[[fixture.identity,'Identity'],[fixture.style,'Style'],[record().references[state.frame].url,'Phase · '+label(record().frames[state.frame].phase)]].map(([url,name],i)=>`<figure>${picture(url,name,i===2?'phase-ref':'')}<figcaption ${i===2?'data-phase-ref-label':''}>${esc(name)}</figcaption></figure>`).join('')}</div><small class="authority">Frozen references · fixture approval</small>`;}
  function evidence(all=false) {const rows=all?[...record().evaluation.results].sort((a,b)=>Number(a.outcome==='pass')-Number(b.outcome==='pass')):findings();return `<div class="evidence-table">${rows.length?rows.map(x=>`<button class="evidence-row ${x.outcome}" data-finding="${record().evaluation.results.indexOf(x)}"><span><strong>${esc(label(x.constraint_id))}</strong><small>${scoped(x)===null?esc(x.scope):'Frame '+num(scoped(x)+1)} · ${label(x.outcome)}</small></span><b>${checkValue(x)}<small>${bound(x)}</small></b><p>${esc(x.reason)}</p></button>`).join(''):'<p class="empty">No failing or unmeasured checks.</p>'}</div>`;}
  function correctionForm() {const range=state.range||[start(state.frame),start(state.frame)+record().frames[state.frame].hold_ticks-1];return `<form class="correction-form" data-correction><div class="scope-fields"><label>Category<select name="category"><option value="silhouette">Silhouette</option><option value="appearance">Appearance / feature</option><option value="phase">Phase</option><option value="contact">Contact</option><option value="general">Other</option></select></label><fieldset><legend>Ticks</legend><input type="number" name="from" min="0" max="${total()-1}" value="${range[0]}" aria-label="Start tick"><span>–</span><input type="number" name="to" min="0" max="${total()-1}" value="${range[1]}" aria-label="End tick"></fieldset></div><div class="region-field"><button type="button" data-mark aria-pressed="${state.marking}">＋ Region</button><output data-roi>${state.roi?Object.values(state.roi).join(', ')+' px':'Whole frame'}</output><button type="button" data-clear-roi aria-label="Clear region">×</button></div><label>Defect<textarea name="note" rows="3" placeholder="What must change?" required></textarea></label><button class="primary" type="submit">Queue correction →</button></form>`;}
  function decisions() {return `<div class="decision-block"><dl><div><dt>Technical</dt><dd>${status(record())}</dd></div><div><dt>Coverage</dt><dd class="${record().evaluation.coverage_status==='complete'?'':'incomplete'}">${record().evaluation.coverage_status}</dd></div><div><dt>Human</dt><dd>${esc(acceptance(record()))}</dd></div></dl><div class="decision-actions"><button data-decide="reject">Reject</button><button data-decide="needs_changes">Needs changes</button><button class="primary" data-decide="approve">Approve</button></div><small>${esc(record().id)} · ${esc(record().evaluation.id)}</small><p>${esc(blockers().join(' · ')||'Release not verified in local prototype')}</p></div>`;}
  function taskCards() {return saved.issues.map(i=>{const r=replacement(i);return `<article class="local-task"><header><b>${esc(label(i.category))}</b><span>${esc(i.status)}</span></header><p>${esc(i.note)}</p><small>${esc(i.clip_revision_id)} · ticks ${i.frame_range.join('–')}<br>${i.roi?Object.values(i.roi).join(', ')+' px':'Whole frame'}</small><div class="task-actions"><button data-inspect-issue="${i.id}">Inspect</button>${r?`<button data-replacement="${i.id}">Replacement ↗</button>`:''}${i.status==='resolved'?`<button data-reopen="${i.id}">Reopen</button>`:r?`<button data-resolve="${i.id}" ${canResolve(i)?'':'disabled'}>Resolve</button>`:''}</div></article>`;}).join('')||'<p class="empty">No local correction requests.</p>';}

  function updateTransport() {
    $$('[data-play]').forEach(el=>el.textContent=state.playing?'Pause':'Play');
    $$('[data-position]').forEach(el=>el.textContent=num(state.frame+1)+' / '+num(record().frames.length));
    $$('[data-tick]').forEach(el=>el.textContent=Math.floor(state.tick)+'t / '+total());
    $$('[data-scrub]').forEach(el=>el.value=Math.floor(state.tick));
    $$('[data-live-image]').forEach(el=>el.src=record().frames[state.frame].url);
    $$('.phase-ref').forEach(el=>el.src=record().references[state.frame].url);
    $$('[data-phase-ref-label]').forEach(el=>el.textContent='Phase · '+label(record().frames[state.frame].phase));
    $$('[data-frame]').forEach(el=>el.classList.toggle('selected',Number(el.dataset.frame)===state.frame));
    $$('[data-live-phase]').forEach(el=>el.textContent=label(record().frames[state.frame].phase));
    $$('[data-decide]').forEach(el=>{el.disabled=!ready(images.get(record().frames[state.frame].url));el.setAttribute('aria-pressed',String(decision()?.action===el.dataset.decide));});
    if(!state.range)$$('[data-correction]').forEach(form=>{form.elements.from.value=start(state.frame);form.elements.to.value=start(state.frame)+record().frames[state.frame].hold_ticks-1;});
  }
  function paint() {
    $$('.stage').forEach(el=>el.dataset.view=state.mode);
    $$('[data-raster]').forEach(canvas=>{
      const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.clearRect(0,0,96,96);
      const candidate=images.get(record().frames[state.frame].url),baseline=base()?images.get(base().frames[state.frame].url):null;
      const isBase=canvas.dataset.raster==='base';let image=isBase?baseline:candidate;
      if(!isBase&&state.mode==='blink'&&Math.floor(performance.now()/500)%2===0)image=baseline;
      if(ready(image))ctx.drawImage(image,0,0);
      if(!isBase&&state.mode==='diff'&&ready(candidate)&&ready(baseline)){
        try{const a=document.createElement('canvas');a.width=a.height=96;const ac=a.getContext('2d',{willReadFrequently:true});ac.drawImage(baseline,0,0);const data=ctx.getImageData(0,0,96,96),b=ac.getImageData(0,0,96,96);let count=0;for(let p=0;p<data.data.length;p+=4){const changed=[0,1,2,3].some(k=>data.data[p+k]!==b.data[p+k]);count+=Number(changed);data.data[p]=244;data.data[p+1]=91;data.data[p+2]=55;data.data[p+3]=changed?255:0;}ctx.putImageData(data,0,0);$$('[data-diff-count]').forEach(el=>el.textContent=count+' changed pixels');}catch{$$('[data-diff-count]').forEach(el=>el.textContent='Pixel comparison needs HTTP');}
      }
      if(!isBase&&state.roi){const b=state.roi;ctx.strokeStyle='#ed9e1d';ctx.lineWidth=1;ctx.strokeRect(b.left+.5,b.top+.5,b.right-b.left,b.bottom-b.top);}
      if(!isBase)canvas.style.cursor=state.marking?'crosshair':'default';
      const box=canvas.parentElement;const scale=Math.max(1,Math.floor(Math.min(box.clientWidth-16,box.clientHeight-16)/96));canvas.style.width=canvas.style.height=scale*96+'px';
    });
    $$('[data-media-error]').forEach(el=>el.textContent=images.get(record().frames[state.frame].url)?.complete&&!ready(images.get(record().frames[state.frame].url))?'Frame media unavailable':'');
  }
  function updateInspector() {
    const dialog=$('[data-inspector]');if(!dialog?.open)return;
    $('[data-inspector-title]').textContent=record().label+' / '+record().id;
    $$('[data-inspector-tab]').forEach(el=>el.setAttribute('aria-selected',String(el.dataset.inspectorTab===inspectTab)));
    const body=$('[data-inspector-body]');
    if(inspectTab==='film')body.innerHTML=modes()+stage('inspector-stage')+transport()+`<span class="diff-count" data-diff-count></span>`+references();
    if(inspectTab==='evidence')body.innerHTML=`<div class="inspector-evidence">${references()}${evidence(true)}</div>`;
    if(inspectTab==='correction')body.innerHTML=stage('inspector-small')+transport()+correctionForm();
    if(inspectTab==='decision')body.innerHTML=decisions()+`<div class="inspector-tasks">${taskCards()}</div>`;
  }
  function inspect(tab='film',id=null,frame=null) {pause(false);if(id)selectRecord(id);if(frame!==null){state.frame=frame;state.tick=start(frame);}inspectTab=tab;const dialog=$('[data-inspector]');if(document.body.dataset.concept==='matrix'&&tab==='correction')state.mode='candidate';if(!dialog.open)dialog.showModal();updateInspector();paint();updateTransport();if(document.body.dataset.concept==='matrix')dialog.scrollTop=0;}
  document.addEventListener('click',e=>{
    const button=e.target.closest('button');if(!button)return;
    if(button.hasAttribute('data-play'))play();
    if(button.dataset.step)selectFrame(state.frame+Number(button.dataset.step),false);
    if(button.dataset.mode)setMode(button.dataset.mode);
    if(button.hasAttribute('data-mark'))mark();
    if(button.hasAttribute('data-clear-roi')){state.roi=null;$$('[data-roi]').forEach(el=>el.textContent='Whole frame');paint();}
    if(button.dataset.decide)decide(button.dataset.decide);
    if(button.dataset.inspect)inspect(button.dataset.inspect);
    if(button.dataset.inspectorTab){inspectTab=button.dataset.inspectorTab;pause(false);if(document.body.dataset.concept==='matrix'&&inspectTab==='correction')state.mode='candidate';updateInspector();paint();updateTransport();if(document.body.dataset.concept==='matrix')$('[data-inspector]').scrollTop=0;}
    if(button.hasAttribute('data-close-inspector')){pause();$('[data-inspector]').close();}
    if(button.dataset.finding!==undefined){const f=record().evaluation.results[Number(button.dataset.finding)];if(scoped(f)!==null)selectFrame(scoped(f));}
    if(button.dataset.inspectIssue){const i=saved.issues.find(i=>i.id===button.dataset.inspectIssue);inspect('correction',i.clip_revision_id,slot(i.frame_range[0],records.find(r=>r.id===i.clip_revision_id)));state.roi=i.roi;state.range=i.frame_range;updateInspector();const form=$('[data-inspector-body] form');form.elements.category.value=i.category;form.elements.note.value=i.note;paint();}
    if(button.dataset.replacement){const i=saved.issues.find(i=>i.id===button.dataset.replacement);const r=replacement(i);if(r){inspect('film',r.id);setMode('compare');}}
    if(button.dataset.resolve)resolve(button.dataset.resolve);
    if(button.dataset.reopen)reopen(button.dataset.reopen);
    if(button.hasAttribute('data-reset'))reset();
    if(button.hasAttribute('data-download'))download();
  });
  document.addEventListener('change',e=>{if(e.target.matches('[data-speed]')){state.speed=Number(e.target.value);stamp=performance.now();}});
  document.addEventListener('input',e=>{if(e.target.matches('[data-scrub]'))setTick(Number(e.target.value));if(e.target.closest('[data-correction]')&&e.target.matches('[name=from],[name=to]')){const form=e.target.form;state.range=[Number(form.elements.from.value),Number(form.elements.to.value)];}});
  document.addEventListener('submit',e=>{if(e.target.matches('[data-correction]')){e.preventDefault();pause(false);submitIssue(e.target);}});
  document.addEventListener('focusin',e=>{if(e.target.closest('[data-correction]')&&state.playing)pause(false);});
  function point(e,canvas){const b=canvas.getBoundingClientRect();return {x:Math.max(0,Math.min(96,(e.clientX-b.left)/b.width*96)),y:Math.max(0,Math.min(96,(e.clientY-b.top)/b.height*96))};}
  document.addEventListener('pointerdown',e=>{const c=e.target.closest('[data-raster=candidate]');if(!c||!state.marking)return;pause(false);drag={...point(e,c),canvas:c};c.setPointerCapture(e.pointerId);});
  document.addEventListener('pointermove',e=>{if(!drag)return;const p=point(e,drag.canvas);state.roi={left:Math.floor(Math.min(p.x,drag.x)),top:Math.floor(Math.min(p.y,drag.y)),right:Math.ceil(Math.max(p.x,drag.x)),bottom:Math.ceil(Math.max(p.y,drag.y))};$$('[data-roi]').forEach(el=>el.textContent=Object.values(state.roi).join(', ')+' px');paint();});
  document.addEventListener('pointerup',e=>{if(!drag)return;drag.canvas.releasePointerCapture(e.pointerId);drag=null;state.marking=false;if(state.roi&&(state.roi.left===state.roi.right||state.roi.top===state.roi.bottom))state.roi=null;$$('[data-mark]').forEach(el=>el.setAttribute('aria-pressed','false'));if(document.body.dataset.concept==='canvas'&&!$('[data-inspector]').open)inspect('correction');paint();});
  document.addEventListener('pointercancel',()=>{drag=null;});
  document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});
  window.addEventListener('resize',paint);
  document.addEventListener('keydown',e=>{if(e.target.matches('input,select,textarea')||e.ctrlKey||e.metaKey||e.altKey)return;if(e.key===' '&&!e.target.closest('button,a')&&$$('[data-play]').some(el=>el.checkVisibility())){e.preventDefault();play();}if(e.key==='ArrowRight'){e.preventDefault();selectFrame(state.frame+1,false);}if(e.key==='ArrowLeft'){e.preventDefault();selectFrame(state.frame-1,false);}});
  setInterval(()=>{if(state.mode==='blink')paint();},500);
  return {fixture,records,state,$,$$,esc,label,num,record,base,start,total,slot,findings,scoped,decision,issues,replacement,canResolve,status,acceptance,picture,checkValue,bound,blockers,selectRecord,selectFrame,setTick,pause,play,setMode,mark,decide,submitIssue,resolve,reopen,reset,download,transport,modes,stage,references,evidence,correctionForm,decisions,taskCards,inspect,paint,updateTransport,emit,notify,get saved(){return saved;},subscribe(fn){listeners.add(fn);}};
})();
