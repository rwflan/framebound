/* Local design studies. Illustrative frames and review data; no project API writes. */
const pages = ['index.html', '01-afterhours.html', '02-paperwork.html', '03-split.html', '04-orbit.html'];
const names = ['All directions', 'Afterhours', 'Paperwork', 'Split', 'Orbit'];
const current = Math.max(0, pages.indexOf(location.pathname.split('/').pop()));
const mark = '<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M3 3h11v5H8v6H3zm15 0h11v11h-5V8h-6zM3 18h5v6h6v5H3zm21 0h5v11H18v-5h6z" fill="currentColor"/></svg>';

document.querySelector('[data-design-nav]').innerHTML = `<a class="study-home" href="index.html">${mark}<span>FRAMEBOUND <b>/ DESIGN STUDIES</b></span></a><nav aria-label="Design candidates">${pages.slice(1).map((p, i) => `<a href="${p}" ${current === i + 1 ? 'aria-current="page"' : ''}><span>0${i + 1}</span> ${names[i + 1]}</a>`).join('')}</nav><a class="study-next" href="${pages[(current + 1) % pages.length]}">Next <span>↗</span></a>`;

// Hand-drawn vector stand-in for Pip: hood, left satchel, trailing scarf, brass compass.
// The eight poses are a visual UI fixture, not evaluated project output.
function courier(frame = 0, options = '') {
  const poses = [[-48, 38, -24, 28, 0], [-30, 18, -15, 14, 7], [0, -28, 12, -14, 0], [35, -47, 28, -24, -8], [49, -35, 22, -28, 0], [28, -15, 12, -14, 7], [-5, 28, -12, 14, 0], [-35, 48, -28, 24, -8]];
  const [a, b, arm, scarf, bob] = poses[frame % 8];
  const ghost = options.includes('ghost');
  return `<svg class="courier ${options}" viewBox="0 0 280 290" aria-hidden="true"><ellipse cx="141" cy="267" rx="70" ry="7" fill="currentColor" opacity=".10"/><g transform="translate(0 ${bob})" ${ghost ? 'opacity=".32"' : ''}>
    <path d="M134 179 Q${136 + b} 214 ${139 + b} 248 l25 8 -2 10 -40 -2 Q${112 + b} 220 125 181" fill="#182c36"/>
    <path d="M144 177 Q${149 + a} 215 ${148 + a} 251 l27 6 -1 10 -43 -2 Q${130 + a} 222 128 184" fill="#284650"/>
    <path d="M127 99 Q82 ${78 - scarf / 2} 39 ${111 - scarf} L64 ${82 - scarf} Q87 85 136 85" fill="#f15c3f"/>
    <path d="M85 ${103 - scarf / 3} L43 ${118 - scarf} 59 ${100 - scarf}" fill="#b72d28"/>
    <path d="M125 102 L155 106 Q165 146 187 180 Q145 207 97 185 L110 139Z" fill="#ee5b3b"/>
    <path d="M125 105 Q115 143 99 183 L127 188 143 134" fill="#c83e29"/>
    <path d="M152 112 Q${177 + arm} 132 ${171 + arm} 156" fill="none" stroke="#a92e27" stroke-width="17" stroke-linecap="round"/>
    <path d="M${171 + arm} 156 l11 -3" stroke="#f3bc87" stroke-width="13" stroke-linecap="round"/>
    <path d="M116 98 Q96 60 117 37 Q133 22 153 38 Q174 57 162 96 L146 113Z" fill="#d9442e"/>
    <path d="M139 46 Q163 49 163 69 L171 78 162 82 160 96 140 101 126 83 128 58Z" fill="#ffc997"/>
    <path d="M114 76 Q108 47 135 38 Q155 37 164 57 L141 54 128 79 136 99 119 102Z" fill="#852e2b"/>
    <path d="M157 68h4" stroke="#27343c" stroke-width="3" stroke-linecap="round"/>
    <path d="M128 108 L113 172" stroke="#743c2b" stroke-width="7"/>
    <path d="M94 156 Q106 150 125 158 L123 187 93 183Z" fill="#8e5437"/>
    <path d="M94 156l31 2 -3 13 -28 -3Z" fill="#b77945"/>
    <rect x="105" y="165" width="10" height="9" rx="1" fill="#f6ca63"/><circle cx="145" cy="119" r="8" fill="#f8d173"/><path d="M145 113l3 6 -3 6 -3 -6Z" fill="#9e652b"/>
    <path d="M119 99 Q140 108 162 97 L163 107 Q143 120 118 110Z" fill="#ff8153"/>
  </g></svg>`;
}
document.querySelectorAll('[data-art]').forEach(el => el.innerHTML = courier(Number(el.dataset.art), el.dataset.artClass || ''));

let frame = 3, playing = false, timer, overlay = false;
let activeClip = 'Run', speed = 1;
const phases = ['Contact', 'Compression', 'Passing', 'Flight', 'Contact', 'Compression', 'Passing', 'Flight'];
function update() {
  document.querySelectorAll('[data-live-art]').forEach(el => el.innerHTML = courier(frame));
  document.querySelectorAll('[data-frame-number]').forEach(el => el.textContent = String(frame + 1).padStart(2, '0'));
  document.querySelectorAll('[data-phase]').forEach(el => el.textContent = phases[frame]);
  document.querySelectorAll('[data-frame]').forEach(el => { el.classList.toggle('selected', Number(el.dataset.frame) === frame); el.setAttribute('aria-pressed', String(Number(el.dataset.frame) === frame)); });
  document.querySelectorAll('[data-play]').forEach(el => { el.innerHTML = playing ? 'Ⅱ <span>Pause</span>' : '▶ <span>Play</span>'; el.setAttribute('aria-label', playing ? 'Pause animation' : 'Play animation'); });
  document.querySelectorAll('[data-scrub]').forEach(el => el.value = frame);
  document.querySelectorAll('[data-orbit-marker]').forEach(el => el.style.transform = `rotate(${frame * 45}deg)`);
  document.querySelectorAll('[data-clip-name]').forEach(el => el.textContent = activeClip);
}
function pause() { playing = false; clearInterval(timer); update(); }
function play() { if (playing) return pause(); playing = true; timer = setInterval(() => { frame = (frame + 1) % 8; update(); }, 140 / speed); update(); }
function selectFrame(n) { pause(); frame = (n + 8) % 8; update(); }
function announce(message) { const el = document.querySelector('[data-toast]'); if (!el) return; el.textContent = message; el.classList.add('visible'); clearTimeout(announce.timeout); announce.timeout = setTimeout(() => el.classList.remove('visible'), 3000); }
document.querySelectorAll('[data-strip]').forEach(strip => { strip.innerHTML = Array.from({length: 8}, (_, i) => `<button class="frame" data-frame="${i}" aria-label="Frame ${i + 1}, ${phases[i]}"><span class="frame-no">${String(i + 1).padStart(2, '0')}</span>${courier(i)}<span class="frame-phase">${phases[i]}</span><span class="frame-hold">4t</span></button>`).join(''); });
document.querySelectorAll('[data-frame]').forEach(el => el.addEventListener('click', () => selectFrame(Number(el.dataset.frame))));
document.querySelectorAll('[data-play]').forEach(el => el.addEventListener('click', play));
document.querySelectorAll('[data-step]').forEach(el => el.addEventListener('click', () => selectFrame(frame + Number(el.dataset.step))));
document.querySelectorAll('[data-scrub]').forEach(el => el.addEventListener('input', () => selectFrame(Number(el.value))));
document.querySelectorAll('[data-overlay]').forEach(el => el.addEventListener('click', () => { overlay = !overlay; document.body.classList.toggle('show-overlay', overlay); document.querySelectorAll('[data-overlay]').forEach(button => button.setAttribute('aria-pressed', String(overlay))); }));
document.querySelectorAll('[data-speed]').forEach(el => el.addEventListener('click', () => { speed = speed === 1 ? .5 : 1; el.textContent = `${speed}×`; if (playing) { pause(); play(); } }));
document.querySelectorAll('[data-decision]').forEach(el => el.addEventListener('click', () => { const decision = el.dataset.decision; document.querySelectorAll('[data-decision]').forEach(button => button.setAttribute('aria-pressed', String(button === el))); document.querySelectorAll('[data-review-state]').forEach(label => label.textContent = decision === 'approve' ? 'Approved' : 'Changes requested'); announce(decision === 'approve' ? `${activeClip} · approved in this study` : `${activeClip} · marked for correction in this study`); }));
document.querySelectorAll('[data-mark]').forEach(el => el.addEventListener('click', () => { document.querySelectorAll('[data-marked]').forEach(label => label.textContent = `Frame ${String(frame + 1).padStart(2, '0')} · marked`); document.querySelector(`[data-frame="${frame}"]`)?.classList.add('marked'); announce(`Frame ${String(frame + 1).padStart(2, '0')} marked for review`); }));
document.querySelectorAll('[data-clip]').forEach(el => el.addEventListener('click', () => { activeClip = el.dataset.clip; document.querySelectorAll('[data-clip]').forEach(button => { button.classList.toggle('active', button === el); button.setAttribute('aria-pressed', String(button === el)); }); document.querySelectorAll('[data-review-state]').forEach(label => label.textContent = 'Awaiting review'); document.querySelectorAll('[data-decision]').forEach(button => button.setAttribute('aria-pressed', 'false')); selectFrame(0); announce(`${activeClip} selected · illustrative poses`); }));
document.querySelectorAll('[data-compare]').forEach(el => el.addEventListener('input', () => { document.querySelector('.compare-after').style.clipPath = `inset(0 0 0 ${el.value}%)`; document.querySelector('.compare-divider').style.left = `${el.value}%`; }));
document.addEventListener('keydown', e => { if (e.target.matches('input,textarea,select') || e.altKey || e.ctrlKey || e.metaKey) return; if (e.code === 'Space' && current && !e.target.closest('button,a')) { e.preventDefault(); play(); } if (e.key === 'ArrowRight' && current) { e.preventDefault(); selectFrame(frame + 1); } if (e.key === 'ArrowLeft' && current) { e.preventDefault(); selectFrame(frame - 1); } if (/^[1-4]$/.test(e.key)) location.href = pages[Number(e.key)]; if (e.key === 'Escape') location.href = 'index.html'; });
update();
