import {useEffect,useState} from 'react';
import type {CSSProperties} from 'react';
import {filmPosition} from './playback';
import {Icon} from './shared';
import type {usePresentationClock} from './useClock';
import './transport.css';
export type PresentationClock=ReturnType<typeof usePresentationClock>;
export type PlaybackLane={title:string;urls:(string|undefined)[]};
export function FilmPlayback({lanes,holds,loop,clock,onInspect}:{lanes:PlaybackLane[];holds:number[];loop:boolean;clock:PresentationClock;onInspect:(slot:number)=>void}){
 const count=holds.length,copies=loop?Math.max(3,2*Math.ceil(2048/Math.max(1,count*92))+1):1,middle=Math.floor(copies/2);
 const [reduced,setReduced]=useState(()=>matchMedia('(prefers-reduced-motion: reduce)').matches);
 useEffect(()=>{const media=matchMedia('(prefers-reduced-motion: reduce)'),update=()=>setReduced(media.matches);media.addEventListener('change',update);return()=>media.removeEventListener('change',update);},[]);
 const progress=filmPosition(holds,clock.tickFloat,loop),position=(loop?middle*count:0)+(reduced?Math.floor(progress):progress)+.5;
 return <div className={'film-projector'+(clock.playing?' is-running':'')} aria-label="Animation playback with moving film strip" tabIndex={0}>
  <div className="projector-screen">{lanes.map(lane=><figure key={lane.title}><figcaption>{lane.title}</figcaption><div className="projector-aperture">{lane.urls[clock.slot]?<img draggable={false} src={lane.urls[clock.slot]} alt={`${lane.title} playback`}/>:<span className="missing-reference">{lane.title} unavailable</span>}</div></figure>)}</div>
  <div className="projector-reels" aria-label="Moving film strip"><div className="projector-gate" aria-hidden="true"/>{lanes.map(lane=><div className="projector-reel" key={lane.title}><span className="projector-lane-label">{lane.title}</span><div className="projector-moving-stock reel-stock" style={{'--transport-position':position} as CSSProperties}>{Array.from({length:copies},(_,copy)=>lane.urls.map((url,slot)=><button key={`${copy}:${slot}`} className={'projector-cell'+(slot===clock.slot?' is-playhead':'')} aria-label={`Inspect ${lane.title.toLowerCase()} playback frame ${slot+1}`} aria-hidden={copy!==middle&&loop?true:undefined} tabIndex={copy!==middle&&loop?-1:0} onPointerDown={e=>{if(e.button===0){e.preventDefault();onInspect(slot);}}} onClick={e=>{if(e.detail===0)onInspect(slot);}}><span>{url?<img src={url} alt="" draggable={false}/>:<span>—</span>}</span><small>{String(slot+1).padStart(2,'0')}</small></button>))}</div></div>)}</div>
 </div>;
}
export function PlaybackControls({clock,holds,tps,loop,onToggle,onInspect,onScrub,disabled=false,filmMode,onFilm}:{clock:PresentationClock;holds:number[];tps:number;loop:boolean;onToggle:()=>void;onInspect:(slot:number)=>void;onScrub:(tick:number)=>void;disabled?:boolean;filmMode?:boolean;onFilm?:()=>void}){
 const total=clock.total,current=clock.slot,duration=total/tps;
 return <footer className="film-transport" aria-label="Film controls">
  <div className="transport-timeline"><div className="transport-segments" aria-hidden="true">{holds.map((hold,i)=><span key={i} style={{flex:hold}} className={i===current?'is-current':''}>{holds.length<=24?i+1:''}</span>)}</div><input className="transport-scrubber" aria-label="Animation timeline" aria-valuetext={`Frame ${current+1} of ${holds.length}, tick ${clock.tick} of ${Math.max(0,total-1)}`} type="range" min={0} max={Math.max(0,total-1)} step={1} value={clock.tick} disabled={disabled} onPointerDown={()=>clock.setPlaying(false)} onChange={e=>onScrub(Number(e.target.value))}/></div>
  <div className="transport-actions"><div className="control-transport"><button aria-label="Previous frame" title="Previous frame · ←" disabled={disabled||current<=0} onClick={()=>onInspect(Math.max(0,current-1))}><Icon name="left"/></button><button className="transport-play" aria-label={clock.playing?'Pause':'Play'} title="Play / pause · Space" disabled={disabled} onClick={onToggle}><Icon name={clock.playing?'pause':'play'}/></button><button aria-label="Next frame" title="Next frame · →" disabled={disabled||current>=holds.length-1} onClick={()=>onInspect(Math.min(holds.length-1,current+1))}><Icon name="right"/></button></div><output className="transport-position">Frame {disabled?0:current+1} / {holds.length}<small>{(clock.tick/tps).toFixed(2)} / {Number.isFinite(duration)?duration.toFixed(2):'0.00'} s</small></output><label className="transport-speed">Speed<select aria-label="Playback speed" value={clock.speed} onChange={e=>clock.setSpeed(Number(e.target.value))}>{[.1,.25,.5,.75,1,1.5,2].map(speed=><option key={speed} value={speed}>{speed===1?'1× · Original':speed+'×'}</option>)}</select></label>{onFilm&&<button className="transport-film" aria-pressed={filmMode} onClick={onFilm} title="Pause and inspect the film"><Icon name="film"/>Inspect film</button>}<span className="transport-timing">{loop?'Loop':'One shot'} · {tps} ticks/s</span></div>
 </footer>;
}
