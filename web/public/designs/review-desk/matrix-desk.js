/* Project-scoped navigation over recorded evidence and local reviewer activity. */
window.MatrixDesk = (() => {
  const R = window.Review, {esc, label, num, picture} = R;
  const projects = R.fixture.projects || [{id:'design-fixture',name:'Character animation'}];
  const state = {view:'interventions',project:'all',returnView:'interventions',event:null,actor:'all',order:'oldest'};
  const requestedRevision=new URLSearchParams(location.search).get('revision');
  if(R.records.some(r=>r.id===requestedRevision)){state.view='sequence';R.selectRecord(requestedRevision);}
  let icon;
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
    return `<section class="event-detail" aria-label="Selected event"><div class="event-traversal"><button class="icon-button" data-event-step="-1" ${index===0?'disabled':''} aria-label="Previous event">←</button><span>${index+1} of ${all.length}</span><button class="icon-button" data-event-step="1" ${index===all.length-1?'disabled':''} aria-label="Next event">→</button></div><header><span>${esc(projectName(event.project))}</span><h2>${esc(event.title)}</h2><p>${esc(revisionName(r))}<span>${event.actor==='framework'?'Framework':'Human review'}</span></p><time datetime="${event.at}" title="${event.at}">${dateLabel(event.at)} · ${timeLabel(event.at)}</time></header>${body}<div class="event-actions"><button class="primary" data-open-sequence="${r.id}">Open sequence ${icon('arrow')}</button><button class="quiet-button" data-event-inspect="evidence">All evidence</button></div><details class="event-identifiers"><summary>Record identifiers</summary><dl><dt>Revision</dt><dd>${esc(r.id)}</dd><dt>Event</dt><dd>${esc(event.id)}</dd>${event.kind==='evaluation'?`<dt>Evidence digest</dt><dd>${esc(r.evaluation.evidence_manifest_sha256)}</dd>`:''}</dl></details></section>`;
  }

  function render(symbols) {
    icon=symbols;
    window.FilmWorkspace.render({
      view:state.view,project:state.project,projects,records:revisions(),
      interventions:interventions(),events:events(),selectedEvent:state.event,
      actor:state.actor,order:state.order,returnView:state.returnView,
      detail:eventDetails,revisionName,projectName,
    },{
      setEvent(id){state.event=id;},
      openIntervention(id){const item=interventions().find(i=>i.id===id);if(item)openSequence(id,item);},
      openSequence,
    },symbols);
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
    if(event.target.matches('[data-film-project]')){state.project=event.target.value;state.event=null;if(state.view==='sequence')state.view='interventions';refresh();}
    if(event.target.matches('[data-time-order]')){state.order=event.target.value;refresh();}
  });
  return {render,isSequence:()=>state.view==='sequence'};
})();
