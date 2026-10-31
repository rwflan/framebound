import {usePresentationClock} from './useClock';
import {AnnotationSurface} from './AnnotationTools';
import './annotations.css';
export type Stroke={slot:number;tool:'pen'|'highlighter';color:string;width:number;points:[number,number][]};
// The inspector is a read-only mirror. Drawing tools live with the main film.
export function AnnotationPlayer({urls,holds,tps,loop,width,height,value=[],controller,compact=false}:{urls:string[];holds:number[];tps:number;loop:boolean;width:number;height:number;value?:Stroke[];controller?:ReturnType<typeof usePresentationClock>;compact?:boolean}){
 const own=usePresentationClock({holds,tps,loop,resetKey:urls.join(),autoPlay:false}),c=controller||own;
 return <div className={'annotation-player'+(compact?' compact-annotations':'')}><div className="studio-stage" style={{aspectRatio:`${width}/${height}`}}><img src={urls[c.slot]} alt={`Frame ${c.slot+1}`}/><AnnotationSurface slot={c.slot} width={width} height={height} value={value}/></div><small>{holds[c.slot]} ticks · {tps} ticks/s · {loop?'Loop':'One shot'}</small></div>;
}
