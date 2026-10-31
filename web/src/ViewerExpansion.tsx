import {useEffect,useRef,useState} from 'react';
import {Icon} from './shared';

export function useViewerExpansion(onResize:()=>void){
 const [expanded,setExpanded]=useState(false),resize=useRef(onResize);resize.current=onResize;
 const toggle=()=>setExpanded(value=>!value);
 useEffect(()=>{
  // Let the existing camera's ResizeObserver preserve its selected frame and zoom.
  resize.current();
 },[expanded]);
 useEffect(()=>{
  if(!expanded)return;
  const escape=(e:KeyboardEvent)=>{
   if(e.key!=='Escape'||e.defaultPrevented||(e.target as HTMLElement).closest('dialog,[role="dialog"]'))return;
   e.preventDefault();setExpanded(false);
  };
  window.addEventListener('keydown',escape,true);return()=>window.removeEventListener('keydown',escape,true);
 },[expanded]);
 function showFeedback(){setExpanded(false);requestAnimationFrame(()=>document.querySelector<HTMLTextAreaElement>('.packet-workspace textarea')?.focus({preventScroll:true}));}
 return {expanded,toggle,showFeedback};
}
export function ViewerExpansion({expanded,onToggle,onFeedback}:{expanded:boolean;onToggle:()=>void;onFeedback?:()=>void}){
 return <div className="viewer-window-actions">{expanded&&onFeedback&&<button className="viewer-return-feedback" onClick={onFeedback}>Feedback</button>}<button className="window-control" aria-label={expanded?'Restore workspace':'Expand film workspace'} title={expanded?'Restore workspace · Esc':'Expand film workspace'} aria-pressed={expanded} onClick={onToggle}>{expanded?<><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M3 8h5V3m8 0v5h5M3 16h5v5m8 0v-5h5"/></svg><span>Restore</span><kbd>Esc</kbd></>:<Icon name="expand"/>}</button></div>;
}
