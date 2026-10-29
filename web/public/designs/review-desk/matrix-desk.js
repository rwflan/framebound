/* Project-scoped navigation over recorded evidence and local reviewer activity. */
window.MatrixDesk = (() => {
  const R = window.Review, {esc, label, num, picture} = R;
  const projects = R.fixture.projects || [{id:'design-fixture',name:'Character animation'}];
  const state = {view:'interventions',project:'all',returnView:'interventions',event:null,actor:'all',order:'oldest',timelineScroll:0};
  const requestedRevision=new URLSearchParams(location.search).get('revision');
  if(R.records.some(r=>r.id===requestedRevision)){state.view='sequence';R.selectRecord(requestedRevision);}
  let drawSequence, icon;
  const projectId = r => r.project_id || projects[0].id;
  const revisions = () => R.records.filter(r => state.project==='all' || projectId(r)===state.project);
  const recordFor = id => R.records.find(r=>r.id===id);
  const revisionName = r => r.label+' · Revision '+r.id.split('-').at(-1).slice(1);
  const projectName = id => projects.find(p=>p.id===id)?.name || id;
  const dateLabel = timestamp => new Date(timestamp).toLocaleDateString(undefined,{day:'numeric',month:'short',year:'numeric'});
  const timeLabel = timestamp => new Date(timestamp).toLocaleTimeString(undefined,{hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});
  const failing = r => r.evaluation.results.filter(f=>['fail','error','unmeasured'].includes(f.outcome));

  function interventions() {
    const items=[];
    for(const r of revisions()) {
      // A prior comparison baseline is history, unless it still needs a repair.
      const next=R.records.find(n=>n.baseline===r.id&&n.evaluation.technical_status==='pass'&&n.evaluation.coverage_status==='complete');
      const issues=R.saved.issues.filter(i=>i.status!=='resolved'&&(i.clip_revision_id===r.id||i.replacement_revision_id===r.id));
      const missing=failing(r).find(f=>f.outcome==='unmeasured');
      const decision=R.decision(r);
      const isBaseline=R.records.some(n=>n.baseline===r.id)&&!r.baseline;
      if(missing) items.push({id:r.id,record:r,priority:0,title:'Review missing evidence',finding:missing,kind:'evidence',detail:label(missing.constraint_id),issues});
      else if(issues.some(R.canResolve)) items.push({id:r.id,record:r,priority:1,title:'Resolve correction',kind:'correction',detail:issues.length+' open correction'+(issues.length===1?'':'s'),issues});
      else if(r.evaluation.technical_status!=='pass'&&!next) items.push({id:r.id,record:r,priority:1,title:'Review failed checks',kind:'evidence',finding:failing(r)[0],detail:failing(r).length+' failed or unmeasured checks',issues});
      else if(!decision&&r.evaluation.technical_status==='pass'&&!isBaseline) items.push({id:r.id,record:r,priority:2,title:r.baseline?'Review replacement':'Visual review',kind:'review',detail:r.baseline?'Compared with Revision '+r.baseline.split('-').at(-1).slice(1):'Awaiting human decision',issues});
      else if(issues.length&&!next&&!isBaseline) items.push({id:r.id,record:r,priority:1,title:'Review open correction',kind:'correction',detail:issues.length+' open correction'+(issues.length===1?'':'s'),issues});
    }
    return items.sort((a,b)=>a.priority-b.priority||Date.parse(a.record.evaluation.created_at)-Date.parse(b.record.evaluation.created_at));
  }

  function events() {
    const rows=[];
    for(const r of revisions()) {
      const common={record:r,project:projectId(r),actor:'framework'};
      rows.push({...common,id:r.revision.id+':revision',kind:'revision',title:'Revision registered',at:r.revision.created_at});
      rows.push({...common,id:r.evaluation.id,kind:'evaluation',title:'Technical '+r.evaluation.technical_status,at:r.evaluation.created_at,outcome:r.evaluation.technical_status});
      rows.push({...common,id:r.packet.id,kind:'packet',title:'Review requested',at:r.packet.created_at});
    }
    for(const e of R.saved.events) {
      const r=recordFor(e.clip_revision_id);if(!r||!revisions().includes(r))continue;
      rows.push({id:e.id,record:r,project:projectId(r),actor:'human',kind:'decision',title:({approve:'Approved',reject:'Rejected',needs_changes:'Changes requested'})[e.action]||label(e.action),at:e.created_at,data:e});
    }
    for(const issue of R.saved.issues) {
      const r=recordFor(issue.clip_revision_id);if(!r||!revisions().includes(r))continue;
      rows.push({id:issue.id,record:r,project:projectId(r),actor:'human',kind:'issue',title:'Correction requested',at:issue.created_at,data:issue});
    }
    for(const a of R.saved.activity||[]) {
      const r=recordFor(a.clip_revision_id);if(!r||!revisions().includes(r))continue;
      rows.push({id:a.id,record:r,project:projectId(r),actor:'human',kind:'activity',title:({'issue_resolved':'Correction resolved','issue_reopened':'Correction reopened'})[a.action]||label(a.action),at:a.created_at,data:a});
    }
    // Recorded timestamps are authoritative. No synthetic times for checks or snapshots.
    return rows.filter(e=>e.at&&Number.isFinite(Date.parse(e.at))&&(state.actor==='all'||e.actor===state.actor)).sort((a,b)=>{
      const delta=Date.parse(a.at)-Date.parse(b.at)||(a.data?.sequence||0)-(b.data?.sequence||0)||a.id.localeCompare(b.id);
      return state.order==='oldest'?delta:-delta;
    });
  }

  function miniStrip(r, frame=null) {
    const frames=frame===null?[0,Math.min(3,r.frames.length-1),r.frames.length-1]:[Math.max(0,frame-1),frame,Math.min(r.frames.length-1,frame+1)];
    return `<div class="intervention-film" aria-hidden="true">${frames.map(i=>picture(r.frames[i].url,'')).join('')}</div>`;
  }

  function shell() {
    const previous=R.$('.timeline-list');if(previous)state.timelineScroll=previous.scrollTop;
    const all=state.project;state.project='all';const count=interventions();state.project=all;
    R.$('[data-app]').classList.add('project-desk');R.$('[data-app]').classList.toggle('is-sequence',state.view==='sequence');
    R.$('[data-app]').innerHTML=`<aside class="project-rail"><h2>Projects</h2><button class="project-choice ${state.project==='all'?'active':''}" data-project="all"><span>All projects</span><b>${count.length}</b></button>${projects.map(p=>`<button class="project-choice ${p.id===state.project?'active':''}" data-project="${esc(p.id)}"><span><i class="project-symbol" aria-hidden="true"></i>${esc(p.name)}</span><b>${count.filter(i=>projectId(i.record)===p.id).length}</b></button>`).join('')}</aside><div class="desk-body"><nav class="desk-views" aria-label="Review views">${[['interventions','Interventions'],['timeline','Timeline'],['sequences','Sequences']].map(([v,n])=>`<button data-desk-view="${v}" aria-current="${state.view===v||(state.view==='sequence'&&state.returnView===v)?'page':'false'}">${n}${v==='interventions'?`<b>${interventions().length}</b>`:''}</button>`).join('')}</nav><div data-desk-content></div></div>`;
  }

  function renderInterventions() {
    const items=interventions();
    R.$('[data-desk-content]').innerHTML=`<header class="desk-heading"><h1>Interventions</h1><span>${items.length} awaiting review</span></header>${projects.filter(p=>state.project==='all'||p.id===state.project).map(p=>{
      const group=items.filter(i=>projectId(i.record)===p.id);
      return `<section class="project-group" data-project-group="${esc(p.id)}"><header><h2>${esc(p.name)}</h2><span>${group.length}</span></header><div class="intervention-list">${group.map(item=>{
        const r=item.record,frame=item.finding?R.scoped(item.finding):null;
        return `<article class="intervention-row"><button class="intervention-preview" data-open-intervention="${r.id}" aria-label="Review ${esc(revisionName(r))}">${miniStrip(r,frame)}</button><div class="intervention-copy"><span class="intervention-context">${esc(revisionName(r))}</span><h3>${esc(item.title)}</h3><p>${esc(item.detail)}${item.finding?.observed_value!=null?` <b>${R.checkValue(item.finding)} / ${R.bound(item.finding).split('–').at(-1)}</b>`:''}</p></div><span class="intervention-kind ${item.kind}">${({evidence:'Evidence',correction:'Correction',review:'Human review'})[item.kind]}</span><button class="review-intervention" data-open-intervention="${r.id}">Review ${icon('arrow')}</button></article>`;
      }).join('')||'<p class="desk-empty">No interventions awaiting review.</p>'}</div></section>`;
    }).join('')}`;
  }

  function evaluationDetails(event) {
    const r=event.record;
    return `<div class="event-result"><span class="signal ${r.evaluation.technical_status}">${esc(r.evaluation.technical_status)}</span><span>Coverage <b>${esc(r.evaluation.coverage_status)}</b></span><span>${r.evaluation.results.length} checks</span></div><div class="event-checks" aria-label="Recorded checks">${r.evaluation.results.map((check,index)=>`<button class="event-check ${check.outcome}" data-check-index="${index}" data-event-record="${r.id}"><span><strong>${esc(label(check.constraint_id))}</strong><small>${R.scoped(check)===null?esc(check.scope):'Frame '+num(R.scoped(check)+1)}</small></span><span class="check-outcome ${check.outcome}">${esc(label(check.outcome))}</span><span>${R.checkValue(check)}${check.expected_interval?`<small>${R.bound(check)}</small>`:''}</span><p>${esc(check.reason)}</p></button>`).join('')}</div>`;
  }

  function eventDetails(event, all) {
    const r=event.record, index=all.indexOf(event), data=event.data;
    let body='';
    if(event.kind==='evaluation') body=evaluationDetails(event);
    if(event.kind==='revision') body=`<dl class="event-facts"><div><dt>Contract</dt><dd>${esc(r.contract.id)}</dd></div><div><dt>Canvas</dt><dd>96 × 96 px</dd></div><div><dt>Authored timing</dt><dd>${R.total(r)} ticks · ${r.frames.length} frames</dd></div><div><dt>Origin</dt><dd>${esc(r.origin)}</dd></div></dl>`;
    if(event.kind==='packet') body=`<dl class="event-facts"><div><dt>Comparison</dt><dd>${r.baseline?'Revision '+r.baseline.split('-').at(-1).slice(1):'None'}</dd></div><div><dt>Flagged checks</dt><dd>${esc(r.packet.issue_ids.map(label).join(', ')||'None')}</dd></div><div><dt>Unresolved coverage</dt><dd>${esc(r.packet.unresolved_coverage.map(label).join(', ')||'None')}</dd></div></dl><button data-event-inspect="decision">Review decision ${icon('arrow')}</button>`;
    if(event.kind==='issue') body=`<div class="event-issue"><h3>${esc(label(data.category))}</h3><p>${esc(data.note)}</p><dl class="event-facts"><div><dt>Ticks</dt><dd>${data.frame_range.join('–')}</dd></div><div><dt>Region</dt><dd>${data.roi?Object.values(data.roi).join(', ')+' px':'Whole frame'}</dd></div><div><dt>Current status</dt><dd>${esc(data.status)}</dd></div></dl></div><button data-inspect-issue="${data.id}">Inspect correction ${icon('arrow')}</button>`;
    if(event.kind==='decision') body=`<dl class="event-facts"><div><dt>Decision</dt><dd>${esc(label(data.action))}</dd></div><div><dt>Evaluation</dt><dd>${esc(data.expected_evaluation_id)}</dd></div><div><dt>Origin</dt><dd>Local review</dd></div></dl>`;
    if(event.kind==='activity') body=`<dl class="event-facts"><div><dt>Correction</dt><dd>${esc(data.issue_id)}</dd></div>${data.expected_evaluation_id?`<div><dt>Evaluation</dt><dd>${esc(data.expected_evaluation_id)}</dd></div>`:''}</dl>`;
    return `<section class="event-detail" aria-label="Selected event"><div class="event-traversal"><button class="icon-button" data-event-step="-1" ${index===0?'disabled':''} aria-label="Previous event">←</button><span>${index+1} of ${all.length}</span><button class="icon-button" data-event-step="1" ${index===all.length-1?'disabled':''} aria-label="Next event">→</button></div><header><span>${esc(projectName(event.project))}</span><h2>${esc(event.title)}</h2><p>${esc(revisionName(r))}<span>${event.actor==='framework'?'Framework':'Human review'}</span></p><time datetime="${event.at}" title="${event.at}">${dateLabel(event.at)} · ${timeLabel(event.at)}</time></header>${miniStrip(r)}${body}<div class="event-actions"><button class="primary" data-open-sequence="${r.id}">Open sequence ${icon('arrow')}</button><button class="quiet-button" data-event-inspect="evidence">All evidence</button></div><details class="event-identifiers"><summary>Record identifiers</summary><dl><dt>Revision</dt><dd>${esc(r.id)}</dd><dt>Event</dt><dd>${esc(event.id)}</dd>${event.kind==='evaluation'?`<dt>Evidence digest</dt><dd>${esc(r.evaluation.evidence_manifest_sha256)}</dd>`:''}</dl></details></section>`;
  }

  function renderTimeline() {
    const all=events();
    if(!all.some(e=>e.id===state.event))state.event=all[0]?.id||null;
    const selected=all.find(e=>e.id===state.event);
    R.$('[data-desk-content]').innerHTML=`<header class="desk-heading timeline-heading"><h1>Timeline</h1><div><label><span class="sr-only">Activity source</span><select data-activity-source aria-label="Activity source"><option value="all">All activity</option><option value="framework" ${state.actor==='framework'?'selected':''}>Framework</option><option value="human" ${state.actor==='human'?'selected':''}>Human review</option></select></label><label><span class="sr-only">Chronological order</span><select data-time-order aria-label="Chronological order"><option value="oldest" ${state.order==='oldest'?'selected':''}>Oldest first</option><option value="newest" ${state.order==='newest'?'selected':''}>Newest first</option></select></label></div></header><div class="timeline-workspace"><div class="timeline-list" aria-label="Project activity">${projects.filter(p=>state.project==='all'||state.project===p.id).map(p=>{
      const group=all.filter(e=>e.project===p.id);let date='';
      return `<section class="timeline-project" data-project-group="${esc(p.id)}"><h2>${esc(p.name)}<span>${group.length}</span></h2>${group.map(event=>{
        const day=dateLabel(event.at),header=day!==date?`<h3 class="timeline-date">${day}</h3>`:'';date=day;
        return header+`<button class="timeline-event ${event.id===state.event?'selected':''}" data-timeline-event="${esc(event.id)}" aria-pressed="${event.id===state.event}"><span class="timeline-dot ${event.outcome||event.actor}" aria-hidden="true"></span><span><strong>${esc(event.title)}</strong><small>${esc(revisionName(event.record))}</small></span><time datetime="${event.at}" title="${event.at}">${timeLabel(event.at)}</time></button>`;
      }).join('')||'<p class="desk-empty">No recorded activity for this filter.</p>'}</section>`;
    }).join('')}</div>${selected?eventDetails(selected,all):'<section class="event-detail desk-empty">No recorded events.</section>'}</div>`;
    const list=R.$('.timeline-list'),active=R.$('.timeline-event.selected');
    list.scrollTop=state.timelineScroll;
    if(active){const row=active.getBoundingClientRect(),box=list.getBoundingClientRect();if(row.top<box.top)list.scrollTop+=row.top-box.top-8;else if(row.bottom>box.bottom)list.scrollTop+=row.bottom-box.bottom+8;}
  }

  function renderSequences() {
    R.$('[data-desk-content]').innerHTML=`<header class="desk-heading"><h1>Sequences</h1></header>${projects.filter(p=>state.project==='all'||p.id===state.project).map(p=>`<section class="project-group"><header><h2>${esc(p.name)}</h2></header><div class="sequence-library">${revisions().filter(r=>projectId(r)===p.id).map(r=>`<button class="sequence-library-item" data-open-sequence="${r.id}">${miniStrip(r)}<span><strong>${esc(revisionName(r))}</strong><small>${R.status(r)} · Coverage ${esc(r.evaluation.coverage_status)}</small></span>${icon('arrow')}</button>`).join('')}</div></section>`).join('')}`;
  }

  function render(sequence, symbols) {
    drawSequence=sequence;icon=symbols;shell();
    if(state.view==='interventions')renderInterventions();
    if(state.view==='timeline')renderTimeline();
    if(state.view==='sequences')renderSequences();
    if(state.view==='sequence') {
      const r=R.record();
      R.$('[data-desk-content]').innerHTML=`<div class="sequence-navigation"><button class="quiet-button" data-desk-back>← ${state.returnView==='timeline'?'Timeline':state.returnView==='sequences'?'Sequences':'Interventions'}</button><span>${esc(projectName(projectId(r)))}</span></div><div data-sequence-panel></div>`;
      drawSequence();
    }
  }

  function refresh() {R.pause(false);R.emit();}
  function openSequence(id, item=null) {
    state.returnView=state.view==='sequence'?state.returnView:state.view;state.view='sequence';R.selectRecord(id);
    const frame=item?.finding?R.scoped(item.finding):null;
    if(frame!==null&&frame!==undefined){R.state.selectedColumns=[frame];R.selectFrame(frame);}
    window.scrollTo({top:0});
  }
  function inspectEvent(tab) {const event=events().find(e=>e.id===state.event);if(event)R.inspect(tab,event.record.id);}
  document.addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button)return;
    if(button.dataset.deskView){state.view=button.dataset.deskView;refresh();window.scrollTo({top:0});}
    if(button.dataset.project){state.project=button.dataset.project;if(state.view==='sequence')state.view='interventions';state.event=null;refresh();}
    if(button.dataset.openIntervention){const item=interventions().find(i=>i.id===button.dataset.openIntervention);if(item)openSequence(item.record.id,item);}
    if(button.dataset.openSequence)openSequence(button.dataset.openSequence);
    if(button.hasAttribute('data-desk-back')){state.view=state.returnView;refresh();}
    if(button.dataset.timelineEvent){state.event=button.dataset.timelineEvent;refresh();}
    if(button.dataset.eventStep){const all=events(),index=all.findIndex(e=>e.id===state.event),next=all[index+Number(button.dataset.eventStep)];if(next){state.event=next.id;refresh();}}
    if(button.dataset.eventInspect)inspectEvent(button.dataset.eventInspect);
    if(button.dataset.checkIndex!==undefined&&button.dataset.eventRecord){const r=recordFor(button.dataset.eventRecord),check=r.evaluation.results[Number(button.dataset.checkIndex)];R.inspect('evidence',r.id,R.scoped(check));}
  });
  document.addEventListener('change',event=>{
    if(event.target.matches('[data-activity-source]')){state.actor=event.target.value;state.event=null;refresh();}
    if(event.target.matches('[data-time-order]')){state.order=event.target.value;refresh();}
  });
  return {render,isSequence:()=>state.view==='sequence'};
})();
