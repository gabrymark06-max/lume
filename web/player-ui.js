(() => {
  'use strict';
  const frame = document.querySelector('#video-frame');
  const video = document.querySelector('#video');
  const dialog = document.querySelector('#player-dialog');
  const bar = frame?.querySelector('.video-controls');
  if (!frame || !video || !dialog || !bar) return;
  let timer, editingSelect = false, dragging = false;
  const tv = () => document.documentElement.classList.contains('tv-mode');
  const active = () => dialog.open;
  const hidden = () => frame.classList.contains('controls-hidden');

  function schedule() {
    clearTimeout(timer);
    if (!active() || video.paused || video.ended || editingSelect || dragging) return;
    timer = setTimeout(() => {
      if (!active() || video.paused || video.ended || editingSelect || dragging) return;
      // Evita di lasciare un pulsante invisibile selezionato dal telecomando.
      if (bar.contains(document.activeElement)) video.focus({preventScroll:true});
      bar.setAttribute('aria-hidden','true');
      bar.inert = true;
      frame.classList.add('controls-hidden');
    },3000);
  }
  function show() {
    frame.classList.remove('controls-hidden');
    bar.removeAttribute('aria-hidden');
    bar.inert = false;
    schedule();
  }
  for (const name of ['play','playing','pause','ended','loadedmetadata','seeking','seeked']) video.addEventListener(name,show);
  for (const name of ['pointermove','pointerdown','click','touchstart']) frame.addEventListener(name,show,{passive:true});
  frame.addEventListener('focusin',show);
  bar.addEventListener('pointerdown',event => {
    if (event.target.closest('select')) editingSelect = true;
    if (event.target.matches('input[type="range"]')) dragging = true;
    schedule();
  });
  document.addEventListener('pointerup',() => {dragging=false;schedule();});
  document.addEventListener('pointercancel',() => {dragging=false;schedule();});
  bar.addEventListener('change',() => {editingSelect=false;show();});
  bar.addEventListener('focusout',() => {editingSelect=false;schedule();});
  document.addEventListener('keydown',event => {
    if (!active() || document.querySelector('#action-dialog[open]')) return;
    const wasHidden = hidden();
    if (event.target.matches('select') && ['Enter',' '].includes(event.key)) editingSelect=true;
    if (event.key === 'Escape') editingSelect=false;
    show();
    if (tv() && wasHidden && ['Enter','ArrowDown','ArrowUp'].includes(event.key)) {
      document.querySelector('#video-play')?.focus({preventScroll:true});
      event.preventDefault();event.stopImmediatePropagation();
    }
  },true);
  dialog.addEventListener('close',() => {clearTimeout(timer);editingSelect=false;dragging=false;frame.classList.remove('controls-hidden');bar.inert=false;bar.removeAttribute('aria-hidden');});
  document.addEventListener('fullscreenchange',show);
})();
