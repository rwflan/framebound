/* Five candidate interfaces over the same real, procedural framework evidence.
 * All review writes are local prototypes; no production API or authority is used. */
const fixture = window.FRAMEBOUND_REVIEW_FIXTURE;
const pages = ['index.html','02-ledger.html','03-comparison.html','04-triage.html','05-sequence.html'];
const design = Math.max(0,pages.indexOf(location.pathname.split('/').pop()));
const key = 'framebound.review-designs.v3';
let local;
try { local=JSON.parse(localStorage.getItem(key)||'null'); } catch { local=null; }
if(!local || !Array.isArray(local.events) || !Array.isArray(local.issues)) local={events:[],issues:[]};
let record=fixture.records.find(r=>r.id===fixture.default_revision);
let tick=12, playing=false, speed=1, stamp=0, raf=0, mode=design===2||design===4?'compare':'single';
let roi=null, dragging=null, allChecks=design===1, rangeDirty=false, marking=false, masks=false;
const images=new Map();
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const label=s=>String(s||'').replaceAll('_',' ').replaceAll('-',' ');
const n2=n=>String(n).padStart(2,'0');
const total=()=>record.contract.timing.holds.reduce((a,b)=>a+b,0);
const startOf=n=>record.contract.timing.holds.slice(0,n).reduce((a,b)=>a+b,0);
function slotAt(t){let sum=0;return record.contract.timing.holds.findIndex(h=>{const yes=t>=sum&&t<sum+h;sum+=h;return yes;});}
const slot=()=>Math.max(0,slotAt(Math.min(total()-1,Math.floor(tick))));
const baseline=()=>fixture.records.find(r=>r.id===record.baseline);
const currentDecision=r=>local.events.filter(e=>e.clip_revision_id===r.id&&e.expected_evaluation_id===r.evaluation.id).at(-1);
const relatedIssues=r=>local.issues.filter(i=>i.clip_revision_id===r.id||i.replacement_revision_id===r.id||r.baseline===i.clip_revision_id);
const openIssues=r=>relatedIssues(r).filter(i=>i.status!=='resolved');
const failing=r=>r.evaluation.results.filter(x=>['fail','error'].includes(x.outcome));
const attention=r=>r.evaluation.results.filter(x=>x.outcome!=='pass');
const tone=v=>['pass','complete','approve','resolved','fixture-approved'].includes(v)?'good':['fail','error','reject'].includes(v)?'bad':'warn';
const badge=(text,value=text)=>`<span class="badge ${tone(value)}">${escape(label(text))}</span>`;
function persist(){try{localStorage.setItem(key,JSON.stringify(local));}catch{announce('Browser storage unavailable; review lasts until this page closes.');}}
function announce(text){$('[data-message]').textContent=text;}
function img(url,alt,cls=''){return `<img class="${cls}" src="${url}" alt="${escape(alt)}" loading="eager">`;}
function load(url){if(!url||images.has(url))return;const i=new Image();images.set(url,i);i.onload=()=>{draw();updateDecisionButtons();};i.onerror=()=>{draw();updateDecisionButtons();};i.src=url;}
fixture.records.forEach(r=>{r.frames.forEach(f=>load(f.url));r.references.forEach(f=>load(f.url));});
[fixture.identity,fixture.style,fixture.editable,fixture.protected].forEach(load);

$('[data-designs]').innerHTML=pages.map((p,i)=>`<a href="${p}" aria-label="Design ${i+1}" ${i===design?'aria-current="page"':''}>0${i+1}</a>`).join('');

function renderQueue(){
  $('[data-queue-list]').innerHTML=fixture.records.filter(r=>r.id!=='pip-run-r01').map(r=>{
    const d=currentDecision(r);
    return `<button class="queue-item ${r.id===record.id?'selected':''}" data-revision="${r.id}" aria-pressed="${r.id===record.id}">${img(r.frames[Math.min(3,r.frames.length-1)].url,r.label+' revision '+r.id)}<span class="queue-copy"><strong>${r.label}<small>${r.id.split('-').at(-1)}</small></strong><span>${badge(r.evaluation.technical_status)}<small>${d?label(d.action):'Unreviewed'}</small></span></span>${failing(r).length?`<b class="queue-count">${failing(r).length}</b>`:''}</button>`;
  }).join('');
  $('[data-task-count]').textContent=local.issues.filter(i=>i.status!=='resolved').length;
}
function renderSummary(){
  const d=currentDecision(record);
  $('[data-summary]').innerHTML=`<div class="revision-title"><span class="eyebrow">Pip / ${escape(record.contract.action.view)} / ${escape(record.contract.action.facing)}</span><h1>${record.label}<span>${record.id}</span></h1></div><dl class="status-grid"><div><dt>Technical</dt><dd>${badge(record.evaluation.technical_status)}</dd></div><div><dt>Coverage</dt><dd>${badge(record.evaluation.coverage_status)}</dd></div><div><dt>Human review</dt><dd>${badge(d?`${label(d.action)} · local`:'Unreviewed',d?.action||'unreviewed')}</dd></div></dl>`;
  $('[data-bound-revision]').textContent=record.id;
  $('[data-bound-evaluation]').textContent=record.evaluation.id;
  $('[data-human-decision]').textContent=d?`${label(d.action)} · saved locally`:'Unreviewed';
  const blockers=[];
  if(record.evaluation.technical_status!=='pass')blockers.push('Technical '+label(record.evaluation.technical_status));
  if(record.evaluation.coverage_status!=='complete')blockers.push('Coverage '+label(record.evaluation.coverage_status));
  if(openIssues(record).length)blockers.push(`${openIssues(record).length} open correction${openIssues(record).length===1?'':'s'}`);
  $('[data-release]').textContent=blockers.length?blockers.join(' · '):'Release not verified in local prototype';
  $$('[data-decide]').forEach(b=>b.setAttribute('aria-pressed',String(d?.action===b.dataset.decide)));
}
function value(result){
  if(result.observed_value===null||result.observed_value===undefined)return '—';
  if(typeof result.observed_value!=='number')return escape(result.observed_value);
  const fraction=result.units==='fraction';
  return `${(result.observed_value*(fraction?100:1)).toFixed(fraction?1:2).replace(/\.00$/,'')}${fraction?'%':result.units==='native_px'?' px':result.units==='pixels'?' px':''}`;
}
function bound(result){
  if(!result.expected_interval)return '—';
  const scale=result.units==='fraction'?100:1;
  return result.expected_interval.map(x=>(x*scale).toFixed(1).replace(/\.0$/,'')).join('–')+(scale===100?'%':result.units==='native_px'?' px':'');
}
function resultSlot(result){const m=result.scope.match(/^slot (\d+)$/);return m?Number(m[1]):null;}
function renderEvidence(){
  const rows=allChecks?[...record.evaluation.results].sort((a,b)=>Number(a.outcome==='pass')-Number(b.outcome==='pass')):attention(record);
  $('[data-findings-title]').textContent=`Findings · ${attention(record).length}`;
  $('[data-check-filter]').textContent=allChecks?'Show attention only':`All ${record.evaluation.results.length} checks`;
  $('[data-evidence]').innerHTML=rows.length?`<div class="evidence-head"><span>Check / frame</span><span>Observed</span><span>Bound</span></div>`+rows.map((r,i)=>{
    const index=record.evaluation.results.indexOf(r),s=resultSlot(r);
    return `<button class="finding ${tone(r.outcome)} ${s===slot()?'current':''}" data-finding="${index}" title="${escape(r.reason)}"><span class="finding-name"><i></i><strong>${escape(label(r.constraint_id))}</strong><small>${s===null?escape(r.scope):'Frame '+n2(s+1)} · ${escape(label(r.outcome))}</small></span><b>${value(r)}</b><span class="bound">${bound(r)}</span><p>${escape(r.reason)}</p></button>`;
  }).join(''):`<div class="no-findings">No failing or unmeasured checks.</div>`;
}
function renderTimeline(){
  $('[data-frames]').style.setProperty('--frames',record.frames.length);
  $('[data-frames]').innerHTML=record.frames.map((f,i)=>{
    const outcomes=record.evaluation.results.filter(r=>resultSlot(r)===i&&r.outcome!=='pass');
    return `<button class="frame ${outcomes.some(r=>r.outcome==='fail')?'has-failure':outcomes.length?'has-gap':''}" data-frame="${i}" aria-label="Frame ${i+1}, ${escape(label(f.phase))}"><span class="frame-top"><b>${n2(i+1)}</b><span>${f.hold_ticks}t</span></span>${img(f.url,'Frame '+(i+1))}<span class="phase">${escape(label(f.phase))}</span></button>`;
  }).join('');
  $('[data-timing]').textContent=`${total()} ticks / ${record.contract.timing.ticks_per_second} tps · locked`;
  $('[data-scrub]').max=total()-1;
  $('[data-range-from]').max=total()-1;$('[data-range-to]').max=total()-1;
}
function renderReferences(){
  $('[data-references]').innerHTML=`<figure>${img(fixture.identity,'Frozen identity reference')}<figcaption>Identity <span>Fixture approved</span></figcaption></figure><figure>${img(fixture.style,'Frozen style reference')}<figcaption>Style <span>Fixture approved</span></figcaption></figure><figure>${img(record.references[slot()].url,'Matching phase reference','phase-reference')}<figcaption>Phase <span data-reference-phase>${escape(label(record.frames[slot()].phase))}</span></figcaption></figure>`;
}
function updateScope(){
  if(!rangeDirty){$('[data-range-from]').value=startOf(slot());$('[data-range-to]').value=startOf(slot())+record.frames[slot()].hold_ticks-1;}
  $('[data-roi]').textContent=roi?`${roi.left}, ${roi.top} → ${roi.right}, ${roi.bottom} px`:'Whole frame';
  $('[data-clear-roi]').disabled=!roi;
}
function renderPosition(){
  const s=slot(),f=record.frames[s];
  $('[data-position]').textContent=`Frame ${n2(s+1)} / ${n2(record.frames.length)}`;
  $('[data-phase]').textContent=label(f.phase);
  $('[data-tick]').textContent=`Tick ${Math.floor(tick)} / ${total()} · hold ${f.hold_ticks}t`;
  $('[data-scrub]').value=Math.floor(tick);
  $$('[data-frame]').forEach(el=>{const on=Number(el.dataset.frame)===s;el.classList.toggle('selected',on);el.setAttribute('aria-pressed',String(on));});
  $$('[data-finding]').forEach(el=>el.classList.toggle('current',resultSlot(record.evaluation.results[Number(el.dataset.finding)])===s));
  const phase=$('.phase-reference');if(phase&&phase.getAttribute('src')!==record.references[s].url)phase.src=record.references[s].url;
  if($('[data-reference-phase]'))$('[data-reference-phase]').textContent=label(f.phase);
  $('[data-play]').textContent=playing?'Pause':'Play';
  $('[data-current-hash]').textContent=f.asset_id;
  updateScope();draw();
}
function renderRevision(){
  renderQueue();renderSummary();renderTimeline();renderReferences();renderEvidence();
  $$('[data-mode]').forEach(b=>{b.disabled=b.dataset.mode!=='single'&&!baseline();b.setAttribute('aria-pressed',String(b.dataset.mode===mode));});
  $('.viewer').dataset.mode=mode;
  $('[data-baseline-label]').textContent=baseline()?.id||'No baseline';
  $('[data-candidate-label]').textContent=record.id;
  $('[data-contract]').textContent=record.contract.id;
  renderPosition();resizeStages();
}
function selectRevision(id){
  const next=fixture.records.find(r=>r.id===id);if(!next)return;
  pause();record=next;tick=Math.min(12,total()-1);roi=null;rangeDirty=false;marking=false;
  $('[data-mark-region]').setAttribute('aria-pressed','false');
  if(!baseline())mode='single';else if(design===2||design===4)mode='compare';
  $('[data-note]').value='';announce('');renderRevision();
}
function pause(){playing=false;cancelAnimationFrame(raf);renderPosition();}
function play(){
  if(playing){pause();return;}
  if(!record.contract.action.loop&&tick>=total()-1)tick=0;
  playing=true;stamp=performance.now();
  const step=now=>{
    if(!playing)return;
    tick+=(now-stamp)/1000*record.contract.timing.ticks_per_second*speed;stamp=now;
    if(tick>=total()){
      if(record.contract.action.loop)tick%=total();
      else{tick=total()-1;playing=false;}
    }
    renderPosition();if(playing)raf=requestAnimationFrame(step);
  };
  renderPosition();raf=requestAnimationFrame(step);
}
function selectFrame(s){pause();s=Math.max(0,Math.min(record.frames.length-1,s));tick=startOf(s);roi=null;rangeDirty=false;renderPosition();}
function fitCanvas(canvas){
  const screen=canvas.parentElement;
  const requested=$('[data-zoom]').value;
  const max=requested==='fit'?Math.max(1,Math.floor(Math.min(screen.clientWidth-16,screen.clientHeight-16)/96)):Number(requested);
  canvas.style.width=canvas.style.height=`${96*max}px`;
  screen.style.alignItems=96*max>screen.clientHeight?'flex-start':'center';
  screen.style.justifyContent=96*max>screen.clientWidth?'flex-start':'center';
}
function resizeStages(){$$('canvas[data-stage],canvas[data-base]').forEach(fitCanvas);}
function ready(i){return i&&i.complete&&i.naturalWidth>0;}
function draw(){
  const f=record.frames[slot()],main=$('[data-stage]'),base=$('[data-base]');
  if(!main||!base)return;
  const ctx=main.getContext('2d'),bctx=base.getContext('2d');ctx.clearRect(0,0,96,96);bctx.clearRect(0,0,96,96);
  const image=images.get(f.url),bf=baseline()?.frames[slot()],bi=bf?images.get(bf.url):null;
  $('[data-media-error]').textContent=image?.complete&&!image.naturalWidth?'Frame media failed to load.':'';
  if(ready(bi))bctx.drawImage(bi,0,0);
  if(ready(image))ctx.drawImage(image,0,0);
  if(mode==='blink'&&ready(bi)&&Math.floor(performance.now()/450)%2===0){ctx.clearRect(0,0,96,96);ctx.drawImage(bi,0,0);}
  if(mode==='diff'&&ready(image)&&ready(bi)){
    try{
      const a=ctx.getImageData(0,0,96,96),b=bctx.getImageData(0,0,96,96);let count=0;
      for(let p=0;p<a.data.length;p+=4){const changed=[0,1,2,3].some(k=>a.data[p+k]!==b.data[p+k]);if(changed)count++;a.data[p]=changed?235:0;a.data[p+1]=changed?91:0;a.data[p+2]=changed?65:0;a.data[p+3]=changed?255:0;}
      ctx.putImageData(a,0,0);$('[data-diff-count]').textContent=`${count} changed pixels`;
    }catch{$('[data-diff-count]').textContent='Serve over HTTP to inspect pixel differences.';}
  }else $('[data-diff-count]').textContent='';
  if(masks&&ready(images.get(fixture.editable))){
    // Visualise the fixture's actual editable mask, not an invented anatomy overlay.
    const scratch=document.createElement('canvas');scratch.width=scratch.height=96;
    const sc=scratch.getContext('2d');sc.drawImage(images.get(fixture.editable),0,0);
    const data=sc.getImageData(0,0,96,96);
    for(let p=0;p<data.data.length;p+=4){const a=data.data[p]>127;data.data[p]=a?68:27;data.data[p+1]=a?202:46;data.data[p+2]=a?190:72;data.data[p+3]=a?70:20;}
    sc.putImageData(data,0,0);ctx.drawImage(scratch,0,0);
  }
  if(roi){ctx.strokeStyle='#edb332';ctx.lineWidth=1;ctx.strokeRect(roi.left+.5,roi.top+.5,roi.right-roi.left,roi.bottom-roi.top);}
  main.style.cursor=marking?'crosshair':'default';
  updateDecisionButtons();
}
function updateDecisionButtons(){if(!record||!$('[data-stage]'))return;const available=ready(images.get(record.frames[slot()].url));$$('[data-decide]').forEach(b=>b.disabled=!available);}
function nativePoint(e){const b=$('[data-stage]').getBoundingClientRect();return {x:Math.max(0,Math.min(96,(e.clientX-b.left)/b.width*96)),y:Math.max(0,Math.min(96,(e.clientY-b.top)/b.height*96))};}
const canvas=$('[data-stage]');
canvas.addEventListener('pointerdown',e=>{if(!marking)return;pause();dragging=nativePoint(e);canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener('pointermove',e=>{if(!dragging)return;const p=nativePoint(e);roi={left:Math.floor(Math.min(dragging.x,p.x)),top:Math.floor(Math.min(dragging.y,p.y)),right:Math.ceil(Math.max(dragging.x,p.x)),bottom:Math.ceil(Math.max(dragging.y,p.y))};updateScope();draw();});
canvas.addEventListener('pointerup',e=>{if(!dragging)return;const p=nativePoint(e);roi={left:Math.floor(Math.min(dragging.x,p.x)),top:Math.floor(Math.min(dragging.y,p.y)),right:Math.ceil(Math.max(dragging.x,p.x)),bottom:Math.ceil(Math.max(dragging.y,p.y))};if(roi.right-roi.left<1||roi.bottom-roi.top<1)roi=null;dragging=null;marking=false;canvas.releasePointerCapture(e.pointerId);$('[data-mark-region]').setAttribute('aria-pressed','false');updateScope();draw();});
canvas.addEventListener('pointercancel',()=>{dragging=null;});

function replacementFor(issue){
  return fixture.records.find(r=>r.baseline===issue.clip_revision_id&&r.id!==issue.clip_revision_id&&
    r.evaluation.technical_status==='pass'&&r.evaluation.coverage_status==='complete');
}
function canResolve(issue,replacement){
  return replacement&&replacementFor(issue)?.id===replacement.id&&currentDecision(replacement)?.action==='approve';
}
function renderTasks(){
  $('[data-task-list]').innerHTML=local.issues.length?local.issues.map(i=>{
    const replacement=replacementFor(i);
    const approved=canResolve(i,replacement);
    return `<article class="task"><header><strong>${escape(label(i.category))}</strong>${badge(i.status)}</header><p>${escape(i.note)}</p><dl><div><dt>Revision</dt><dd>${escape(i.clip_revision_id)}</dd></div><div><dt>Tick range</dt><dd>${i.frame_range.join('–')}</dd></div><div><dt>ROI</dt><dd>${i.roi?Object.values(i.roi).join(', ')+' px':'Whole frame'}</dd></div></dl><div class="task-actions"><button data-inspect-task="${i.id}">Inspect</button>${replacement?`<button data-replacement="${replacement.id}">Compare replacement</button>`:''}${i.status==='resolved'?`<button data-reopen="${i.id}">Reopen</button>`:replacement?`<button data-resolve="${i.id}" ${approved&&replacement.evaluation.technical_status==='pass'?'':'disabled'}>Resolve with ${replacement.id}</button>`:''}</div><small>${escape(i.id)} · local</small></article>`;
  }).join(''):'<p class="empty">No local correction tasks.</p>';
}
function decide(action){
  pause();
  local.events.push({id:crypto.randomUUID(),action,clip_revision_id:record.id,packet_id:record.packet.id,
    expected_revision_id:record.id,expected_evaluation_id:record.evaluation.id,
    evidence_manifest_sha256:record.evaluation.evidence_manifest_sha256,created_at:new Date().toISOString(),origin:'local-design-prototype'});
  persist();renderSummary();renderQueue();announce(`${label(action)} saved locally for ${record.id}.`);
}
function requestCorrection(e){
  e.preventDefault();const from=Number($('[data-range-from]').value),to=Number($('[data-range-to]').value),note=$('[data-note]').value.trim();
  if(!Number.isInteger(from)||!Number.isInteger(to)||from<0||to<from||to>=total()){announce(`Tick range must be within 0–${total()-1}.`);return;}
  if(!note){$('[data-note]').focus();return;}
  const id='local-task-'+crypto.randomUUID().slice(0,8);
  local.issues.push({id,status:'open',clip_revision_id:record.id,packet_id:record.packet.id,
    baseline_evaluation_id:record.evaluation.id,frame_instance_id:record.frames[Math.max(0,slotAt(from))].id,
    frame_range:[from,to],roi,category:$('[data-category]').value,note,created_at:new Date().toISOString(),origin:'local-design-prototype'});
  persist();renderQueue();renderSummary();$('[data-note]').value='';announce(`Correction queued locally · ${id}`);
}
document.addEventListener('click',e=>{
  const button=e.target.closest('button');if(!button)return;
  if(button.dataset.revision)selectRevision(button.dataset.revision);
  if(button.dataset.frame!==undefined)selectFrame(Number(button.dataset.frame));
  if(button.dataset.finding!==undefined){const r=record.evaluation.results[Number(button.dataset.finding)],s=resultSlot(r);if(s!==null)selectFrame(s);$('[data-category]').value=r.constraint_id.includes('silhouette')?'silhouette':r.constraint_id.includes('span')?'appearance':'general';}
  if(button.hasAttribute('data-play'))play();
  if(button.dataset.step){pause();tick=Math.max(0,Math.min(total()-1,Math.floor(tick)+Number(button.dataset.step)));renderPosition();}
  if(button.dataset.stepFrame)selectFrame(slot()+Number(button.dataset.stepFrame));
  if(button.dataset.mode){mode=button.dataset.mode;$('.viewer').dataset.mode=mode;$$('[data-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b===button)));draw();resizeStages();}
  if(button.hasAttribute('data-mark-region')){pause();marking=!marking;button.setAttribute('aria-pressed',String(marking));draw();}
  if(button.hasAttribute('data-clear-roi')){roi=null;updateScope();draw();}
  if(button.hasAttribute('data-check-filter')){allChecks=!allChecks;renderEvidence();}
  if(button.dataset.decide)decide(button.dataset.decide);
  if(button.hasAttribute('data-tasks')){pause();renderTasks();$('[data-tasks-dialog]').showModal();}
  if(button.hasAttribute('data-close-tasks'))$('[data-tasks-dialog]').close();
  if(button.dataset.replacement){$('[data-tasks-dialog]').close();selectRevision(button.dataset.replacement);mode='compare';renderRevision();}
  if(button.dataset.inspectTask){const i=local.issues.find(x=>x.id===button.dataset.inspectTask);$('[data-tasks-dialog]').close();selectRevision(i.clip_revision_id);tick=i.frame_range[0];roi=i.roi;rangeDirty=true;$('[data-range-from]').value=i.frame_range[0];$('[data-range-to]').value=i.frame_range[1];$('[data-note]').value=i.note;$('[data-category]').value=i.category;renderPosition();}
  if(button.dataset.resolve){const i=local.issues.find(x=>x.id===button.dataset.resolve),replacement=replacementFor(i);if(canResolve(i,replacement)){i.status='resolved';i.replacement_revision_id=replacement.id;i.replacement_evaluation_id=replacement.evaluation.id;persist();renderTasks();renderSummary();renderQueue();}}
  if(button.dataset.reopen){const i=local.issues.find(x=>x.id===button.dataset.reopen);i.status='reopened';for(const id of [i.clip_revision_id,i.replacement_revision_id].filter(Boolean)){const r=fixture.records.find(r=>r.id===id);local.events.push({id:crypto.randomUUID(),action:'needs_changes',clip_revision_id:id,expected_evaluation_id:r.evaluation.id,packet_id:r.packet.id,origin:'local-design-prototype',created_at:new Date().toISOString()});}persist();renderTasks();renderSummary();renderQueue();}
  if(button.hasAttribute('data-reset')){pause();local={events:[],issues:[]};persist();renderRevision();announce('Local review reset.');}
  if(button.hasAttribute('data-download')){const a=document.createElement('a'),url=URL.createObjectURL(new Blob([JSON.stringify({schema:'local-review-prototype-1',fixture_schema:fixture.schema,...local},null,2)],{type:'application/json'}));a.href=url;a.download='framebound-local-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
});
$('[data-correction-form]').addEventListener('submit',requestCorrection);
$('[data-correction-form]').addEventListener('focusin',()=>{if(playing)pause();});
[$('[data-range-from]'),$('[data-range-to]')].forEach(el=>el.addEventListener('input',()=>rangeDirty=true));
$('[data-scrub]').addEventListener('input',e=>{pause();tick=Number(e.target.value);renderPosition();});
$('[data-speed]').addEventListener('change',e=>{speed=Number(e.target.value);stamp=performance.now();});
$('[data-zoom]').addEventListener('change',resizeStages);
$('[data-masks]').addEventListener('change',e=>{masks=e.target.checked;draw();});
document.addEventListener('keydown',e=>{if(e.target.matches('input,textarea,select')||e.ctrlKey||e.metaKey||e.altKey||$('[data-tasks-dialog]').open)return;if(/^[1-5]$/.test(e.key)){location.href=pages[Number(e.key)-1];return;}if(e.code==='Space'&&!e.target.closest('button,a')){e.preventDefault();play();}if(e.key==='ArrowRight'){e.preventDefault();selectFrame(slot()+1);}if(e.key==='ArrowLeft'){e.preventDefault();selectFrame(slot()-1);}});
document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});
new ResizeObserver(resizeStages).observe($('.viewer'));
setInterval(()=>{if(mode==='blink')draw();},450);
renderRevision();
