// UI prototypes: original SVG pose fixtures; all decisions are local to this page.
const pages = ['index.html', '02-motion.html', '03-compare.html', '04-clips.html', '05-sheet.html'];
const pageIndex = Math.max(0, pages.indexOf(location.pathname.split('/').pop()));
const icons = {
  play: 'M9 5l11 7-11 7z', pause: 'M8 5v14M16 5v14',
  left: 'M15 5l-7 7 7 7', right: 'M9 5l7 7-7 7',
  prev: 'M6 5v14M18 5l-9 7 9 7z', next: 'M18 5v14M6 5l9 7-9 7z',
  check: 'M5 12l5 5L20 6', cross: 'M6 6l12 12M18 6L6 18',
  layers: 'M12 3L2 8l10 5 10-5zM2 12l10 5 10-5M2 16l10 5 10-5',
  bounds: 'M8 3H3v5M16 3h5v5M21 16v5h-5M8 21H3v-5M12 7v10M7 12h10',
  pin: 'M8 3h8l-1 7 4 5H5l4-5zM12 15v7',
  expand: 'M9 3H3v6M15 3h6v6M21 15v6h-6M9 21H3v-6',
  reset: 'M3 10a9 9 0 1 1 2 9M3 3v7h7',
  swap: 'M3 7h17l-4-4M21 17H4l4 4',
};
function icon(name) { return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${icons[name] || icons.play}" fill="${name === 'play' ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg>`; }
document.querySelectorAll('[data-icon]').forEach(el => el.innerHTML = icon(el.dataset.icon));
document.querySelectorAll('[data-nav]').forEach(el => el.innerHTML = `<a class="nav-arrow" href="${pages[(pageIndex + 4) % 5]}" aria-label="Previous design">${icon('left')}</a>${pages.map((p, i) => `<a href="${p}" aria-label="Design ${i + 1}" ${i === pageIndex ? 'aria-current="page"' : ''}>0${i + 1}</a>`).join('')}<a class="nav-arrow" href="${pages[(pageIndex + 1) % 5]}" aria-label="Next design">${icon('right')}</a>`);

// Hand-authored poses, varied by clip. Coordinates are illustration space.
const run = [
  [-65, 52, 0, 22, -24, 1], [-40, 25, 0, 30, -12, 12],
  [-6, -15, 4, 44, 6, 0], [44, -58, 20, 24, 26, -15],
  [65, -48, 0, 28, 25, 1], [38, -25, 0, 40, 14, 12],
  [0, 18, 12, 38, -6, 0], [-44, 60, 24, 15, -26, -15],
];
function pose(frame, clip) {
  if (clip === 'Idle') return [0, 15, 0, 0, 2, [0,2,4,2,0,-2,-4,-2][frame]];
  if (clip === 'Jump') return [[-12,12,0,0,-10,26],[-30,25,12,10,-30,5],[-48,45,35,38,-36,-40],[-32,30,48,48,-20,-65],[-10,20,45,40,4,-55],[24,-15,32,25,18,-30],[35,-24,0,0,12,18],[8,10,0,0,0,6]][frame];
  if (clip === 'Attack') return [[-20,24,0,0,-20,0],[-28,25,0,0,-48,4],[-38,28,0,0,-65,8],[40,-25,0,0,70,-4],[48,-20,0,0,82,0],[38,-12,0,0,55,5],[10,10,0,0,16,4],[-10,20,0,0,-12,0]][frame];
  return run[frame];
}
function art(frame = 3, clip = 'Run', previous = false) {
  const [a, b, liftA, liftB, arm, bob] = pose(frame, clip);
  const left = 192 + a, right = 201 + b;
  return `<svg class="pip" viewBox="0 ${clip === 'Jump' ? '-65' : '0'} 400 ${clip === 'Jump' ? '485' : '420'}" aria-hidden="true">
  <ellipse class="shadow" cx="203" cy="384" rx="90" ry="9" fill="currentColor" opacity=".12"/>
  <g transform="translate(${previous ? -8 : 0} ${bob})" stroke="#123b39" stroke-width="2" stroke-linejoin="round">
    <path d="M187 248 Q${190+b} 291 ${right} ${365-liftB} L${right+23} ${370-liftB} Q${right+30} ${375-liftB} ${right+22} ${380-liftB} L${right-10} ${380-liftB} Q${right-14} ${335-liftB} ${180+b/2} 305 L173 259Z" fill="#1d4846"/>
    <path d="M205 247 Q${203+a/2} 284 ${left} ${362-liftA} L${left+27} ${369-liftA} Q${left+32} ${375-liftA} ${left+23} ${380-liftA} L${left-11} ${380-liftA} Q${left-10} ${329-liftA} ${179+a/2} 297 L179 258Z" fill="#35605b"/>
    <path d="M${left-11} ${359-liftA}l14 1 2 7 24 4 3 8 -42 1z" fill="#173e3d"/><path d="M${right-10} ${360-liftB}l12 1 2 6 24 6 -2 7 -36 0z" fill="#123532"/>
    <path d="M175 149 Q113 ${139-arm/3} 48 ${178-arm/2} L76 ${145-arm/2} 52 ${133-arm/2} Q119 ${124-arm/3} 181 133Z" fill="#e65d48" stroke="#b83d33"/>
    <path d="M168 139 Q114 ${117-arm/3} 68 ${131-arm/2}" fill="none" stroke="#ff9774"/>
    <path d="M183 141 Q163 160 153 205 L130 265 Q181 290 251 267 Q230 227 229 194 L224 151Z" fill="#478b7d"/>
    <path d="M180 153 Q175 213 143 264 Q164 274 187 275 L205 159Z" fill="#2f6b63" stroke="none"/>
    <path d="M218 165 Q${244+arm/2} 191 ${233+arm} 217" fill="none" stroke="#245b54" stroke-width="24" stroke-linecap="round"/>
    <path d="M${232+arm} 218l11 -6" stroke="#efbb89" stroke-width="14" stroke-linecap="round"/>
    <path d="M169 141 Q132 102 156 64 Q181 28 213 48 Q246 65 243 106 L227 147 Q198 168 169 141Z" fill="#34756a"/>
    <path d="M211 63 Q239 74 239 102 L250 115 238 118 234 139 Q218 153 200 135 L186 105 190 79Z" fill="#efc397" stroke="#284d43"/>
    <path d="M175 138 Q150 117 157 88 Q168 51 201 49 Q226 51 237 75 Q213 65 198 80 Q185 103 201 140 L192 153Z" fill="#184c48"/>
    <path d="M167 88 Q171 65 192 58" fill="none" stroke="#5b9b83" stroke-width="4" stroke-linecap="round"/>
    <path d="M230 102h5" stroke="#153b37" stroke-width="3" stroke-linecap="round"/>
    <path d="M165 143 Q196 156 234 139 L234 154 Q203 173 166 157Z" fill="#f0785c" stroke="#b94635"/>
    <path d="M209 166L168 248" stroke="#563c2e" stroke-width="9"/>
    <path d="M136 223 Q157 215 179 228 L172 267 Q148 270 129 257Z" fill="#b77c47" stroke="#674c33"/>
    <path d="M136 223l43 5 -8 19 -39 -10Z" fill="#d19b5d" stroke="#8c633d"/>
    <rect x="149" y="237" width="13" height="11" rx="2" fill="#e9c477" stroke="#8b6934"/>
    <circle cx="213" cy="177" r="10" fill="#e7c675" stroke="#9b7c40"/><path d="M214 170l3 8 -5 6 -2-8z" fill="#486351" stroke="none"/>
    <path d="M220 199l8 30M196 233l-7 21" fill="none" stroke="#68a68d" stroke-width="3" stroke-linecap="round"/>
  </g></svg>`;
}

let frame = 3, clip = 'Run', playing = false, timer, speed = 1;
const holds = [4,4,4,4,4,4,4,4], marks = new Map(), decisions = new Map();
const stateKey = () => `${clip}:${frame}`;
const frameLabel = () => `${String(frame+1).padStart(2,'0')} / 08`;
document.querySelectorAll('[data-art]').forEach(el => el.innerHTML = art(Number(el.dataset.art), el.dataset.clipArt || 'Run', el.hasAttribute('data-previous')));
document.querySelectorAll('[data-frames]').forEach(el => {
  el.innerHTML = holds.map((_, i) => `<button class="frame" data-frame="${i}" aria-label="Frame ${i+1}"><span>${String(i+1).padStart(2,'0')}</span>${art(i)}<i class="frame-pin"></i></button>`).join('');
});
document.querySelectorAll('[data-panorama]').forEach(el => {
  el.innerHTML = holds.map((_, i) => `<button class="pose" data-frame="${i}" aria-label="Frame ${i+1}" style="--i:${i}">${art(i)}</button>`).join('');
});
document.querySelectorAll('[data-sheet]').forEach(el => {
  el.innerHTML = holds.map((hold, i) => `<div class="sheet-row" data-row="${i}"><button class="sheet-frame" data-frame="${i}" aria-label="Frame ${i+1}"><span>${String(i+1).padStart(2,'0')}</span>${art(i)}</button><label><input type="number" min="1" max="12" value="${hold}" data-hold="${i}" aria-label="Frame ${i+1} hold in ticks"><span>t</span></label><button class="sheet-mark icon-button" data-pin-frame="${i}" aria-label="Mark frame ${i+1}" aria-pressed="false">${icon('pin')}</button></div>`).join('');
});
function update() {
  document.querySelectorAll('[data-live]').forEach(el => el.innerHTML = art(frame, clip, el.hasAttribute('data-previous')));
  document.querySelectorAll('[data-count]').forEach(el => el.textContent = frameLabel());
  document.querySelectorAll('[data-current]').forEach(el => el.textContent = String(frame+1).padStart(2,'0'));
  document.querySelectorAll('[data-total]').forEach(el => el.textContent = `${holds.reduce((a,b)=>a+b,0)}t`);
  document.querySelectorAll('[data-frame]').forEach(el => { const n=Number(el.dataset.frame); el.setAttribute('aria-pressed', String(n===frame)); el.classList.toggle('selected',n===frame); el.classList.toggle('marked', marks.has(`${clip}:${n}`)); });
  document.querySelectorAll('[data-row]').forEach(el => el.classList.toggle('selected',Number(el.dataset.row)===frame));
  document.querySelectorAll('[data-play]').forEach(el => { el.innerHTML=icon(playing?'pause':'play'); el.setAttribute('aria-label',playing?'Pause':'Play'); el.title=playing?'Pause':'Play'; });
  document.querySelectorAll('[data-pin]').forEach(el => el.setAttribute('aria-pressed',String(marks.has(stateKey()))));
  document.querySelectorAll('[data-pin-frame]').forEach(el=>el.setAttribute('aria-pressed',String(marks.has(`${clip}:${el.dataset.pinFrame}`))));
  document.querySelectorAll('[data-decision]').forEach(el => el.setAttribute('aria-pressed',String(decisions.get(clip)===el.dataset.decision)));
  document.querySelectorAll('[data-status]').forEach(el => el.textContent = decisions.get(clip)==='approve'?'Approved':decisions.get(clip)==='reject'?'Changes requested':'');
  document.querySelectorAll('[data-clip-label]').forEach(el=>el.textContent=clip);
  document.querySelectorAll('[data-scrub]').forEach(el=>el.value=frame);
  document.body.style.setProperty('--playhead',`${(frame+.5)/8*100}%`);
  const field = document.querySelector('[data-panorama]');
  if (field && innerWidth <= 640) {
    const selected = field.querySelector('.selected');
    field.scrollLeft = document.body.classList.contains('onion-off') ? 0 : selected.offsetLeft + selected.offsetWidth/2 - field.clientWidth/2;
  }
}
function pause() { playing=false;clearTimeout(timer);update(); }
function tick() { if(!playing)return;timer=setTimeout(()=>{frame=(frame+1)%8;update();tick();},holds[frame]*1000/24/speed); }
function play() { if(playing)return pause();playing=true;update();tick(); }
function select(n) { pause();frame=(n+8)%8;update(); }
function pin(n=frame) { const key=`${clip}:${n}`;marks.has(key)?marks.delete(key):marks.set(key,true);update(); }
document.querySelectorAll('[data-frame]').forEach(el=>el.addEventListener('click',()=>select(Number(el.dataset.frame))));
document.querySelectorAll('[data-play]').forEach(el=>el.addEventListener('click',play));
document.querySelectorAll('[data-step]').forEach(el=>el.addEventListener('click',()=>select(frame+Number(el.dataset.step))));
document.querySelectorAll('[data-scrub]').forEach(el=>el.addEventListener('input',()=>select(Number(el.value))));
document.querySelectorAll('[data-pin]').forEach(el=>el.addEventListener('click',()=>pin()));
document.querySelectorAll('[data-pin-frame]').forEach(el=>el.addEventListener('click',()=>pin(Number(el.dataset.pinFrame))));
document.querySelectorAll('[data-toggle]').forEach(el=>el.addEventListener('click',()=>{const on=document.body.classList.toggle(el.dataset.toggle);el.setAttribute('aria-pressed',String(on));update();}));
document.querySelectorAll('[data-speed]').forEach(el=>el.addEventListener('click',()=>{speed=speed===1?.5:1;el.textContent=`${speed}×`;if(playing){pause();play();}}));
document.querySelectorAll('[data-decision]').forEach(el=>el.addEventListener('click',()=>{decisions.set(clip,el.dataset.decision);update();}));
document.querySelectorAll('[data-hold]').forEach(el=>el.addEventListener('change',()=>{const n=Number(el.value);holds[Number(el.dataset.hold)]=Number.isFinite(n)?Math.min(12,Math.max(1,Math.round(n))):4;el.value=holds[Number(el.dataset.hold)];update();}));
document.querySelectorAll('[data-open-clip]').forEach(el=>el.addEventListener('click',()=>{clip=el.dataset.openClip;select(0);document.querySelector('[data-dialog]').showModal();}));
document.querySelectorAll('[data-close]').forEach(el=>el.addEventListener('click',()=>{pause();document.querySelector('[data-dialog]').close();}));
document.querySelector('[data-dialog]')?.addEventListener('close',pause);
document.querySelectorAll('[data-swap]').forEach(el=>el.addEventListener('click',()=>{document.querySelector('.pair').classList.toggle('swapped');}));
document.addEventListener('visibilitychange',()=>{if(document.hidden)pause();});
document.addEventListener('keydown',e=>{
  if(e.target.matches('input,textarea,select')||e.metaKey||e.ctrlKey||e.altKey)return;
  if(/^[1-5]$/.test(e.key)){location.href=pages[Number(e.key)-1];return;}
  if(e.code==='Space'&&!e.target.closest('button,a')){e.preventDefault();play();}
  if(e.key==='ArrowRight'){e.preventDefault();select(frame+1);}
  if(e.key==='ArrowLeft'){e.preventDefault();select(frame-1);}
});
update();
