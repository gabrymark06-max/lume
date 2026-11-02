(() => {
  'use strict';
  const tv = new URLSearchParams(location.search).get('tv') === '1' || /LumeTV/.test(navigator.userAgent);
  if (tv) document.documentElement.classList.add('tv-mode');
  const visible = el => !el.disabled && !el.closest('[hidden]') && el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden';
  function controls() {
    const dialogs = [...document.querySelectorAll('dialog[open]')];
    const root = dialogs.at(-1) || document;
    return [...root.querySelectorAll('button,a[href],input,select,textarea,[tabindex="0"]')].filter(visible);
  }
  window.lumeBack = () => {
    const dialogs = [...document.querySelectorAll('dialog[open]')];
    const active = dialogs.at(-1);
    if (active) {
      if (active.classList.contains('cloud-access')) return true;
      active.querySelector('[data-close]')?.click();
      return true;
    }
    if (document.querySelector('[data-nav="home"][aria-current="page"]')) return false;
    document.querySelector('[data-nav="home"]')?.click(); return true;
  };
  if (tv) document.addEventListener('keydown',event => {
    if (['Escape','GoBack','BrowserBack'].includes(event.key)) {
      if (window.lumeBack()) {event.preventDefault();event.stopImmediatePropagation();} return;
    }
    if (event.key === 'MediaPlayPause') {document.querySelector('#video-play')?.click();event.preventDefault();return;}
    const current = document.activeElement;
    if (current?.matches('input,textarea,select') && !current.matches('input[type="range"]')) return;
    if (event.key === 'Enter' && current?.tagName === 'VIDEO') {document.querySelector('#video-play')?.click();event.preventDefault();return;}
    if (!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) return;
    if (current?.tagName === 'VIDEO' && event.key === 'ArrowDown') {
      document.querySelector('#video-play')?.focus();event.preventDefault();event.stopImmediatePropagation();return;
    }
    // Le frecce sul video conservano seek/volume; nei controlli muovono il focus.
    if (current?.tagName === 'VIDEO' || current?.matches('input[type="range"]')) return;
    const candidates = controls();
    let target;
    if (!candidates.includes(current)) target = candidates[0];
    else {
      const r = current.getBoundingClientRect(), x = r.x+r.width/2, y = r.y+r.height/2;
      const horizontal = ['ArrowLeft','ArrowRight'].includes(event.key), sign = ['ArrowRight','ArrowDown'].includes(event.key)?1:-1;
      let best = Infinity;
      for (const element of candidates) {
        if (element === current) continue;
        const b = element.getBoundingClientRect(), dx = b.x+b.width/2-x, dy = b.y+b.height/2-y;
        const forward = (horizontal?dx:dy)*sign, side = Math.abs(horizontal?dy:dx);
        if (forward <= 2) continue;
        const score = forward + side*3 + (side>forward?1000:0);
        if (score < best) { best=score;target=element; }
      }
    }
    if (target) {event.preventDefault();event.stopImmediatePropagation();target.focus({preventScroll:true});target.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});}
  },true);
  if ('serviceWorker' in navigator && window.isSecureContext) navigator.serviceWorker.register('/sw.js').catch(()=>{});
})();
