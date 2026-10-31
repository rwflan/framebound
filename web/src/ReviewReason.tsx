import {Icon,words} from './shared';
export type ReviewContext={version_id:string;kind:string;label:string;title:string;summary:string;next_step:string;technical_status:string;coverage:string;evaluation_id:string|null;requested_reason?:string;intake_reasons?:string[];feedback_baseline?:string;annotation_slots?:number[];prior_issues:{id:string;text:string;slots:number[]}[];findings:{check_id:string;family:string;outcome:string;slots:number[];reason:string;observed:unknown;expected:unknown;source:string}[]};
export function ReviewReason({context,onDetails}:{context:ReviewContext;onDetails:()=>void}){
 return <div className={'review-reason '+context.kind} aria-label="Why this animation is here"><Icon name="inbox"/><div><strong>{context.title}</strong><p>{context.summary}</p></div><button type="button" onClick={onDetails}>Why this take?</button></div>;
}
const measurement=(value:unknown)=>value==null?'Unmeasured':typeof value==='object'?JSON.stringify(value):String(value);
export function ReviewEvidence({context,onFrame}:{context:ReviewContext;onFrame:(slot:number)=>void}){
 return <section className="review-reason-evidence"><h2>Why this take is here</h2><strong>{context.title}</strong><p>{context.summary}</p><p>{context.next_step}</p>{context.requested_reason&&<p><b>Review request:</b> {context.requested_reason}</p>}
  <dl className="review-check-status"><dt>Animation checks</dt><dd>{context.technical_status==='not_run'?'Not run on this take':words(context.technical_status)}</dd><dt>Coverage</dt><dd>{words(context.coverage)}</dd></dl>
  {context.findings.map(f=><article className="review-finding" key={f.check_id}><header><strong>{words(f.family)}</strong><span>{f.outcome==='fail'?'Failed':f.outcome==='error'?'Check error':'Unmeasured'}</span></header><p>{f.reason}</p><div className="review-finding-frames">{f.slots.map(slot=><button type="button" key={slot} onClick={()=>onFrame(slot)}>Frame {slot+1} →</button>)}</div><dl><dt>Observed</dt><dd>{measurement(f.observed)}</dd><dt>Expected</dt><dd>{measurement(f.expected)}</dd></dl><small>{f.check_id} · {words(f.source)}</small></article>)}
  {context.prior_issues.length>0&&<div className="review-requested-fixes"><h3>Requested on the previous take</h3><small>These are earlier reports to verify, not findings measured on this take.</small>{context.prior_issues.map(issue=><article key={issue.id}><p>{issue.text}</p><div className="review-finding-frames">{issue.slots.map(slot=><button type="button" key={slot} onClick={()=>onFrame(slot)}>Frame {slot+1} →</button>)}</div></article>)}</div>}
  {!!context.annotation_slots?.length&&<p>Visual feedback on previous frames {context.annotation_slots.map(i=>i+1).join(', ')}. Open the previous take to see its marks.</p>}
  {!!context.intake_reasons?.length&&<ul>{context.intake_reasons.map(reason=><li key={reason}>{words(reason)}</li>)}</ul>}
 </section>;
}
