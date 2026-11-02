import {useEffect,useRef} from 'react';
import type {ReactNode} from 'react';
import {Icon} from './shared';
import './utilities.css';
export type Utility='export'|'status'|'reviewed-guides'|'training'|'settings';
const utilities:{id:Utility;title:string;description:string;icon:'folder'|'history'|'frame'|'film'|'settings'}[]=[
 {id:'training',title:'Train a model',description:'Build a model with your own evidence',icon:'film'},
 {id:'settings',title:'Settings',description:'Meta and Modal connections',icon:'settings'},
 {id:'export',title:'Export',description:'Preview and save a local snapshot',icon:'folder'},
 {id:'status',title:'Status',description:'Current work and framework evidence',icon:'history'},
 {id:'reviewed-guides',title:'Reference approvals',description:'Legacy guide authority',icon:'frame'},
];
export function UtilitiesMenu({active,extras=[]}:{active?:string;extras?:{href:string;title:string}[]}){
 const root=useRef<HTMLDetailsElement>(null),trigger=useRef<HTMLElement>(null);
 useEffect(()=>{
  const outside=(e:PointerEvent)=>{if(root.current?.open&&!root.current.contains(e.target as Node))root.current.open=false;};
  const escape=(e:KeyboardEvent)=>{if(e.key==='Escape'&&root.current?.open){e.preventDefault();e.stopImmediatePropagation();root.current.open=false;trigger.current?.focus();}};
  const changed=()=>{if(root.current)root.current.open=false;};
  document.addEventListener('pointerdown',outside);window.addEventListener('keydown',escape,true);window.addEventListener('hashchange',changed);
  return()=>{document.removeEventListener('pointerdown',outside);window.removeEventListener('keydown',escape,true);window.removeEventListener('hashchange',changed);};
 },[]);
 function keyboard(e:React.KeyboardEvent<HTMLDetailsElement>){
  if(!['ArrowDown','ArrowUp','Home','End'].includes(e.key))return;
  e.preventDefault();if(root.current)root.current.open=true;
  const links=Array.from(root.current?.querySelectorAll<HTMLAnchorElement>('nav a')||[]),index=links.indexOf(document.activeElement as HTMLAnchorElement);
  if(!links.length)return;
  const next=e.key==='Home'?0:e.key==='End'?links.length-1:e.key==='ArrowDown'?(index+1)%links.length:index<0?links.length-1:(index-1+links.length)%links.length;
  links[next]?.focus();
 }
 return <details ref={root} className="workspace-switcher utility-menu" onKeyDown={keyboard}><summary ref={trigger} aria-label="More workspaces" title="Workspace tools">•••</summary><nav aria-label="Workspace tools"><small className="utility-menu-label">Workspace tools</small>{utilities.filter(item=>item.id!=='reviewed-guides').map(item=><a key={item.id} href={'#/'+item.id} aria-current={active===item.id?'page':undefined} onClick={()=>{if(root.current)root.current.open=false;}}><Icon name={item.icon}/><span><strong>{item.title}</strong><small>{item.description}</small></span>{active===item.id&&<Icon name="check"/>}</a>)}<div className="utility-menu-extra"><small className="utility-menu-label">Legacy tools</small><a href="#/reviewed-guides" aria-current={active==='reviewed-guides'?'page':undefined} onClick={()=>{if(root.current)root.current.open=false;}}>Reference approvals</a>{extras.map(item=><a key={item.href} href={item.href} onClick={()=>{if(root.current)root.current.open=false;}}>{item.title}</a>)}</div></nav></details>;
}
export function UtilityWindow({view,children,back='#/'}:{view:Utility|'corrections'|'issues';children:ReactNode;back?:string}){
 const item=utilities.find(item=>item.id===view)||{title:view==='corrections'?'Correction tasks':'Issue records',icon:'inbox' as const};
 const showTabs=view==='settings'||view==='export'||view==='status';
 return <div className={'utility-workspace utility-workspace--'+view}><section className="utility-window"><header className="pane-title"><span className="file-icon"><Icon name={item.icon}/></span><h1>{item.title}</h1><span className="title-grip"/><a className="utility-back" href={back}><Icon name="left"/>Back to review</a></header>{showTabs&&<nav className="utility-tabs" aria-label="Workspace utilities">{utilities.filter(item=>item.id==='settings'||item.id==='export'||item.id==='status').map(item=><a key={item.id} href={'#/'+item.id} aria-current={item.id===view?'page':undefined}><Icon name={item.icon}/>{item.title}</a>)}</nav>}<div className="utility-content">{children}</div></section></div>;
}
