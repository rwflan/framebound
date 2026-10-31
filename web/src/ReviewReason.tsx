import {words} from './shared';
export type ReviewContext={version_id:string;kind:string;label:string;title:string;summary:string;next_step:string;technical_status:string;coverage:string;evaluation_id:string|null;requested_reason?:string;intake_reasons?:string[];feedback_baseline?:string;annotation_slots?:number[];prior_issues:{id:string;text:string;slots:number[]}[];findings:{check_id:string;family:string;outcome:string;slots:number[];reason:string;observed:unknown;expected:unknown;source:string}[]};
export function reviewTag(context?:ReviewContext,activity?:string){
 if(context?.kind==='approved')return {label:'Approved',tone:'approved'};
 const work:Record<string,string>={queued:'Queued',generating:'Generating',unknown:'Outcome unknown',failed:'Generation failed'};
 if(activity&&work[activity])return {label:work[activity],tone:activity==='unknown'||activity==='failed'?'blocked':'working'};
 if(context?.kind==='findings'){
  const finding=context.findings.find(f=>f.outcome==='error')||context.findings.find(f=>f.outcome==='fail')||context.findings[0];
  return {label:finding?`${words(finding.family).replace(/^./,c=>c.toUpperCase())} · ${finding.outcome==='fail'?'Failed':finding.outcome==='error'?'Error':'Unmeasured'}`:'Check failed',tone:finding?.outcome==='unmeasured'?'incomplete':'blocked'};
 }
 const states:Record<string,{label:string;tone:string}>={unassessed:{label:'Unassessed',tone:'neutral'},first_review:{label:'Unreviewed',tone:'review'},correction_review:{label:'Verify fixes',tone:'verify'},coverage:{label:'Incomplete',tone:'incomplete'},excluded:{label:'Intake failed',tone:'blocked'}};
 return states[context?.kind||'']||{label:'Review needed',tone:'review'};
}
export function ReviewTag({context,activity}:{context?:ReviewContext;activity?:string}){
 const tag=reviewTag(context,activity);
 return <span className={'review-tag '+tag.tone} title={activity?tag.label:context?.summary}>{tag.label}</span>;
}
const measurement=(value:unknown)=>value==null?'Unmeasured':typeof value==='object'?JSON.stringify(value):String(value);
export function ReviewEvidence({context,onFrame}:{context:ReviewContext;onFrame:(slot:number)=>void}){
 return <details className="review-reason-evidence" open={context.findings.length>0||context.prior_issues.length>0}><summary>Assessment</summary><strong>{context.title}</strong><p>{context.summary}</p><p>{context.next_step}</p>{context.requested_reason&&<p><b>Review request:</b> {context.requested_reason}</p>}
  <dl className="review-check-status"><dt>Animation checks</dt><dd>{context.technical_status==='not_run'?'Not run on this take':words(context.technical_status)}</dd><dt>Coverage</dt><dd>{words(context.coverage)}</dd></dl>
  {context.findings.map(f=><article className="review-finding" key={f.check_id}><header><strong>{words(f.family)}</strong><span>{f.outcome==='fail'?'Failed':f.outcome==='error'?'Check error':'Unmeasured'}</span></header><p>{f.reason}</p><div className="review-finding-frames">{f.slots.map(slot=><button type="button" key={slot} onClick={()=>onFrame(slot)}>Frame {slot+1} →</button>)}</div><dl><dt>Observed</dt><dd>{measurement(f.observed)}</dd><dt>Expected</dt><dd>{measurement(f.expected)}</dd></dl><small>{f.check_id} · {words(f.source)}</small></article>)}
  {context.prior_issues.length>0&&<div className="review-requested-fixes"><h3>Requested on the previous take</h3><small>These are earlier reports to verify, not findings measured on this take.</small>{context.prior_issues.map(issue=><article key={issue.id}><p>{issue.text}</p><div className="review-finding-frames">{issue.slots.map(slot=><button type="button" key={slot} onClick={()=>onFrame(slot)}>Frame {slot+1} →</button>)}</div></article>)}</div>}
  {!!context.annotation_slots?.length&&<p>Visual feedback on previous frames {context.annotation_slots.map(i=>i+1).join(', ')}. Open the previous take to see its marks.</p>}
  {!!context.intake_reasons?.length&&<ul>{context.intake_reasons.map(reason=><li key={reason}>{words(reason)}</li>)}</ul>}
 </details>;
}
