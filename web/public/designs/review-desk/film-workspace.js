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
      this.x=0;this.y=0;this.zoom=1;this.targetZoom=1;this.target=0;this.targetY=0;
      this.velocity=0;this.velocityY=0;this.raf=0;this.zoomRaf=0;this.drag=null;this.pinch=null;this.pointers=new Map();this.suppressUntil=0;
      this.abort=new AbortController();const options={signal:this.abort.signal};
      viewport.addEventListener('pointerdown',e=>this.down(e),options);
      viewport.addEventListener('pointermove',e=>this.move(e),options);
      viewport.addEventListener('pointerup',e=>this.up(e),options);
      viewport.addEventListener('pointercancel',e=>this.up(e,true),options);
      viewport.addEventListener('wheel',e=>this.wheel(e),{...options,passive:false});
      viewport.addEventListener('click',e=>{if(performance.now()<this.suppressUntil){e.preventDefault();e.stopImmediatePropagation();}}, {...options,capture:true});
      viewport.addEventListener('dragstart',e=>e.preventDefault(),options);
      this.resize=new ResizeObserver(()=>{
        const width=this.width,height=this.height,trackWidth=this.trackWidth,trackHeight=this.trackHeight;this.measure();
        if(width!==this.width||height!==this.height||trackWidth!==this.trackWidth||trackHeight!==this.trackHeight){this.jump(this.x,this.y);if(active?.camera===this&&active.model.view==='sequence')this.reveal(active.index,cellWidth(),true);}
      });
      this.resize.observe(viewport);this.measure();
    }
    measure(){
      this.width=this.viewport.clientWidth;this.height=this.viewport.clientHeight;
      this.trackWidth=this.track.offsetWidth;this.trackHeight=this.track.offsetHeight;
      this.lanes=[...this.track.querySelectorAll('.reel-lane')].map(row=>({top:row.offsetTop,height:row.offsetHeight-(row.querySelector('.frame-evidence')?row.querySelector('.frame-evidence').offsetHeight+14:0)}));
      this.labels=[...this.viewport.querySelectorAll('.reel-lane-label')];this.bounds();
    }
    bounds(){
      const width=this.trackWidth*this.zoom,height=this.trackHeight*this.zoom;
      if(width<=this.width-48)this.min=this.max=(this.width-width)/2;else{this.max=24;this.min=this.width-width-24;}
      if(height<=this.height-24)this.minY=this.maxY=0;else{this.maxY=(height-this.height)/2+12;this.minY=-this.maxY;}
    }
    clamp(x){return Math.max(this.min,Math.min(this.max,x));}
    clampY(y){return Math.max(this.minY,Math.min(this.maxY,y));}
    rubber(x,min=this.min,max=this.max){return x>max?max+56*(1-Math.exp(-(x-max)/300)):x<min?min-56*(1-Math.exp(-(min-x)/300)):x;}
    paint(){
      this.track.style.transform=`translate3d(${this.x.toFixed(3)}px,${this.y.toFixed(3)}px,0) scale(${this.zoom.toFixed(5)})`;
      this.labels.forEach((node,i)=>{const row=this.lanes[i];if(!row)return;const top=this.height/2+this.y+(row.top-this.trackHeight/2)*this.zoom,height=row.height*this.zoom;node.style.top=top+'px';node.style.height=height+'px';node.style.setProperty('--label-y',(Math.max(18,Math.min(this.height-18,top+height/2))-top)+'px');});
      this.onPosition(this.max===this.min?0:(this.max-this.x)/(this.max-this.min),this.zoom);
    }
    stop(){cancelAnimationFrame(this.raf);cancelAnimationFrame(this.zoomRaf);this.raf=this.zoomRaf=0;this.velocity=this.velocityY=0;}
    jump(x,y=this.y){this.stop();this.x=this.target=this.clamp(x);this.y=this.targetY=this.clampY(y);this.paint();}
    go(x,velocity=this.velocity,y=this.y,velocityY=this.velocityY){
      this.target=this.clamp(x);this.targetY=this.clampY(y);
      if(reduced.matches){this.jump(this.target,this.targetY);return;}
      this.stop();this.velocity=velocity;this.velocityY=velocityY;let previous=performance.now();
      const tick=now=>{
        const dt=Math.min(.032,Math.max(.001,(now-previous)/1000));previous=now;
        this.velocity+=((this.target-this.x)*190-this.velocity*28)*dt;this.velocityY+=((this.targetY-this.y)*190-this.velocityY*28)*dt;
        this.x+=this.velocity*dt;this.y+=this.velocityY*dt;
        if(Math.abs(this.target-this.x)<.12&&Math.abs(this.targetY-this.y)<.12&&Math.abs(this.velocity)<.6&&Math.abs(this.velocityY)<.6){this.x=this.target;this.y=this.targetY;this.paint();this.raf=0;return;}
        this.paint();this.raf=requestAnimationFrame(tick);
      };this.raf=requestAnimationFrame(tick);
    }
    zoomTo(value,px=this.width/2,py=this.height/2,direct=false){
      const target=Math.max(.05,Math.min(2,value)),start=this.zoom,worldX=(px-this.x)/start,worldY=(py-this.height/2-this.y)/start;
      this.stop();this.targetZoom=target;const began=performance.now();
      const apply=z=>{this.zoom=z;this.bounds();this.x=this.clamp(px-worldX*z);this.y=this.clampY(py-this.height/2-worldY*z);this.paint();};
      if(direct||reduced.matches){apply(target);return;}
      const tick=now=>{const t=Math.min(1,(now-began)/240),ease=1-Math.pow(1-t,3);apply(start+(target-start)*ease);if(t<1)this.zoomRaf=requestAnimationFrame(tick);else this.zoomRaf=0;};
      this.zoomRaf=requestAnimationFrame(tick);
    }
    fit(){this.zoomTo(Math.min((this.width-48)/this.trackWidth,(this.height-24)/this.trackHeight,1));}
    local(e){const box=this.viewport.getBoundingClientRect();return{x:e.clientX-box.left,y:e.clientY-box.top};}
    down(e){
      if(e.button!==0||e.target.closest('input,select,textarea'))return;
      this.stop();this.suppressUntil=0;
      if(e.pointerType==='touch'){
        this.pointers.set(e.pointerId,this.local(e));if(this.pointers.size>2)return;
        if(this.pointers.size===2){const [a,b]=[...this.pointers.values()],x=(a.x+b.x)/2,y=(a.y+b.y)/2;this.pinch={distance:Math.max(1,Math.hypot(b.x-a.x,b.y-a.y)),zoom:this.zoom,worldX:(x-this.x)/this.zoom,worldY:(y-this.height/2-this.y)/this.zoom};this.drag=null;for(const id of this.pointers.keys())this.viewport.setPointerCapture(id);return;}
      }
      this.drag={id:e.pointerId,startX:e.clientX,startY:e.clientY,x:this.x,y:this.y,lastX:e.clientX,lastY:e.clientY,lastTime:performance.now(),speed:0,speedY:0,moved:false};
    }
    move(e){
      if(this.pointers.has(e.pointerId))this.pointers.set(e.pointerId,this.local(e));
      if(this.pinch&&this.pointers.size===2){
        e.preventDefault();const [a,b]=[...this.pointers.values()],p=this.pinch,x=(a.x+b.x)/2,y=(a.y+b.y)/2;
        this.zoom=Math.max(.05,Math.min(2,p.zoom*Math.hypot(b.x-a.x,b.y-a.y)/p.distance));this.targetZoom=this.zoom;this.bounds();this.x=this.clamp(x-p.worldX*this.zoom);this.y=this.clampY(y-this.height/2-p.worldY*this.zoom);this.paint();return;
      }
      const d=this.drag;if(!d||d.id!==e.pointerId)return;
      const dx=e.clientX-d.startX,dy=e.clientY-d.startY,vertical=this.minY!==this.maxY;
      if(!d.moved){if(Math.hypot(dx,vertical?dy:0)<7||(!vertical&&Math.abs(dx)<Math.abs(dy)*.8))return;d.moved=true;this.viewport.setPointerCapture(e.pointerId);this.viewport.classList.add('is-dragging');}
      e.preventDefault();const now=performance.now(),dt=Math.max(1,now-d.lastTime);
      d.speed=d.speed*.6+(e.clientX-d.lastX)/dt*.4;d.speedY=d.speedY*.6+(e.clientY-d.lastY)/dt*.4;d.lastX=e.clientX;d.lastY=e.clientY;d.lastTime=now;
      this.x=this.rubber(d.x+dx);this.y=vertical?this.rubber(d.y+dy,this.minY,this.maxY):0;this.paint();
    }
    up(e,cancelled=false){
      this.pointers.delete(e.pointerId);if(this.viewport.hasPointerCapture(e.pointerId))this.viewport.releasePointerCapture(e.pointerId);
      if(this.pinch){if(this.pointers.size<2){this.pinch=null;this.viewport.classList.remove('is-dragging');this.suppressUntil=performance.now()+320;this.go(this.x,0,this.y,0);}if(this.viewport.hasPointerCapture(e.pointerId))this.viewport.releasePointerCapture(e.pointerId);return;}
      const d=this.drag;if(!d||d.id!==e.pointerId)return;
      this.drag=null;this.viewport.classList.remove('is-dragging');
      if(this.viewport.hasPointerCapture(e.pointerId))this.viewport.releasePointerCapture(e.pointerId);
      if(d.moved){const stale=cancelled||performance.now()-d.lastTime>90,sx=stale?0:Math.max(-3.2,Math.min(3.2,d.speed)),sy=stale?0:Math.max(-3.2,Math.min(3.2,d.speedY));this.suppressUntil=performance.now()+320;this.go(this.x+(reduced.matches?0:sx*170),sx*180,this.y+(reduced.matches?0:sy*170),sy*180);}
      else if(this.x!==this.clamp(this.x)||this.y!==this.clampY(this.y))this.go(this.x,0,this.y,0);
    }
    wheel(e){
      e.preventDefault();const unit=e.deltaMode===1?16:e.deltaMode===2?this.width:1;
      if(e.ctrlKey||e.metaKey){const p=this.local(e);this.zoomTo(this.zoom*Math.exp(-e.deltaY*.008),p.x,p.y,true);return;}
      if(this.minY!==this.maxY&&!e.shiftKey){this.go((this.raf?this.target:this.x)-e.deltaX*unit,this.velocity,(this.raf?this.targetY:this.y)-e.deltaY*unit);return;}
      const delta=(Math.abs(e.deltaX)>Math.abs(e.deltaY)?e.deltaX:e.deltaY)*unit;this.go((this.raf?this.target:this.x)-delta);
    }
    reveal(index,width,force=false){const size=width*this.zoom,left=this.x+index*size,right=left+size;if(force||left<36||right>this.width-36)this.go(this.width/2-(index+.5)*size);}
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

  function frameEvidence(r,index){
    const checks=r.evaluation.results;
    const metrics=[['Area','silhouette-area'],['Width','silhouette-width']].map(([name,id])=>{
      const check=checks.find(c=>c.constraint_id===id&&R.scoped(c)===index);
      return `<button class="frame-measure ${check?.outcome||'unmeasured'}" data-reel-measure="${check?checks.indexOf(check):-1}" data-reel-at="${index}" aria-label="${name} drift, frame ${index+1}: ${check?R.checkValue(check):'unmeasured'}" title="${esc(check?.reason||'Unmeasured')}"><span>${name}</span><strong>${check?R.checkValue(check):'—'}</strong><small>${check?.expected_interval?'≤ '+R.bound(check).split('–').at(-1):'Unmeasured'}</small></button>`;
    }).join('');
    const first=R.start(index,r),last=first+r.frames[index].hold_ticks-1;
    const issues=R.issues(r).filter(i=>i.frame_range[0]<=last&&i.frame_range[1]>=first);
    const unknown=checks.find(c=>R.scoped(c)===index&&['error','unmeasured'].includes(c.outcome));
    return `<div class="frame-evidence" aria-label="Frame ${index+1} evidence and corrections">${metrics}<div class="frame-corrections">${issues.length?`<button class="frame-issue ${issues.some(i=>i.status!=='resolved')?'open':'resolved'}" data-inspect-issue="${issues[0].id}" title="${esc(issues.map(i=>label(i.category)+' · '+i.status+' · '+i.note+' · ticks '+i.frame_range.join('–')).join('\n'))}"><span class="issue-dot" aria-hidden="true"></span><span><strong>${issues.length>1?issues.length+' corrections':esc(label(issues[0].category))}</strong><small>${esc(issues[0].status)}${issues[0].clip_revision_id!==r.id?' · '+esc(issues[0].clip_revision_id.split('-').at(-1)):''}</small><span class="correction-note">${esc(issues[0].note)}</span></span></button>`:unknown?`<button class="frame-unknown" data-reel-measure="${checks.indexOf(unknown)}" data-reel-at="${index}" title="${esc(unknown.reason)}">${esc(label(unknown.constraint_id))}<span>${esc(unknown.outcome)}</span></button>`:'<span class="frame-no-issues">Corrections <span>0</span></span>'}<button class="frame-add-correction" data-reel-add="${index}" aria-label="Request correction for frame ${index+1}">${svg('plus')}</button></div></div>`;
  }

  function sequence(){
    const r=R.record(),base=R.base(),reference=compare==='baseline'&&base?base.frames:r.references;
    const rows=[[compare==='baseline'&&base?'Baseline':'Reference',reference,'reference'],['Candidate',r.frames,'candidate']];
    return `<div class="reel-camera reel-sequence-camera" data-reel-camera tabindex="0" role="region" aria-label="Draggable frame comparison"><div class="reel-surface"><div class="reel-track reel-sequence" data-reel-track style="--cell-count:${r.frames.length}"><div class="reel-ruler">${r.frames.map((f,i)=>`<button data-reel-frame="${i}" aria-label="Frame ${i+1}" aria-pressed="${R.state.selectedColumns.includes(i)}">${num(i+1)}</button>`).join('')}</div>${rows.map(([name,frames,kind])=>`<div class="reel-stock reel-lane ${kind}"><div class="reel-shot-row">${frames.map((f,i)=>`<div class="reel-frame-unit"><button class="reel-frame" data-reel-frame="${i}" aria-label="${name}, frame ${i+1}" aria-pressed="${R.state.selectedColumns.includes(i)}"><span class="frame-aperture">${picture(f.url,name+' frame '+(i+1)).replace('<img','<img draggable="false"')}${kind==='candidate'?'<span class="frame-focus-mark" aria-hidden="true"></span>':''}</span></button>${kind==='candidate'?frameEvidence(r,i):''}</div>`).join('')}</div></div>`).join('')}</div></div><div class="reel-lane-labels" aria-hidden="true">${rows.map(([name,frames,kind])=>`<div class="reel-lane-label ${kind}"><strong>${name}</strong></div>`).join('')}</div><div class="reel-vignette" aria-hidden="true"></div></div>`;
  }

  function dock(model,total){
    const seq=model.view==='sequence';
    return `<footer class="reel-dock"><div class="reel-navigation"><button data-reel-step="-1" class="reel-icon" aria-label="Previous ${seq?'frame':'item'}">${svg('left')}</button><output class="reel-counter" data-reel-counter aria-live="polite"></output><button data-reel-step="1" class="reel-icon" aria-label="Next ${seq?'frame':'item'}">${svg('right')}</button></div><div class="reel-focus-caption" data-reel-caption></div><div class="reel-zoom" role="group" aria-label="Film zoom"><button data-reel-zoom="-1" aria-label="Zoom out">−</button><button class="zoom-value" data-reel-zoom-reset aria-label="Reset zoom to 100%" title="Reset zoom to 100%">100%</button><button data-reel-zoom="1" aria-label="Zoom in">+</button><button data-reel-fit title="Fit film in view">Fit</button></div><label class="reel-position"><span class="sr-only">Film position</span><input data-reel-pan type="range" min="0" max="1000" value="0" aria-label="Film position"></label><div class="reel-actions">${seq?`<button class="reel-icon" data-reel-play aria-label="Play animation">${svg('play')}</button><button class="reel-secondary" data-inspect="evidence">Evidence</button><button class="reel-secondary" data-reel-correction aria-label="Request correction">${svg('plus')}<span>Correction</span></button><button class="reel-primary" data-inspect="decision">Decision ${svg('check')}</button>`:`<button class="reel-primary" data-reel-open ${total?'':'disabled'}>${model.view==='timeline'?'Details':'Review'} ${svg('right')}</button>`}</div></footer>`;
  }

  function ensureEventDialog(){
    if(R.$('[data-film-event]'))return;
    R.$('[data-common]').insertAdjacentHTML('beforeend','<dialog class="inspector film-event-dialog" data-film-event><button class="film-event-close reel-icon" data-close-film-event aria-label="Close event">×</button><div data-film-event-body></div></dialog>');
  }

  function render(model,actions,icons){
    const previous=active;
    if(previous){positions.set(previous.key,{x:previous.camera.x,y:previous.camera.y,zoom:previous.camera.zoom,index:previous.index,id:previous.items[previous.index]?.id});previous.camera.destroy();}
    const seq=model.view==='sequence',items=seq?[]:entries(model),r=R.record();
    const key=[model.view,model.project,model.actor,model.order,seq?r.id:''].join('|'),saved=positions.get(key);
    let index=seq?R.state.frame:model.view==='timeline'&&model.selectedEvent?items.findIndex(e=>e.id===model.selectedEvent):saved?.id?items.findIndex(e=>e.id===saved.id):saved?.index||0;
    index=Math.max(0,Math.min((seq?r.frames.length:items.length)-1,index));
    const app=R.$('[data-app]');app.className='film-desk';app.dataset.filmView=model.view;
    app.innerHTML=`<h1 class="sr-only">${seq?'Sequence review':label(model.view)}</h1>`+menu(model)+(seq?sequence():items.length?collection(model,items):'<div class="reel-empty">No recorded items.</div>')+dock(model,seq?r.frames.length:items.length);
    ensureEventDialog();
    if(!seq&&!items.length){active=null;R.$('[data-reel-counter]').textContent='0 / 0';R.$('[data-reel-pan]').disabled=true;R.$$('[data-reel-step],[data-reel-zoom],[data-reel-zoom-reset],[data-reel-fit]').forEach(b=>b.disabled=true);return;}
    const viewport=R.$('[data-reel-camera]'),track=R.$('[data-reel-track]'),range=R.$('[data-reel-pan]');
    const camera=new ReelCamera(viewport,track,(p,z)=>{
      range.value=String(Math.round(Math.max(0,Math.min(1,p))*1000));
      const percent=Math.round(z*100),readout=R.$('[data-reel-zoom-reset]');readout.textContent=percent+'%';readout.setAttribute('aria-label','Zoom '+percent+'%. Reset to 100%.');
      R.$$('[data-reel-zoom]').forEach(b=>b.disabled=Number(b.dataset.reelZoom)<0?z<=.051:z>=1.999);
      const detail=camera.trackWidth/(seq?r.frames.length:items.length)*z>=300?'expanded':'compact';if(viewport.dataset.zoomDetail!==detail)viewport.dataset.zoomDetail=detail;
    });
    active={key,model,actions,icons,items,index,camera};
    camera.zoom=camera.targetZoom=saved?.zoom||(previous?.model.view===model.view?previous.camera.zoom:1);camera.bounds();if(saved)camera.jump(saved.x,saved.y||0);else camera.jump(camera.max);
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
    if(button.dataset.reelAdd!==undefined){focus(Number(button.dataset.reelAdd));correction();}
    if(button.dataset.reelMeasure!==undefined){focus(Number(button.dataset.reelAt));R.inspect('evidence');}
    if(button.dataset.reelZoom&&active){const levels=[.05,.1,.25,.5,.75,1,1.25,1.5,2],z=active.camera.zoomRaf?active.camera.targetZoom:active.camera.zoom,target=Number(button.dataset.reelZoom)>0?levels.find(v=>v>z+.01):[...levels].reverse().find(v=>v<z-.01);active.camera.zoomTo(target??z);}
    if(button.hasAttribute('data-reel-zoom-reset')&&active)active.camera.zoomTo(1);
    if(button.hasAttribute('data-reel-fit')&&active)active.camera.fit();
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
