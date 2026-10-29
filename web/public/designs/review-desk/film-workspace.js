/* A camera over a continuous reel. Pointer motion never mutates authored timing. */
window.FilmWorkspace = (() => {
  const R=window.Review, {esc,label,num,picture}=R;
  const positions=new Map();
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  let active=null, compare='reference';
  const svg=(name)=>`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${({left:'<path d="m14 6-6 6 6 6"/>',right:'<path d="m10 6 6 6-6 6"/>',play:'<path d="m8 5 11 7-11 7Z"/>',inspect:'<path d="M8 4H4v4m12-4h4v4M4 16v4h4m12-4v4h-4"/>',plus:'<path d="M12 5v14M5 12h14"/>',check:'<path d="m5 12 4 4L19 6"/>',folder:'<path d="M3 7V5h6l2 2h10v13H3Z"/>'})[name]||''}</svg>`;
  const frameName=r=>r.label+' · '+r.id.split('-').at(-1).slice(1);
  const time=t=>new Date(t).toLocaleString(undefined,{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',hour12:false});

  class ReelCamera {
    constructor(viewport,track,onPosition) {
      this.viewport=viewport;this.track=track;this.onPosition=onPosition;
      this.x=0;this.target=0;this.velocity=0;this.raf=0;this.drag=null;this.suppressUntil=0;
      this.abort=new AbortController();const options={signal:this.abort.signal};
      viewport.addEventListener('pointerdown',e=>this.down(e),options);
      viewport.addEventListener('pointermove',e=>this.move(e),options);
      viewport.addEventListener('pointerup',e=>this.up(e),options);
      viewport.addEventListener('pointercancel',e=>this.up(e,true),options);
      viewport.addEventListener('wheel',e=>this.wheel(e),{...options,passive:false});
      viewport.addEventListener('click',e=>{if(performance.now()<this.suppressUntil){e.preventDefault();e.stopImmediatePropagation();}}, {...options,capture:true});
      viewport.addEventListener('dragstart',e=>e.preventDefault(),options);
      this.resize=new ResizeObserver(()=>{const width=this.width,trackWidth=this.trackWidth;this.measure();if(width!==this.width||trackWidth!==this.trackWidth){this.jump(this.clamp(this.x));if(active?.camera===this&&active.model.view==='sequence')this.reveal(active.index,cellWidth(),true);}});
      this.resize.observe(viewport);this.measure();
    }
    measure(){
      this.width=this.viewport.clientWidth;this.trackWidth=this.track.offsetWidth;
      if(this.trackWidth<=this.width-48)this.min=this.max=(this.width-this.trackWidth)/2;
      else{this.max=24;this.min=this.width-this.trackWidth-24;}
    }
    clamp(x){return Math.max(this.min,Math.min(this.max,x));}
    rubber(x){return x>this.max?this.max+56*(1-Math.exp(-(x-this.max)/300)):x<this.min?this.min-56*(1-Math.exp(-(this.min-x)/300)):x;}
    paint(){this.track.style.transform=`translate3d(${this.x.toFixed(3)}px,0,0)`;this.onPosition(this.max===this.min?0:(this.max-this.x)/(this.max-this.min));}
    stop(){cancelAnimationFrame(this.raf);this.raf=0;this.velocity=0;}
    jump(x){this.stop();this.x=this.target=this.clamp(x);this.paint();}
    go(x,velocity=this.velocity){
      this.target=this.clamp(x);
      if(reduced.matches){this.jump(this.target);return;}
      this.stop();this.velocity=velocity;let previous=performance.now();
      const tick=now=>{
        const dt=Math.min(.032,Math.max(.001,(now-previous)/1000));previous=now;
        this.velocity+=((this.target-this.x)*190-this.velocity*28)*dt;
        this.x+=this.velocity*dt;
        if(Math.abs(this.target-this.x)<.12&&Math.abs(this.velocity)<.6){this.x=this.target;this.paint();this.raf=0;return;}
        this.paint();this.raf=requestAnimationFrame(tick);
      };
      this.raf=requestAnimationFrame(tick);
    }
    down(e){
      if(e.button!==0||e.target.closest('input,select,textarea'))return;
      this.stop();this.suppressUntil=0;this.drag={id:e.pointerId,startX:e.clientX,startY:e.clientY,x:this.x,lastX:e.clientX,lastTime:performance.now(),speed:0,moved:false};
    }
    move(e){
      const d=this.drag;if(!d||d.id!==e.pointerId)return;
      const dx=e.clientX-d.startX,dy=e.clientY-d.startY;
      if(!d.moved){if(Math.abs(dx)<7||Math.abs(dx)<Math.abs(dy)*.8)return;d.moved=true;this.viewport.setPointerCapture(e.pointerId);this.viewport.classList.add('is-dragging');}
      e.preventDefault();const now=performance.now(),dt=Math.max(1,now-d.lastTime);
      d.speed=d.speed*.6+(e.clientX-d.lastX)/dt*.4;d.lastX=e.clientX;d.lastTime=now;
      this.x=this.rubber(d.x+dx);this.paint();
    }
    up(e,cancelled=false){
      const d=this.drag;if(!d||d.id!==e.pointerId)return;
      this.drag=null;this.viewport.classList.remove('is-dragging');
      if(this.viewport.hasPointerCapture(e.pointerId))this.viewport.releasePointerCapture(e.pointerId);
      if(d.moved){this.suppressUntil=performance.now()+320;const speed=cancelled||performance.now()-d.lastTime>90?0:Math.max(-3.2,Math.min(3.2,d.speed));this.go(this.x+(reduced.matches?0:speed*170),speed*180);}else if(this.x!==this.clamp(this.x))this.go(this.x);
    }
    wheel(e){
      e.preventDefault();const unit=e.deltaMode===1?16:e.deltaMode===2?this.width:1;
      const delta=(Math.abs(e.deltaX)>Math.abs(e.deltaY)?e.deltaX:e.deltaY)*unit;
      this.go((this.raf?this.target:this.x)-delta);
    }
    reveal(index,cellWidth,force=false){
      const left=this.x+index*cellWidth,right=left+cellWidth;
      if(force||left<36||right>this.width-36)this.go(this.width/2-(index+.5)*cellWidth);
    }
    destroy(){this.stop();this.abort.abort();this.resize.disconnect();}
  }

  function entries(model){
    if(model.view==='timeline')return model.events.map(e=>({id:e.id,record:e.record,event:e,title:e.title,subtitle:model.revisionName(e.record),meta:time(e.at),outcome:e.outcome||e.actor,frame:Math.min(3,e.record.frames.length-1)}));
    if(model.view==='interventions')return model.interventions.map(i=>({id:i.id,record:i.record,item:i,title:i.title.replace('Review missing evidence','Missing evidence'),subtitle:frameName(i.record),meta:i.kind==='evidence'?(i.finding?.outcome==='unmeasured'?'Unmeasured':'Failed checks'):i.kind==='correction'?'Correction':'Human review',outcome:i.kind==='evidence'?'incomplete':'human',frame:i.finding&&R.scoped(i.finding)!==null?R.scoped(i.finding):Math.min(3,i.record.frames.length-1)}));
    return model.records.map(r=>({id:r.id,record:r,title:frameName(r),subtitle:R.acceptance(r),meta:'Technical '+r.evaluation.technical_status,outcome:r.evaluation.technical_status,frame:Math.min(3,r.frames.length-1)}));
  }

  function menu(model){
    const current=model.view==='sequence'?model.returnView:model.view;
    return `<div class="reel-menus"><label class="reel-project">${svg('folder')}<span class="sr-only">Project</span><select data-film-project aria-label="Project"><option value="all" ${model.project==='all'?'selected':''}>All projects</option>${model.projects.map(p=>`<option value="${esc(p.id)}" ${model.project===p.id?'selected':''}>${esc(p.name)}</option>`).join('')}</select></label><nav class="reel-views" aria-label="Review views">${[['interventions','Interventions'],['timeline','Timeline'],['sequences','Sequences']].map(([v,n])=>`<button data-desk-view="${v}" aria-current="${v===current?'page':'false'}">${n}${v==='interventions'?`<span>${model.interventions.length}</span>`:''}</button>`).join('')}</nav><div class="reel-menu-tools">${model.view==='timeline'?`<select data-activity-source aria-label="Activity source"><option value="all">All activity</option><option value="framework" ${model.actor==='framework'?'selected':''}>Framework</option><option value="human" ${model.actor==='human'?'selected':''}>Human review</option></select><select data-time-order aria-label="Chronological order"><option value="oldest" ${model.order==='oldest'?'selected':''}>Oldest first</option><option value="newest" ${model.order==='newest'?'selected':''}>Newest first</option></select>`:model.view==='sequence'?`<select data-revision-select aria-label="Clip revision">${model.records.map(r=>`<option value="${r.id}" ${r.id===R.state.id?'selected':''}>${esc(frameName(r))}</option>`).join('')}</select>${R.base()?`<select data-reel-comparison aria-label="Compare candidate with"><option value="reference" ${compare==='reference'?'selected':''}>Phase reference</option><option value="baseline" ${compare==='baseline'?'selected':''}>Baseline</option></select>`:''}`:''}</div></div>`;
  }

  function badge(entry){
    return entry.event?`<time class="shot-outcome ${esc(entry.outcome)}" datetime="${esc(entry.event.at)}" title="${esc(entry.event.at)}">${esc(entry.meta)}</time>`:`<span class="shot-outcome ${esc(entry.outcome)}">${esc(entry.meta)}</span>`;
  }

  function collection(model,items){
    return `<div class="reel-camera" data-reel-camera tabindex="0" role="region" aria-label="Draggable ${model.view} film"><div class="reel-surface"><div class="reel-track reel-collection" data-reel-track style="--cell-count:${items.length}"><div class="reel-stock"><div class="reel-shot-row">${items.map((entry,index)=>`<button class="reel-shot" data-reel-item="${index}" aria-pressed="false" aria-label="${esc(entry.title+', '+entry.subtitle)}"><span class="shot-aperture">${picture(entry.record.frames[entry.frame].url,entry.subtitle).replace('<img','<img draggable="false"')}<span class="shot-caption">${model.project==='all'&&model.projects.length>1?`<span class="shot-project">${esc(model.projectName(entry.record.project_id))}</span>`:''}<strong>${esc(entry.title)}</strong><span>${esc(entry.subtitle)}</span></span>${badge(entry)}</span></button>`).join('')}</div></div></div></div><div class="reel-vignette" aria-hidden="true"></div></div>`;
  }

  function sequence(){
    const r=R.record(),base=R.base(),reference=compare==='baseline'&&base?base.frames:r.references;
    const rows=[[compare==='baseline'&&base?'Baseline':'Reference',reference,'reference'],['Candidate',r.frames,'candidate']];
    return `<div class="reel-camera reel-sequence-camera" data-reel-camera tabindex="0" role="region" aria-label="Draggable frame comparison"><div class="reel-surface"><div class="reel-track reel-sequence" data-reel-track style="--cell-count:${r.frames.length}"><div class="reel-ruler">${r.frames.map((f,i)=>`<button data-reel-frame="${i}" aria-label="Frame ${i+1}" aria-pressed="${R.state.selectedColumns.includes(i)}">${num(i+1)}</button>`).join('')}</div>${rows.map(([name,frames,kind])=>`<div class="reel-stock reel-lane ${kind}"><div class="reel-shot-row">${frames.map((f,i)=>`<button class="reel-frame" data-reel-frame="${i}" aria-label="${name}, frame ${i+1}" aria-pressed="${R.state.selectedColumns.includes(i)}"><span class="frame-aperture">${picture(f.url,name+' frame '+(i+1)).replace('<img','<img draggable="false"')}${kind==='candidate'?'<span class="frame-focus-mark" aria-hidden="true"></span>':''}</span></button>`).join('')}</div></div>`).join('')}</div></div><div class="reel-lane-labels" aria-hidden="true">${rows.map(([name,frames,kind])=>`<div class="reel-lane-label ${kind}"><strong>${name}</strong></div>`).join('')}</div><div class="reel-vignette" aria-hidden="true"></div></div>`;
  }

  function dock(model,total){
    const seq=model.view==='sequence';
    return `<footer class="reel-dock"><div class="reel-navigation"><button data-reel-step="-1" class="reel-icon" aria-label="Previous ${seq?'frame':'item'}">${svg('left')}</button><output class="reel-counter" data-reel-counter aria-live="polite"></output><button data-reel-step="1" class="reel-icon" aria-label="Next ${seq?'frame':'item'}">${svg('right')}</button></div><div class="reel-focus-caption" data-reel-caption></div><label class="reel-position"><span class="sr-only">Film position</span><input data-reel-pan type="range" min="0" max="1000" value="0" aria-label="Film position"></label><div class="reel-actions">${seq?`<button class="reel-icon" data-reel-play aria-label="Play animation">${svg('play')}</button><button class="reel-secondary" data-inspect="evidence">Evidence</button><button class="reel-secondary" data-reel-correction>${svg('plus')}<span>Correction</span></button><button class="reel-primary" data-inspect="decision">Decision ${svg('check')}</button>`:`<button class="reel-primary" data-reel-open ${total?'':'disabled'}>${model.view==='timeline'?'Details':'Review'} ${svg('right')}</button>`}</div></footer>`;
  }

  function ensureEventDialog(){
    if(R.$('[data-film-event]'))return;
    R.$('[data-common]').insertAdjacentHTML('beforeend','<dialog class="inspector film-event-dialog" data-film-event><button class="film-event-close reel-icon" data-close-film-event aria-label="Close event">×</button><div data-film-event-body></div></dialog>');
  }

  function render(model,actions,icons){
    const previous=active;
    if(previous){positions.set(previous.key,{x:previous.camera.x,index:previous.index,id:previous.items[previous.index]?.id});previous.camera.destroy();}
    const seq=model.view==='sequence',items=seq?[]:entries(model),r=R.record();
    const key=[model.view,model.project,model.actor,model.order,seq?r.id:''].join('|'),saved=positions.get(key);
    let index=seq?R.state.frame:model.view==='timeline'&&model.selectedEvent?items.findIndex(e=>e.id===model.selectedEvent):saved?.id?items.findIndex(e=>e.id===saved.id):saved?.index||0;
    index=Math.max(0,Math.min((seq?r.frames.length:items.length)-1,index));
    const app=R.$('[data-app]');app.className='film-desk';app.dataset.filmView=model.view;
    app.innerHTML=`<h1 class="sr-only">${seq?'Sequence review':label(model.view)}</h1>`+menu(model)+(seq?sequence():items.length?collection(model,items):'<div class="reel-empty">No recorded items.</div>')+dock(model,seq?r.frames.length:items.length);
    ensureEventDialog();
    if(!seq&&!items.length){active=null;R.$('[data-reel-counter]').textContent='0 / 0';R.$('[data-reel-pan]').disabled=true;R.$$('[data-reel-step]').forEach(b=>b.disabled=true);return;}
    const viewport=R.$('[data-reel-camera]'),track=R.$('[data-reel-track]'),range=R.$('[data-reel-pan]');
    const camera=new ReelCamera(viewport,track,p=>{range.value=String(Math.round(Math.max(0,Math.min(1,p))*1000));});
    active={key,model,actions,icons,items,index,camera};
    if(saved)camera.jump(saved.x);else camera.jump(camera.max);
    if(seq&&!saved)camera.reveal(index,cellWidth(),true);else if(!saved&&index>0)camera.reveal(index,cellWidth());
    if(previous?.key===key)app.classList.add('reel-retained');
    update(false);
    if(R.$('[data-film-event]').open)updateEventDialog();
  }

  function cellWidth(){return active?.camera.trackWidth/(active.model.view==='sequence'?R.record().frames.length:active.items.length)||1;}
  function update(reveal=false){
    if(!active)return;const seq=active.model.view==='sequence';if(seq){active.index=R.state.frame;if(!R.state.range&&R.state.selectedColumns.length===1)R.state.selectedColumns=[R.state.frame];}
    const total=seq?R.record().frames.length:active.items.length,index=active.index,entry=active.items[index];
    R.$('[data-reel-counter]').textContent=num(index+1)+' / '+num(total);
    R.$$('[data-reel-step]').forEach(b=>b.disabled=Number(b.dataset.reelStep)<0?index===0:index===total-1);
    if(seq){
      R.$$('[data-reel-frame]').forEach(el=>{el.setAttribute('aria-pressed',String(R.state.selectedColumns.includes(Number(el.dataset.reelFrame))));el.classList.toggle('is-current',Number(el.dataset.reelFrame)===R.state.frame);});
      const columns=R.state.selectedColumns,from=R.start(Math.min(...columns)),last=Math.max(...columns),to=R.start(last)+R.record().frames[last].hold_ticks-1;
      R.$('[data-reel-caption]').innerHTML=`<strong>${columns.length>1?columns.length+' frames':esc(label(R.record().frames[index].phase))}</strong><span>${from}–${to} ticks</span><span class="reel-technical ${R.record().evaluation.technical_status}">Technical ${R.record().evaluation.technical_status}</span>`;
    }else{
      R.$$('[data-reel-item]').forEach(el=>el.setAttribute('aria-pressed',String(Number(el.dataset.reelItem)===index)));
      R.$('[data-reel-caption]').innerHTML=entry?`<strong>${esc(entry.subtitle)}</strong><span>${esc(entry.meta)}</span>`:'';
      if(active.model.view==='timeline'&&entry)active.actions.setEvent(entry.id);
    }
    if(reveal)active.camera.reveal(index,cellWidth());
  }

  function focus(index,shift=false){
    if(!active)return;const seq=active.model.view==='sequence',total=seq?R.record().frames.length:active.items.length;
    index=Math.max(0,Math.min(total-1,index));active.index=index;
    if(seq){const anchor=R.state.selectedColumns[0];R.state.selectedColumns=shift?Array.from({length:Math.abs(anchor-index)+1},(_,i)=>Math.min(anchor,index)+i):[index];R.state.range=null;R.selectFrame(index,false);}
    update(true);
  }
  function open(){
    if(!active)return;
    if(active.model.view==='sequence'){R.inspect('film');return;}
    const entry=active.items[active.index];if(!entry)return;
    if(active.model.view==='timeline'){active.actions.setEvent(entry.id);updateEventDialog();R.$('[data-film-event]').showModal();}
    else if(entry.item)active.actions.openIntervention(entry.record.id);
    else active.actions.openSequence(entry.record.id);
  }
  function updateEventDialog(){
    if(!active||active.model.view!=='timeline')return;
    const entry=active.items[active.index];if(!entry)return;
    R.$('[data-film-event-body]').innerHTML=active.model.detail(entry.event,active.model.events);
  }
  function correction(){
    const cols=R.state.selectedColumns,first=Math.min(...cols),last=Math.max(...cols);
    R.selectFrame(first,false);R.state.range=[R.start(first),R.start(last)+R.record().frames[last].hold_ticks-1];R.inspect('correction');
  }

  document.addEventListener('click',e=>{
    const button=e.target.closest('button');if(!button)return;
    if(button.hasAttribute('data-close-film-event'))R.$('[data-film-event]').close();
    if(button.closest('[data-film-event]')&&(button.dataset.openSequence||button.dataset.eventInspect||button.dataset.checkIndex!==undefined||button.dataset.inspectIssue))R.$('[data-film-event]').close();
    if(button.dataset.reelItem!==undefined)focus(Number(button.dataset.reelItem));
    if(button.dataset.reelFrame!==undefined)focus(Number(button.dataset.reelFrame),e.shiftKey);
    if(button.dataset.reelStep&&active)focus(active.index+Number(button.dataset.reelStep));
    if(button.hasAttribute('data-reel-open'))open();
    if(button.hasAttribute('data-reel-play')){R.inspect('film');R.play();}
    if(button.hasAttribute('data-reel-correction'))correction();
  });
  document.addEventListener('dblclick',e=>{if(e.target.closest('[data-reel-item],[data-reel-frame]')&&active&&performance.now()>active.camera.suppressUntil)open();});
  document.addEventListener('input',e=>{if(e.target.matches('[data-reel-pan]')&&active)active.camera.jump(active.camera.max-Number(e.target.value)/1000*(active.camera.max-active.camera.min));});
  document.addEventListener('change',e=>{if(e.target.matches('[data-reel-comparison]')&&active){compare=e.target.value;render(active.model,active.actions,active.icons);}});
  document.addEventListener('keydown',e=>{
    if(!active||R.$('[data-inspector]')?.open||R.$('[data-film-event]')?.open||e.target.matches('input,select,textarea')||e.ctrlKey||e.metaKey||e.altKey)return;
    if(e.key==='ArrowLeft'||e.key==='ArrowRight'||e.key==='Home'||e.key==='End'){
      e.preventDefault();e.stopImmediatePropagation();const total=active.model.view==='sequence'?R.record().frames.length:active.items.length;
      focus(e.key==='Home'?0:e.key==='End'?total-1:active.index+(e.key==='ArrowRight'?1:-1),e.shiftKey);
    }
  },true);
  document.addEventListener('close',e=>{if(e.target.matches('[data-film-event]')&&active?.model.view==='timeline'){update(true);R.$('[data-reel-open]')?.focus({preventScroll:true});}if(e.target.matches('[data-inspector]')&&active?.model.view==='sequence')update(true);},true);
  R.subscribe(full=>{if(!full&&active?.model.view==='sequence')update(false);});
  return {render};
})();
