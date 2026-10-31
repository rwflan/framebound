import {useEffect,useRef,useState} from 'react';
import type {Stroke} from './AnnotationPlayer';
import './annotations.css';
export type AnnotationTool='view'|'pen'|'highlighter';
type Options={value:Stroke[];onChange?: (value:Stroke[])=>void;slot:number;onSlot:(slot:number)=>void;pause:()=>void;onDraw?:()=>void;resetKey:string;fit?:()=>void;transport?:{count:number;slot?:number;playing:boolean;toggle:()=>void;fit:()=>void}};
export function useAnnotations(options:Options){
 const [chosen,setChosen]=useState<AnnotationTool>('view'),[penColor,setPenColor]=useState('#d65b29'),[markerColor,setMarkerColor]=useState('#e4b52a'),[penWidth,setPenWidth]=useState(3),[markerWidth,setMarkerWidth]=useState(14);
 const live=useRef(options);live.current=options;
 useEffect(()=>setChosen('view'),[options.resetKey]);
 const tool=options.onChange?chosen:'view',color=tool==='highlighter'?markerColor:penColor,width=tool==='highlighter'?markerWidth:penWidth;
 function select(next:AnnotationTool){if(next!=='view'&&!options.onChange)return;options.pause();setChosen(next);if(next!=='view')options.onDraw?.();}
 function undo(){if(!options.onChange||!options.value.length)return;options.pause();options.onSlot(options.value[options.value.length-1].slot);options.onChange(options.value.slice(0,-1));}
 function clear(){options.onChange?.(options.value.filter(s=>s.slot!==options.slot));}
 // Local viewer shortcuts never consume text editing, browser commands or modal keys.
 const actions=useRef({select,undo});actions.current={select,undo};
 useEffect(()=>{
  function keyboard(e:KeyboardEvent){
   const target=e.target as HTMLElement;
   if(e.defaultPrevented||target.closest('input,textarea,select,[contenteditable="true"],dialog,[role="dialog"]'))return;
   const o=live.current,key=e.key.toLowerCase();
   if((e.ctrlKey||e.metaKey)&&key==='z'&&!e.shiftKey&&target.closest('.film-window')){if(o.onChange&&o.value.length){e.preventDefault();actions.current.undo();}return;}
   if(e.ctrlKey||e.metaKey||e.altKey)return;
   const tools:Record<string,AnnotationTool>={v:'view',p:'pen',h:'highlighter',escape:'view'};
   if(tools[key]){e.preventDefault();actions.current.select(tools[key]);return;}
   if(key==='f'&&(o.fit||o.transport)){e.preventDefault();(o.fit||o.transport!.fit)();return;}
   if(!o.transport||(target.closest('button')&&!target.closest('.reel-camera,.film-projector')))return;
   if(e.code==='Space'){e.preventDefault();o.transport.toggle();}
   if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){
    e.preventDefault();o.pause();o.onSlot(e.key==='Home'?0:e.key==='End'?o.transport.count-1:Math.max(0,Math.min(o.transport.count-1,(o.transport.playing?(o.transport.slot??o.slot):o.slot)+(e.key==='ArrowRight'?1:-1))));
   }
  }
  window.addEventListener('keydown',keyboard);return()=>window.removeEventListener('keydown',keyboard);
 },[]);
 return {tool,color,width,select,undo,clear,enabled:Boolean(options.onChange),count:options.value.filter(s=>s.slot===options.slot).length,total:options.value.length,slot:options.slot,
  setColor:(color:string)=>tool==='highlighter'?setMarkerColor(color):setPenColor(color),setWidth:(width:number)=>tool==='highlighter'?setMarkerWidth(width):setPenWidth(width)};
}
export type AnnotationControls=ReturnType<typeof useAnnotations>;
function ToolIcon({name}:{name:AnnotationTool|'undo'|'clear'}){
 return <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">{name==='view'?<><path d="M8 12V7a2 2 0 0 1 4 0v4-7a2 2 0 0 1 4 0v7-5a2 2 0 0 1 4 0v9c0 4-2 7-6 7h-2c-2 0-3-1-4-3l-4-6a2 2 0 0 1 3-2l1 1Z"/></>:name==='pen'?<><path d="m4 20 2-7L17 2l5 5-11 11-7 2Z"/><path d="m14 5 5 5M6 13l5 5M4 20l3-3"/></>:name==='highlighter'?<><path d="m8 16 8-12 6 4-8 12-6-4Z"/><path d="m9 17-3 4H2l5-6M14 7l6 4"/><path d="M3 23h16" strokeWidth="3"/></>:name==='undo'?<><path d="m8 5-5 5 5 5M3 10h10a7 7 0 0 1 0 14" transform="translate(0 -3)"/></>:<><path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 11v6M14 11v6"/></>}</svg>;
}
export function AnnotationTools({controls:c}:{controls:AnnotationControls}){
 return <div className="annotation-toolbar" role="toolbar" aria-label="Frame annotation tools">
  <div className="annotation-modes" role="group" aria-label="Drawing mode">
   <button type="button" className="annotation-pan" aria-label="Pan (V)" title="Pan the film · V or Esc" aria-pressed={c.tool==='view'} onClick={()=>c.select('view')}><ToolIcon name="view"/><span>Pan</span><kbd>V</kbd></button>
   <button type="button" className="annotation-pen" aria-label="Pen (P)" title="Draw an issue on a frame · P" disabled={!c.enabled} aria-pressed={c.tool==='pen'} onClick={()=>c.select('pen')}><ToolIcon name="pen"/><span>Pen</span><kbd>P</kbd></button>
   <button type="button" className="annotation-marker" aria-label="Highlighter (H)" title="Highlight an area · H" disabled={!c.enabled} aria-pressed={c.tool==='highlighter'} onClick={()=>c.select('highlighter')}><ToolIcon name="highlighter"/><span>Highlight</span><kbd>H</kbd></button>
  </div>
  <div className="annotation-style" role="group" aria-label="Stroke appearance"><label className="annotation-swatch" title="Drawing colour" style={{'--mark-color':c.color} as React.CSSProperties}><span className="sr-only">Mark color</span><input type="color" aria-label="Mark color" value={c.color} disabled={!c.enabled||c.tool==='view'} onChange={e=>c.setColor(e.target.value)}/></label><select aria-label="Stroke width" value={c.width} disabled={!c.enabled||c.tool==='view'} onChange={e=>c.setWidth(Number(e.target.value))}>{[1,3,6,14,24].map(w=><option key={w} value={w}>{w} px</option>)}</select></div>
  <div className="annotation-history" role="group" aria-label="Manage marks"><button type="button" className="annotation-undo" aria-label="Undo last mark" title="Undo last mark · ⌘/Ctrl Z" disabled={!c.enabled||!c.total} onClick={c.undo}><ToolIcon name="undo"/><span>Undo</span></button><button type="button" className="annotation-clear" aria-label="Clear marks on this frame" title="Clear marks on the selected frame only" disabled={!c.enabled||!c.count} onClick={c.clear}><ToolIcon name="clear"/><span>Clear frame</span></button></div>
  <span className="annotation-hint" role="status">{!c.enabled?'Read-only':c.tool==='view'?'Drag to pan':c.tool==='pen'?'Draw on a frame':'Highlight on a frame'}{c.total>0&&<b>{c.total} mark{c.total===1?'':'s'}</b>}</span>
 </div>;
}
export function AnnotationSurface({slot,width,height,value,controls,onChange,onStart}:{slot:number;width:number;height:number;value:Stroke[];controls?:AnnotationControls;onChange?:(value:Stroke[])=>void;onStart?:()=>void}){
 const [live,setLive]=useState<Stroke|null>(null),drawing=useRef<Stroke|null>(null),pointer=useRef<number|null>(null);
 const enabled=Boolean(onChange&&controls?.enabled&&controls.tool!=='view');
 useEffect(()=>{drawing.current=null;pointer.current=null;setLive(null);},[slot,enabled]);
 function point(e:React.PointerEvent<SVGSVGElement>){const matrix=e.currentTarget.getScreenCTM();if(!matrix)return null;const p=new DOMPoint(e.clientX,e.clientY).matrixTransform(matrix.inverse());return [p.x,p.y] as [number,number];}
 return <svg className="frame-annotations" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="xMidYMid meet" aria-label={`Frame ${slot+1} annotation surface`} data-annotation-active={enabled} data-annotation-drawing={Boolean(live)} style={{pointerEvents:enabled?'auto':'none',touchAction:enabled?'none':'auto'}}
  onPointerDown={e=>{if(!enabled||e.button!==0||drawing.current)return;const p=point(e);if(!p||p[0]<0||p[0]>=width||p[1]<0||p[1]>=height)return;e.preventDefault();e.stopPropagation();e.currentTarget.setPointerCapture(e.pointerId);e.currentTarget.closest<HTMLElement>('.reel-camera')?.focus({preventScroll:true});onStart?.();pointer.current=e.pointerId;drawing.current={slot,tool:controls!.tool as 'pen'|'highlighter',color:controls!.color,width:controls!.width,points:[p]};setLive(drawing.current);}}
  onPointerMove={e=>{if(!drawing.current||pointer.current!==e.pointerId)return;e.stopPropagation();const p=point(e);if(!p)return;const bounded:[number,number]=[Math.max(0,Math.min(width-.01,p[0])),Math.max(0,Math.min(height-.01,p[1]))];drawing.current={...drawing.current,points:[...drawing.current.points,bounded].slice(0,4000)};setLive(drawing.current);}}
  onPointerUp={e=>{if(pointer.current!==e.pointerId)return;e.stopPropagation();if(drawing.current)onChange?.([...value,drawing.current]);drawing.current=null;pointer.current=null;setLive(null);}}
  onPointerCancel={()=>{drawing.current=null;pointer.current=null;setLive(null);}} onLostPointerCapture={()=>{drawing.current=null;pointer.current=null;setLive(null);}} onClick={e=>{if(enabled){e.preventDefault();e.stopPropagation();}}}>
  {[...value,...(live?[live]:[])].filter(s=>s.slot===slot).map((s,i)=>s.points.length===1?<circle key={i} cx={s.points[0][0]} cy={s.points[0][1]} r={s.width/2} fill={s.color} opacity={s.tool==='highlighter'?.35:1}/>:<polyline key={i} points={s.points.map(p=>p.join(',')).join(' ')} fill="none" stroke={s.color} strokeWidth={s.width} opacity={s.tool==='highlighter'?.35:1} strokeLinecap="round" strokeLinejoin="round"/>)}
 </svg>;
}
