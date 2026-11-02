(() => {
  'use strict';
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const escapeHTML = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const icon = name => `<svg aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const imageURL = url => url ? `/api/image?${new URLSearchParams({url})}` : '';
  const LIST_URL = 'https://www.giardiniblog.it/canali-veezie/';
  const mediaPayload = media => Object.fromEntries(['id','title','url','poster','backdrop','year','kind','channel_id','channel_name','series_url','episode','imdb','imdb_id'].filter(key => media?.[key] !== undefined).map(key => [key,media[key]]));
  let state = {channels:[], favorites:[], progress:{}};
  let view = 'home', query = '', channel = '', items = [], nextPages = {}, catalogRequest = 0;
  let detail = null, detailRequest = 0, sourceRequest = 0, currentPlayback = null, hls = null;
  let hlsLoader = null, toastTimer = null, progressTimer = null, refreshBusy = false;
  let startupRefreshAttempted = false;
  let settings = {show_url:false,trailer_autoplay:false,poster_size:'medium',default_player:'integrated',buffer_minutes:1,subtitle_language:'it',autoplay_next:false};
  let homeData = null, heroIndex = 0, heroTimer = null, heroHls = null;
  let discoverKind = 'movie', discoverPage = 1, discoverNext = null, discoverItems = [], discoverFiltersVisible = false;
  let collectionKind = 'movie', watchlists = [], historyItems = [], activeWatchlist = 'favorites', selectionMode = false, selected = new Set();
  let libraryKind = 'local', libraryData = {items:[],folders:[]}, downloadsTimer = null;
  let profiles = [], activeProfile = '';
  let integrations = [];
  let heroTrailerRequest = 0, subtitlePreferenceApplied = false;
  let calendarView = 'schedule', calendarItems = [], calendarShows = [], calendarTimers = [];
  let galleryIndex = 0;
  let playerHosts = [];

  async function api(path, data, method) {
    if (window.LumeCloud && (path === '/api/mpv' || path === '/api/library/pick')) throw new Error('Questa funzione richiede la versione PC di Lume.');
    if (window.LumeCloud) return window.LumeCloud.request(path,data,method);
    const response = await fetch(path, {
      method: method || (data === undefined ? 'GET' : 'POST'),
      headers: data === undefined ? {} : {'Content-Type':'application/json'},
      body: data === undefined ? undefined : JSON.stringify(data),
      credentials:'same-origin'
    });
    let result;
    try { result = await response.json(); }
    catch { throw new Error('Il server locale non ha restituito una risposta valida.'); }
    if (!response.ok) throw new Error(result.error || `Richiesta non riuscita (${response.status}).`);
    return result;
  }
  function applyState(result) {
    const data = result?.state || result;
    if (!data || !Array.isArray(data.channels)) return;
    state = {...state, ...data};
    state.favorites = Array.isArray(state.favorites) ? state.favorites : [];
    state.progress = state.progress || {};
    renderChannelOptions();
    renderChannels();
  }
  async function reloadState() { applyState(await api('/api/state')); }
  async function refreshStaleList() {
    if (startupRefreshAttempted || !state.channels.length || !state.list_url) return;
    startupRefreshAttempted = true;
    const value = state.last_refresh;
    const numeric = Number(value);
    const refreshedAt = numeric > 0 ? (numeric < 1e12 ? numeric * 1000 : numeric) : Date.parse(value || '');
    if (Number.isFinite(refreshedAt) && Date.now() - refreshedAt < 6 * 60 * 60 * 1000) return;
    refreshBusy = true;
    setBusy($('#refresh-channels'),true,'Aggiorno i canali…');
    showMessage($('#global-message'),'Aggiorno la lista dei canali prima di caricare i cataloghi…');
    try {
      applyState(await api('/api/refresh',{}));
      await reloadState();
      $('#global-message').hidden = true;
    } catch (error) {
      showMessage($('#global-message'),`La lista non si è aggiornata: ${error.message} Uso i canali già salvati.`,true);
    } finally { refreshBusy = false; setBusy($('#refresh-channels'),false); }
  }
  function toast(text, error = false) {
    clearTimeout(toastTimer);
    const toastParent = $('#action-dialog')?.open ? $('#action-dialog') : $('#player-dialog')?.open ? $('#player-dialog') : document.body;
    if ($('#toast').parentElement !== toastParent) toastParent.append($('#toast'));
    $('#toast').textContent = text;
    $('#toast').classList.toggle('error', error);
    $('#toast').hidden = false;
    toastTimer = setTimeout(() => { $('#toast').hidden = true; }, error ? 6500 : 3500);
  }
  function showMessage(element, text, error = false) {
    element.textContent = text;
    element.classList.toggle('error', error);
    element.classList.toggle('success', !error);
    element.hidden = !text;
  }
  function setBusy(element, busy, label) {
    if (!element.dataset.label) element.dataset.label = element.innerHTML;
    element.disabled = busy;
    element.innerHTML = busy ? `<span class="spinner" style="width:15px;height:15px"></span>${escapeHTML(label || 'Caricamento…')}` : element.dataset.label;
  }
  function isFavorite(media) { return state.favorites.some(item => item.url === media.url); }
  function mediaKind(media) {
    return ({movie:'Film',film:'Film',tv:'Serie TV',series:'Serie TV',serie:'Serie TV',episode:'Episodio'})[String(media.kind || '').toLowerCase()] || '';
  }
  function friendlyDate(value) {
    if (!value) return '';
    const date = new Date(typeof value === 'number' && value < 1e12 ? value * 1000 : value);
    return Number.isNaN(date.getTime()) ? '' : new Intl.DateTimeFormat('it-IT',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}).format(date);
  }
  function renderChannelOptions() {
    const select = $('#channel-select');
    const previous = channel;
    select.innerHTML = '<option value="">Tutti i canali</option>' + state.channels.map(c => `<option value="${escapeHTML(c.id)}">${escapeHTML(c.name || c.url)}</option>`).join('');
    channel = state.channels.some(c => String(c.id) === previous) ? previous : '';
    select.value = channel;
  }
  function emptyState(type, message) {
    const variants = {
      initial:{icon:'channels', title:'La tua videoteca inizia dai canali', text:'Importa la lista che usi oppure aggiungi un indirizzo. Qui troverai i titoli dei tuoi canali, pronti da cercare.', action:'Aggiungi i tuoi canali', id:'channels'},
      favorites:{icon:'star', title:'I tuoi preferiti, tutti qui', text:'Apri un titolo e scegli “Aggiungi ai preferiti” per ritrovarlo in questa pagina.'},
      search:{icon:'search', title:'Che cosa vuoi vedere?', text:'Scrivi un titolo nella ricerca in alto. Lume cercherà nei canali che hai aggiunto.'},
      noresults:{icon:'search', title:'Nessun titolo trovato', text:message || 'Prova un titolo diverso o cerca senza selezionare un singolo canale.'},
      failed:{icon:'info', title:'Il catalogo non è disponibile', text:message || 'Controlla lo stato dei canali: l’indirizzo potrebbe essere cambiato o il sito potrebbe non rispondere.', action:'Controlla i canali',id:'channels'}
    };
    const content = variants[type] || variants.noresults;
    $('#catalog-empty').innerHTML = `<div class="empty-icon">${icon(content.icon)}</div><h2>${escapeHTML(content.title)}</h2><p>${escapeHTML(content.text)}</p>${content.action ? `<button class="button" data-nav="${content.id}">${escapeHTML(content.action)}</button>` : ''}`;
    $('#catalog-empty').hidden = false;
  }
  function renderErrors(errors = []) {
    const container = $('#catalog-errors');
    container.hidden = !errors.length;
    container.innerHTML = errors.length ? `<details><summary>${errors.length === 1 ? 'Un canale non ha restituito risultati' : `${errors.length} canali non hanno restituito risultati`}</summary><ul>${errors.map(e => `<li><strong>${escapeHTML(e.name || 'Canale')}</strong>: ${escapeHTML(e.error || 'Non disponibile')}</li>`).join('')}</ul></details>` : '';
  }
  function renderGrid() {
    $('#media-grid').innerHTML = items.map((media, index) => {
      const progress = state.progress[media.url];
      const percent = progress?.duration > 0 ? Math.min(100, Math.max(0, progress.position / progress.duration * 100)) : 0;
      return `<button class="media-card" data-media="${index}" aria-label="Apri ${escapeHTML(media.title || 'Titolo')}" title="${escapeHTML(media.title || '')}">
        <span class="poster-wrap"><span class="poster-fallback">${icon('play')}</span>${media.poster ? `<img src="${escapeHTML(imageURL(media.poster))}" loading="lazy" decoding="async" alt="" referrerpolicy="no-referrer">` : ''}<span class="poster-overlay"><span class="card-play">${icon('play')}</span></span>${isFavorite(media) ? `<span class="saved-mark">${icon('star')}</span>` : ''}${percent ? `<span class="progress-track"><span class="progress-value" style="width:${percent}%"></span></span>` : ''}</span>
        <span class="card-title">${escapeHTML(media.title || 'Senza titolo')}</span><span class="card-meta">${media.year ? `<span class="card-year">${escapeHTML(media.year)}</span>` : ''}<span class="channel-name">${escapeHTML(media.channel_name || mediaKind(media))}</span></span>
      </button>`;
    }).join('');
    $('#media-grid').querySelectorAll('img').forEach(img => img.addEventListener('error', () => { img.hidden = true; }, {once:true}));
    $('#result-count').textContent = items.length ? `${items.length} ${items.length === 1 ? 'titolo' : 'titoli'}${view === 'search' ? ' trovati' : ''}` : '';
    $('#load-more').hidden = !['home','catalog'].includes(view) || !Object.keys(nextPages).length;
  }
  function renderHero() {
    const hero = $('#hero'), heroes = homeData?.hero || [];
    if (view !== 'home' || !heroes.length) { hero.hidden = true; return; }
    heroIndex = heroIndex % heroes.length;
    const media = heroes[heroIndex];
    let index = items.findIndex(m => m.url === media.url);
    if (index < 0) { index = items.length; items.push(media); }
    const rating = ratingValue(media.rating);
    hero.hidden = false;
    hero.innerHTML = `${media.backdrop || media.poster ? `<img class="hero-image" src="${escapeHTML(imageURL(media.backdrop || media.poster))}" alt="">` : ''}<div class="hero-copy"><h2>${escapeHTML(media.title || '')}</h2><div class="hero-meta">${media.year ? `<span>${escapeHTML(media.year)}</span>` : ''}${rating ? `<span class="rating">★${escapeHTML(rating)}</span>` : ''}</div><p class="hero-description">${escapeHTML(media.description || '')}</p><div class="hero-actions"><button class="button" data-media="${index}">${icon('play')}Riproduci</button><button class="button secondary" data-media="${index}">${icon('info')}Più info</button></div></div><div class="hero-dots" aria-label="Titoli in evidenza">${heroes.map((_,i) => `<button data-hero="${i}" aria-label="Titolo in evidenza ${i+1}" ${i === heroIndex ? 'aria-current="true"' : ''}></button>`).join('')}</div>`;
    insertTitleImage(hero,media);
    hideBrokenImages(hero);
    startHeroTrailer(media);
  }
  async function navigate(next) {
    view = next;
    catalogRequest++;
    document.body.dataset.route = next;
    clearInterval(heroTimer); heroTimer = null;
    clearInterval(downloadsTimer); downloadsTimer = null;
    stopHeroTrailer();
    const panels = {home:'home',search:'catalog',catalog:'catalog',channels:'channels',discover:'discover',favorites:'collection',history:'collection',settings:'settings',library:'library',calendar:'calendar'};
    $$('[data-view-panel]').forEach(panel => { panel.hidden = panel.id !== `${panels[next] || 'home'}-view`; });
    $$('.rail-link').forEach(button => {
      if (button.dataset.nav === next || next === 'history' && button.dataset.nav === 'favorites' || next === 'catalog' && button.dataset.nav === 'channels') button.setAttribute('aria-current','page');
      else button.removeAttribute('aria-current');
    });
    window.scrollTo({top:0});
    if (next === 'home') { query = ''; $('#search-input').value = ''; await loadHome(); return; }
    if (next === 'discover') { await loadDiscover(); return; }
    if (next === 'favorites' || next === 'history') { selectionMode = false; selected.clear(); await loadCollection(); return; }
    if (next === 'settings') { await loadSettingsView(); return; }
    if (next === 'library') { await loadLibrary(); downloadsTimer = setInterval(() => loadDownloads().catch(() => {}),3500); return; }
    if (next === 'calendar') { if (!$('#calendar-date').value) $('#calendar-date').value = localDate(); await loadCalendar(); return; }
    if (next === 'channels') { renderChannels(); return; }
    $('#hero').hidden = true;
    $('#catalog-errors').hidden = true;
    $('#catalog-empty').hidden = true;
    $('#catalog-loading').hidden = true;
    $('#media-grid').innerHTML = '';
    $('#load-more').hidden = true;
    $('#refresh-catalog').hidden = next === 'favorites';
    $('#catalog-eyebrow').textContent = next === 'favorites' ? 'LA TUA RACCOLTA' : next === 'search' ? 'CERCA NEI TUOI CANALI' : 'LA TUA VIDEOTECA';
    $('#catalog-title').textContent = next === 'search' ? (query ? `Risultati per “${query}”` : 'Cerca') : state.channels.find(c => String(c.id) === channel)?.name || 'I miei canali';
    if (next === 'favorites') {
      items = state.favorites.filter(item => !channel || String(item.channel_id) === channel);
      nextPages = {}; renderGrid();
      if (!items.length) emptyState('favorites');
    } else if (next === 'search') {
      $('#search-input').focus();
      if (query) await loadSearch();
      else { items = []; renderGrid(); emptyState(state.channels.length ? 'search' : 'initial'); }
    } else {
      query = ''; $('#search-input').value = ''; await loadCatalog();
    }
  }
  async function loadCatalog(more = false) {
    const request = ++catalogRequest;
    const channels = state.channels.filter(c => !channel || String(c.id) === channel);
    if (!channels.length) { items = []; nextPages = {}; renderGrid(); emptyState('initial'); return; }
    if (!more) {
      items = []; nextPages = {}; $('#media-grid').innerHTML = ''; $('#hero').hidden = true;
      $('#catalog-empty').hidden = true; $('#catalog-loading').hidden = false; $('#result-count').textContent = '';
    }
    renderErrors([]);
    const button = $('#load-more');
    if (more) setBusy(button, true, 'Caricamento…');
    const targets = channels.filter(c => !more || nextPages[c.id]);
    const results = await Promise.all(targets.map(async c => {
      try {
        const result = await api(`/api/catalog?${new URLSearchParams({channel:c.id,page:String(more ? nextPages[c.id] : 1)})}`);
        return {channel:c, ...result};
      } catch (error) { return {channel:c, error:error.message, items:[]}; }
    }));
    if (request !== catalogRequest) { if (more) setBusy(button,false); return; }
    const errors = [];
    for (const result of results) {
      if (result.error) errors.push({name:result.channel.name,error:result.error});
      if (result.next_page) nextPages[result.channel.id] = result.next_page;
      else delete nextPages[result.channel.id];
      for (const media of result.items || []) {
        if (!items.some(item => item.url === media.url)) items.push({...media,channel_id:media.channel_id || result.channel.id,channel_name:media.channel_name || result.channel.name});
      }
    }
    $('#catalog-loading').hidden = true;
    setBusy(button,false);
    renderErrors(errors); renderGrid(); renderHero();
    if (!items.length) emptyState(errors.length ? 'failed' : 'noresults','Il canale non ha restituito titoli in questa pagina. Puoi provare la ricerca o un altro canale.');
  }
  async function loadSearch() {
    const request = ++catalogRequest;
    $('#catalog-loading').hidden = false; $('#catalog-empty').hidden = true; $('#hero').hidden = true;
    $('#media-grid').innerHTML = ''; $('#result-count').textContent = ''; $('#load-more').hidden = true;
    renderErrors([]);
    try {
      const result = await api(`/api/search?${new URLSearchParams({q:query,...(channel ? {channel} : {})})}`);
      if (request !== catalogRequest) return;
      items = result.items || []; nextPages = {};
      renderErrors(result.errors || (result.error ? [{error:result.error}] : []));
      renderGrid();
      if (!items.length) emptyState('noresults');
    } catch (error) {
      if (request !== catalogRequest) return;
      items = []; renderGrid(); emptyState('failed',error.message);
    } finally { if (request === catalogRequest) $('#catalog-loading').hidden = true; }
  }
  function statusInfo(c) {
    const status = String(c.status || '').toLowerCase();
    const ready = !c.error && ['ok','ready','available','success','online'].includes(status);
    if (ready) return {className:'ready',label:c.count ? `${c.count} titoli letti` : 'Raggiungibile'};
    if (c.error || ['error','unavailable','offline','failed'].includes(status)) return {className:'unavailable',label:'Non disponibile'};
    return {className:'',label:status === 'checking' ? 'Verifica in corso' : 'Da verificare'};
  }
  function renderChannels() {
    if(!$('#channel-tools-nav')) $('#channels-view>.section-heading').insertAdjacentHTML('afterend','<div id="channel-tools-nav" class="library-actions"><button class="button ghost" data-channel-dialog="manual">Aggiungi canale</button><button class="button ghost" data-channel-dialog="list">Lista automatica</button><button class="button ghost" data-nav="library">Download e libreria</button><button class="button ghost" data-nav="calendar">Calendario Serie TV</button></div>');
    $('#list-url').value = state.list_url || LIST_URL;
    const updated = friendlyDate(state.last_refresh);
    $('#list-updated').textContent = updated ? `Ultimo aggiornamento: ${updated}` : 'La lista viene letta quando scegli di importarla o aggiornarla.';
    $('#channel-count').textContent = `${state.channels.length} ${state.channels.length === 1 ? 'canale' : 'canali'}`;
    $('#channels-list').innerHTML = state.channels.length ? state.channels.map(c => {
      const status = statusInfo(c);
      return `<article class="channel-row"><div class="channel-avatar">${icon('channels')}</div><div class="channel-content"><h3>${escapeHTML(c.name || c.url)}</h3><span class="channel-url" title="${escapeHTML(c.url)}">${escapeHTML(c.url)}</span>${c.in_current_list === false ? '<div class="channel-list-note">Non più presente nella lista aggiornata</div>' : ''}${c.error ? `<div class="channel-error">${escapeHTML(c.error)}</div>` : ''}</div><span class="channel-state ${status.className}">${escapeHTML(status.label)}</span><div class="channel-tools"><button class="button ghost" data-channel="${escapeHTML(c.id)}">Esplora</button><button class="icon-button" data-remove="${escapeHTML(c.id)}" aria-label="Rimuovi ${escapeHTML(c.name || c.url)}" title="Rimuovi canale">${icon('trash')}</button></div></article>`;
    }).join('') : `<div class="settings-card"><h3>Nessun canale aggiunto</h3><p>Importa la lista qui sopra oppure incolla un indirizzo per iniziare.</p></div>`;
  }
  async function refreshChannels() {
    if (refreshBusy) return;
    refreshBusy = true;
    const button = $('#refresh-channels');
    setBusy(button,true,'Aggiorno i canali…');
    showMessage($('#channels-message'),'Leggo la lista e controllo i canali. Alcuni siti possono richiedere qualche secondo.');
    try {
      applyState(await api('/api/refresh',{}));
      await reloadState();
      showMessage($('#channels-message'),'Lista aggiornata. Controlla lo stato di ogni canale qui sotto.');
      toast('Lista e canali aggiornati');
      if (view === 'home') await loadCatalog();
    } catch (error) { showMessage($('#channels-message'),error.message,true); toast(error.message,true); }
    finally { refreshBusy = false; setBusy(button,false); }
  }
  async function addChannels(urls, button) {
    setBusy(button,true,'Verifico i canali…');
    showMessage($('#channels-message'),'Leggo gli indirizzi e controllo i cataloghi…');
    let succeeded = 0;
    const errors = [];
    for (const url of urls) {
      try { applyState(await api('/api/channels',{url})); succeeded++; }
      catch (error) { errors.push(error.message); }
    }
    try { await reloadState(); }
    catch (error) { errors.push(error.message); }
    setBusy(button,false);
    const text = errors.length ? `${succeeded ? `${succeeded} ${succeeded === 1 ? 'indirizzo elaborato' : 'indirizzi elaborati'}. ` : ''}${errors.join(' ')}` : 'Canali aggiunti. Puoi aprire i cataloghi dal pulsante Esplora.';
    showMessage($('#channels-message'),text,errors.length > 0);
    if (!errors.length) { $('#manual-urls').value = ''; toast('Canali aggiornati'); }
  }
  async function openDetail(media) {
    stopHeroTrailer();
    const request = ++detailRequest;
    sourceRequest++;
    detail = {...media};
    $('#detail-content').hidden = true; $('#detail-content').innerHTML = '';
    $('#detail-loading').hidden = false;
    if (!$('#detail-dialog').open) $('#detail-dialog').show();
    try {
      const result = await api(`/api/detail?${new URLSearchParams({url:media.url,channel:media.channel_id || ''})}`);
      if (request !== detailRequest) return;
      detail = {...media,...result,year:result.year || media.year,poster:result.poster || media.poster,channel_id:media.channel_id,channel_name:media.channel_name};
      renderDetail();
    } catch (error) {
      if (request !== detailRequest) return;
      detail.error = error.message; renderDetail();
    }
    finally { if (request === detailRequest) { $('#detail-loading').hidden = true; $('#detail-content').hidden = false; } }
  }
  function sourceButtons(sources, resolved = false) {
    return sources.map((source,index) => `<div class="host-option"><button class="source-button" ${resolved ? 'data-resolved' : 'data-source'}="${index}">${icon('play')}<span>${escapeHTML(source.label || `Sorgente ${index + 1}`)}</span>${icon('arrow')}</button>${!resolved?integrations.filter(s=>s.connected&&['rd','torbox'].includes(s.id)).map(s=>`<button class="button ghost integration-resolve" data-integration-resolve="${escapeHTML(s.id)}" data-host-index="${index}">Apri con ${escapeHTML(s.name)}</button>`).join(''):''}</div>`).join('');
  }
  function renderDetail() {
    if (!detail) return;
    const saved = isFavorite(detail);
    const sources = detail.sources || [], episodes = detail.episodes || [];
    const genres=(detail.genres||[]).map(g=>typeof g==='string'?g:g.name).filter(Boolean),rating=ratingValue(detail.rating);
    const seasons=[...new Set(episodes.map(e=>e.season || e.season_number).filter(s=>s!==undefined&&s!==null))];
    $('#detail-content').innerHTML = `<div class="detail-head">${detail.backdrop || detail.poster ? `<img class="detail-background" src="${escapeHTML(imageURL(detail.backdrop || detail.poster))}" alt="">` : ''}<div class="detail-title-area"><h2 id="detail-title">${escapeHTML(detail.title || 'Dettaglio titolo')}</h2><div class="hero-meta">${detail.year ? `<span>${escapeHTML(detail.year)}</span><span class="dot"></span>` : ''}<span>${escapeHTML(genres.join(', ') || mediaKind(detail))}</span>${detail.runtime?`<span> · ${escapeHTML(detail.runtime)}${typeof detail.runtime==='number'?' min':''}</span>`:''}</div>${rating?`<div class="detail-rating"><span class="rating">★${escapeHTML(rating)}</span></div>`:''}</div></div><div class="detail-body"><div class="detail-actions"><button class="button" data-action="detail-play">${icon('play')}${episodes.length?'Episodi':'Riproduci'}</button><button id="favorite-button" class="button ghost ${saved ? 'saved' : ''}" aria-pressed="${saved}">${icon('star')}${saved ? 'Nei preferiti' : 'Aggiungi ai preferiti'}</button><button class="button ghost" data-action="detail-watchlist">Aggiungi a una lista</button><button class="button ghost" data-action="detail-watched">Segna come visto</button>${detail.trailer?.url?'<button class="button ghost" data-action="detail-trailer">Trailer</button>':''}</div><p class="detail-description">${escapeHTML(detail.description || '')}</p>${detail.cast?.length?`<h3>Cast</h3><div class="detail-cast">${detail.cast.map(c=>`<div class="cast-person">${c.image?`<img src="${escapeHTML(imageURL(c.image))}" alt="" loading="lazy">`:'<div class="cast-placeholder"></div>'}<strong>${escapeHTML(c.name)}</strong><small>${escapeHTML(c.role||'')}</small></div>`).join('')}</div>`:''}${detail.error ? `<div class="message error">${escapeHTML(detail.error)}</div>` : ''}<div id="source-feedback" class="message" role="status" hidden></div><div id="resolved-sources"></div>${sources.length ? `<section class="source-section" id="detail-source-section"><h3>Scegli una sorgente</h3><div class="source-list">${sourceButtons(sources)}</div></section>` : ''}${episodes.length ? `<section class="source-section" id="detail-episode-section"><h3>Episodi disponibili</h3>${seasons.length?`<div class="detail-season"><label for="season-filter">Stagione</label><select id="season-filter"><option value="">Tutte le stagioni</option>${seasons.map(s=>`<option value="${escapeHTML(s)}">Stagione ${escapeHTML(s)}</option>`).join('')}</select></div>`:''}<div class="episode-list">${episodes.map((episode,index) => `<button class="episode-button" data-episode="${index}" data-season="${escapeHTML(episode.season||episode.season_number||'')}"><span>${escapeHTML(episode.label || episode.title || `Episodio ${index+1}`)}</span>${icon('arrow')}</button>`).join('')}</div></section>` : ''}${!sources.length && !episodes.length && !detail.error ? '<div class="message" style="margin-top:24px">Il canale non ha restituito una sorgente riproducibile per questo titolo.</div>' : ''}<div class="detail-metadata">${detail.year?`<div>Anno<strong>${escapeHTML(detail.year)}</strong></div>`:''}${genres.length?`<div>Generi<strong>${escapeHTML(genres.join(', '))}</strong></div>`:''}${detail.runtime?`<div>Durata<strong>${escapeHTML(detail.runtime)}${typeof detail.runtime==='number'?' minuti':''}</strong></div>`:''}${detail.channel_name?`<div>Canale<strong>${escapeHTML(detail.channel_name)}</strong></div>`:''}</div>${detail.similar?.length?`<section class="home-section"><h2>Altri titoli simili</h2><div class="media-row">${detail.similar.map((m,i)=>`<button class="media-card" data-similar="${i}" aria-label="Apri ${escapeHTML(m.title)}"><span class="poster-wrap">${m.poster?`<img src="${escapeHTML(imageURL(m.poster))}" alt="" loading="lazy">`:`<span class="poster-fallback">${icon('play')}</span>`}</span><span class="card-title">${escapeHTML(m.title)}</span></button>`).join('')}</div></section>`:''}</div>`;
    insertTitleImage($('#detail-content'),detail);
    const valueText=value=>Array.isArray(value)?value.map(v=>typeof v==='object'?v.name||v.title||'':v).filter(Boolean).join(', '):typeof value==='object'?value?.name||value?.title||'':String(value??'');
    if(detail.tagline){const tagline=document.createElement('p');tagline.className='detail-tagline';tagline.textContent=detail.tagline;$('#detail-content .detail-title-area h2').after(tagline);}
    const facts=[['Regia',detail.director],['Data di uscita',detail.release_date],['Paese',detail.country],['Lingua originale',detail.original_language],['Budget',detail.budget],['Incasso',detail.revenue],['Produzione',detail.production_companies],['Collezione',detail.collection]].filter(([,value])=>Boolean(value)&&valueText(value));
    if(facts.length)$('#detail-content .detail-body').insertAdjacentHTML('beforeend',`<section class="detail-facts"><h3>Dettagli</h3>${facts.map(([label,value])=>`<div><span>${label}</span><strong>${escapeHTML(valueText(value))}</strong></div>`).join('')}</section>`);
    if(Array.isArray(detail.galleries)&&detail.galleries.length)$('#detail-content .detail-body').insertAdjacentHTML('beforeend',`<section class="home-section"><h2>Immagini</h2><div class="gallery-row">${detail.galleries.map((image,i)=>`<button data-gallery="${i}" aria-label="Apri immagine ${i+1}"><img src="${escapeHTML(imageURL(typeof image==='string'?image:image.url))}" alt="" loading="lazy"></button>`).join('')}</div></section>`);
    if(detail.cast_source){const source=typeof detail.cast_source==='string'?{url:detail.cast_source,name:'TVMaze',license:'CC BY-SA'}:detail.cast_source;if(/^https?:\/\//i.test(source.url||'')){const attribution=document.createElement('p');attribution.className='cast-attribution';attribution.innerHTML=`Foto del cast: <a href="${escapeHTML(source.url)}" target="_blank" rel="noopener noreferrer">${escapeHTML(source.name||'Fonte')}</a>${source.license?' · '+escapeHTML(source.license):''}`;$('#detail-content .detail-cast')?.after(attribution);}}
    $('#detail-content').querySelectorAll('img').forEach(img => img.addEventListener('error',()=>{img.hidden = true;},{once:true}));
  }
  async function toggleFavorite() {
    if (!detail) return;
    const media = mediaPayload(detail);
    const enabled = !isFavorite(media);
    const button = $('#favorite-button');
    button.disabled = true;
    try {
      const result = await api('/api/favorite',{media,enabled});
      if (result?.channels || result?.state) applyState(result);
      else {
        state.favorites = state.favorites.filter(item => item.url !== media.url);
        if (enabled) state.favorites.push(media);
      }
      button.classList.toggle('saved',enabled);
      button.setAttribute('aria-pressed',String(enabled));
      button.innerHTML = `${icon('star')}${enabled ? 'Nei preferiti' : 'Aggiungi ai preferiti'}`;
      if (view === 'favorites') { await loadCollection(); }
      renderGrid();
      toast(enabled ? 'Titolo aggiunto ai preferiti' : 'Titolo rimosso dai preferiti');
    } catch (error) { toast(error.message,true); }
    finally { button.disabled = false; }
  }
  async function resolveSource(source, episode = false) {
    if (!source?.url || !detail) return;
    const request = ++sourceRequest;
    const feedback = $('#source-feedback');
    feedback.className = 'message'; feedback.hidden = false;
    feedback.innerHTML = '<span class="source-status"><span class="spinner"></span>Controllo la sorgente video…</span>';
    $('#resolved-sources').innerHTML = '';
    const referer = source.referer || detail.url;
    let media = {...detail};
    const episodeIsPage = episode && source.kind === 'page';
    if (episode) media = {...detail,url:source.url,series_url:detail.url,episode:{...source},title:`${detail.title} · ${source.label || source.title || 'Episodio'}`};
    try {
      let result;
      if (episodeIsPage) {
        const episodeDetail = await api(`/api/detail?${new URLSearchParams({url:source.url,channel:detail.channel_id || ''})}`);
        if (request !== sourceRequest) return;
        const candidates = episodeDetail.sources || [];
        if (candidates.length > 1) {
          detail.episodeSources = candidates; detail.episodeMedia = media;
          $('#resolved-sources').innerHTML = `<section class="source-section"><h3>${escapeHTML(source.label || source.title || 'Sorgenti episodio')}</h3><div class="source-list">${candidates.map((s,index) => `<button class="source-button" data-episode-source="${index}">${icon('play')}<span>${escapeHTML(s.label || `Sorgente ${index + 1}`)}</span>${icon('arrow')}</button>`).join('')}</div></section>`;
          feedback.hidden = true; return;
        }
        result = await api('/api/resolve',{url:candidates[0]?.url || source.url,referer:source.url});
      } else result = await api('/api/resolve',{url:source.url,referer});
      if (request !== sourceRequest) return;
      const sources = result.sources || [];
      if (!sources.length) throw new Error(result.error || 'La sorgente non ha restituito un video diretto riproducibile. Prova un altro host.');
      detail.resolvedSources = sources;
      detail.resolvedMedia = media;
      detail.resolvedReferer = episodeIsPage ? source.url : referer;
      feedback.hidden = true;
      if (sources.length === 1) playResolved(sources[0],media,detail.resolvedReferer);
      else $('#resolved-sources').innerHTML = `<section class="source-section"><h3>Sorgenti riproducibili</h3><div class="source-list">${sourceButtons(sources,true)}</div></section>`;
    } catch (error) {
      if (request !== sourceRequest) return;
      showMessage(feedback,error.message,true);
    }
  }
  async function resolveEpisodeSource(source) {
    const media = detail.episodeMedia;
    const request = ++sourceRequest;
    showMessage($('#source-feedback'),'Controllo la sorgente dell’episodio…');
    try {
      const result = await api('/api/resolve',{url:source.url,referer:media.url});
      if (request !== sourceRequest) return;
      if (!result.sources?.length) throw new Error(result.error || 'Nessun video disponibile da questa sorgente.');
      detail.resolvedSources = result.sources; detail.resolvedMedia = media; detail.resolvedReferer = media.url;
      $('#source-feedback').hidden = true;
      if (result.sources.length === 1) playResolved(result.sources[0],media,media.url);
      else $('#resolved-sources').innerHTML = `<section class="source-section"><h3>Sorgenti riproducibili</h3><div class="source-list">${sourceButtons(result.sources,true)}</div></section>`;
    } catch (error) { if (request === sourceRequest) showMessage($('#source-feedback'),error.message,true); }
  }
  function ensureHLS() {
    if (window.Hls) return Promise.resolve(window.Hls);
    if (hlsLoader) return hlsLoader;
    hlsLoader = new Promise((resolve,reject) => {
      const script = document.createElement('script');
      script.src = '/vendor/hls.min.js';
      script.onload = () => window.Hls ? resolve(window.Hls) : reject(new Error('Il modulo HLS non è disponibile. Puoi usare MPV.'));
      script.onerror = () => reject(new Error('Il modulo HLS non è installato. Usa “Apri con MPV” per questa sorgente.'));
      document.head.append(script);
    });
    return hlsLoader;
  }
  async function playResolved(source, media, referer) {
    stopHeroTrailer();
    await saveProgress();
    destroyVideo();
    currentPlayback = {source,media:mediaPayload(media),referer:source.headers?.Referer || source.headers?.referer || referer || media.url};
    const active = currentPlayback;
    subtitlePreferenceApplied = false;
    $('#player-title').textContent = media.title || 'Riproduzione';
    $('#player-source').textContent = source.label || 'PLAYER INTEGRATO';
    showMessage($('#player-message'),'Caricamento del video…');
    if (!$('#player-dialog').open) $('#player-dialog').showModal();
    $('#video').focus({preventScroll:true});
    const video = $('#video');
    const local = source.kind === 'local' || source.url?.startsWith('/api/local/file?');
    const url = local ? source.url : `/api/media?${new URLSearchParams({url:source.url,referer:active.referer || ''})}`;
    $('#download-source').hidden = local || media.kind === 'trailer';
    $('#player-mark-watched').hidden = media.kind === 'trailer';
    $('#next-episode').hidden = !nextEpisode();
    if(!$('#player-hosts'))$('#mpv-button').insertAdjacentHTML('afterend','<button id="player-hosts" class="button ghost">Sorgenti</button>');
    $('#player-hosts').hidden=local;
    if(!$('#player-trakt'))$('#player-mark-watched').insertAdjacentHTML('afterend','<button id="player-trakt" class="button ghost">Sincronizza su Trakt</button>');
    $('#player-trakt').hidden=!integrations.some(s=>s.id==='trakt'&&s.connected)||!/^tt\d+/.test(media.imdb||media.imdb_id||'')||(isSeries(media)&&media.kind!=='episode');
    resetTrackControls();
    const isHLS = source.kind === 'hls' || /\.m3u8(?:[?#]|$)/i.test(source.url);
    const progress = state.progress[media.url];
    let restored = false;
    const onMetadata = () => {
      if (currentPlayback !== active || restored) return;
      restored = true;
      if (progress?.position > 5 && Number.isFinite(video.duration) && progress.position < video.duration - 10) video.currentTime = progress.position;
      showMessage($('#player-message'),'Video pronto. Puoi scegliere audio e sottotitoli disponibili dai controlli del player.');
      updatePlayerControls();updateTrackControls();
      if (settings.default_player !== 'mpv' || local) video.play().catch(() => { if (currentPlayback === active) showMessage($('#player-message'),'Video pronto. Premi Play per iniziare.'); });
    };
    video.onloadedmetadata = onMetadata;
    video.onerror = () => { if (currentPlayback === active) showMessage($('#player-message'),'Il browser non riesce a riprodurre questa sorgente o il formato non è supportato. Prova MPV oppure un altro host.',true); };
    try {
      if (isHLS && !video.canPlayType('application/vnd.apple.mpegurl')) {
        const Hls = await ensureHLS();
        if (currentPlayback !== active) return;
        if (!Hls.isSupported()) throw new Error('HLS non è supportato da questo browser. Puoi aprire la sorgente con MPV.');
        hls = new Hls({maxBufferLength:Math.max(30,Number(settings.buffer_minutes||1)*60),backBufferLength:30});
        for (const event of [Hls.Events.MANIFEST_PARSED,Hls.Events.AUDIO_TRACKS_UPDATED,Hls.Events.SUBTITLE_TRACKS_UPDATED]) if (event) hls.on(event,updateTrackControls);
        hls.on(Hls.Events.ERROR,(_event,data) => {
          if (data.fatal && currentPlayback === active) showMessage($('#player-message'),'La sorgente HLS ha interrotto la riproduzione. Prova un altro host oppure MPV.',true);
        });
        hls.loadSource(url); hls.attachMedia(video);
      } else video.src = url;
    } catch (error) { if (currentPlayback === active) showMessage($('#player-message'),error.message,true); }
    progressTimer = setInterval(() => { saveProgress().catch(() => {}); },5000);
    if (settings.default_player === 'mpv' && !local && media.kind !== 'trailer') await launchMPV();
  }
  async function saveProgress() {
    if (!currentPlayback) return;
    if (currentPlayback.media.kind === 'trailer') return;
    const video = $('#video'), url = currentPlayback.media.url;
    if (!url || !Number.isFinite(video.currentTime) || video.currentTime < 1 || !Number.isFinite(video.duration) || video.duration < 1) return;
    const progress = {url,position:video.currentTime,duration:video.duration,media:currentPlayback.media,...(currentPlayback.media.episode ? {episode:currentPlayback.media.episode} : {})};
    state.progress[url] = {position:progress.position,duration:progress.duration};
    try { await api('/api/progress',progress); }
    catch { /* L'avanzamento resta in memoria e sarà ritentato al prossimo intervallo. */ }
  }
  function destroyVideo() {
    clearInterval(progressTimer); progressTimer = null;
    if (hls) { hls.destroy(); hls = null; }
    const video = $('#video');
    video.onloadedmetadata = null; video.onerror = null;
    video.pause(); video.removeAttribute('src'); video.load();
  }
  async function launchMPV() {
    if (!currentPlayback) return;
    const button = $('#mpv-button'); setBusy(button,true,'Apro MPV…');
    try {
      const result = await api('/api/mpv',{url:currentPlayback.source.url,referer:currentPlayback.referer});
      if (result.ok === false || result.error) throw new Error(result.error || 'MPV non è disponibile.');
      $('#video').pause(); showMessage($('#player-message'),'Sorgente aperta con MPV. Puoi chiudere questo player.');
    } catch (error) { showMessage($('#player-message'),error.message,true); }
    finally { setBusy(button,false); }
  }
  function ratingValue(value) {
    const raw = typeof value === 'object' ? value?.value ?? value?.average : value;
    const number = Number(raw);
    return Number.isFinite(number) && number > 0 ? number.toFixed(1) : '';
  }
  function insertTitleImage(container,media){if(!media.title_image)return;const heading=container.querySelector('h2');if(!heading)return;const image=document.createElement('img');image.className='title-image';image.src=imageURL(media.title_image);image.alt='';heading.classList.add('sr-only');heading.after(image);image.onerror=()=>{heading.classList.remove('sr-only');image.remove();};}
  function hideBrokenImages(container) { container.querySelectorAll('img').forEach(img => img.addEventListener('error',()=>{img.hidden=true;},{once:true})); }
  function localDate() { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
  function isSeries(media) { return /serie|series|tv|episode/i.test(media.kind || '') || media.episodes?.length > 0; }
  function registerMedia(media) { const index = items.findIndex(m => m.url === media.url); if (index >= 0) return index; items.push(media); return items.length-1; }
  function cardMarkup(media,{rank=0,collection=false}={}) {
    const index = registerMedia(media), progress = state.progress[media.url] || media;
    const percent = progress.duration > 0 ? Math.min(100,Math.max(0,progress.position/progress.duration*100)) : 0;
    return `<button class="media-card ${collection ? 'collection-card' : ''} ${selected.has(media.url) ? 'selected' : ''}" data-media="${index}" aria-label="${selectionMode && collection ? 'Seleziona' : 'Apri'} ${escapeHTML(media.title || '')}">${rank ? `<span class="rank-number">${rank}</span>` : ''}<span class="poster-wrap"><span class="poster-fallback">${icon('play')}</span>${media.poster || media.backdrop ? `<img src="${escapeHTML(imageURL(media.poster || media.backdrop))}" loading="lazy" decoding="async" alt="">` : ''}<span class="poster-overlay"><span class="card-play">${icon('play')}</span></span>${selectionMode && collection ? `<span class="select-tick">${selected.has(media.url) ? '✓' : ''}</span>` : ''}${percent ? `<span class="progress-track"><span class="progress-value" style="width:${percent}%"></span></span>` : ''}</span><span class="card-title">${escapeHTML(media.title || 'Video')}</span><span class="card-meta">${escapeHTML(media.year || '')}</span></button>`;
  }
  function emptyMarkup(iconName,title,description='',action='') { return `<div class="collection-empty">${icon(iconName)}<h2>${escapeHTML(title)}</h2>${description ? `<p>${escapeHTML(description)}</p>` : ''}${action}</div>`; }
  function loadingMarkup(text='Caricamento…') { return `<div class="loading-state"><span class="spinner"></span><p>${escapeHTML(text)}</p></div>`; }
  async function startHeroTrailer(media) {
    stopHeroTrailer();
    const request = heroTrailerRequest;
    if (!settings.trailer_autoplay || !media.trailer?.url) return;
    const hero = $('#hero');let trailer;
    try {
      let source=media.trailer;
      if(!['video','hls'].includes(source.kind)){const result=await api('/api/resolve',{url:source.url,referer:media.url});source=result.sources?.[0];if(!source)return;}
      if(request!==heroTrailerRequest||view!=='home'||document.querySelector('dialog[open]'))return;
      trailer=document.createElement('video');trailer.className='hero-image hero-trailer';trailer.muted=true;trailer.autoplay=true;trailer.loop=true;trailer.playsInline=true;hero.prepend(trailer);
      const url=`/api/media?${new URLSearchParams({url:source.url,referer:source.headers?.Referer||source.headers?.referer||media.url})}`;
      if ((source.kind === 'hls'||/\.m3u8(?:[?#]|$)/i.test(source.url)) && !trailer.canPlayType('application/vnd.apple.mpegurl')) {
        const Hls = await ensureHLS(); if (request!==heroTrailerRequest||view !== 'home' || !trailer.isConnected) return;
        heroHls = new Hls({maxBufferLength:10,backBufferLength:0}); heroHls.loadSource(url); heroHls.attachMedia(trailer);
        heroHls.on(Hls.Events.ERROR,(_event,data)=>{if(data.fatal&&request===heroTrailerRequest)stopHeroTrailer();});
      } else trailer.src = url;
      trailer.play().catch(()=>{});
      const mute = document.createElement('button');mute.className='icon-button trailer-mute';mute.innerHTML=icon('volume');mute.setAttribute('aria-label','Attiva audio trailer');
      mute.onclick=()=>{trailer.muted=!trailer.muted;mute.setAttribute('aria-label',trailer.muted?'Attiva audio trailer':'Disattiva audio trailer');};hero.querySelector('.hero-actions').append(mute);
      trailer.onerror=()=>{if(request===heroTrailerRequest)stopHeroTrailer();};
    } catch { if(trailer)trailer.remove(); }
  }
  function stopHeroTrailer(){heroTrailerRequest++;if(heroHls){heroHls.destroy();heroHls=null;}const video=$('#hero video');if(video){video.pause();video.removeAttribute('src');video.load();video.remove();}$('#hero .trailer-mute')?.remove();}
  async function loadHome() {
    const request = ++catalogRequest;
    $('#home-content').innerHTML = loadingMarkup('Carico la tua videoteca…');
    try {
      const data = await api('/api/home'); if (request !== catalogRequest || view !== 'home') return;
      homeData = data; items = []; heroIndex = 0;
      let markup = '';
      if (settings.show_url) markup += '<form id="home-url-form" class="home-url-form"><label class="sr-only" for="home-video-url">URL del video</label><input id="home-video-url" type="url" required placeholder="Incolla un indirizzo video"><button class="button" type="submit">Riproduci da URL</button></form>';
      const platforms = data.platforms || [];
      if (platforms.length) markup += `<section class="home-section"><h2>Esplora per piattaforma</h2><div class="platform-row">${platforms.map(p=>`<button class="platform-tile" data-platform="${escapeHTML(p.id)}">${escapeHTML(p.name)}</button>`).join('')}</div></section>`;
      for (const section of data.sections || []) {
        if (!section.items?.length) continue;
        const top = /top.?10|ranking/i.test(section.id), continuing = /continu|resume/i.test(section.id);
        markup += `<section class="home-section"><h2>${escapeHTML(section.title)}</h2><div class="media-row ${top ? 'top-ten' : ''} ${continuing ? 'continue-row' : ''}">${section.items.map((m,i)=>cardMarkup(m,{rank:top?i+1:0})).join('')}</div></section>`;
      }
      if (!(data.hero || []).length && !(data.sections || []).some(s=>s.items?.length)) markup += `<div class="home-empty"><h2>Non ci sono ancora titoli da mostrare</h2><p>Aggiungi i tuoi canali per consultare i cataloghi e cercare film e serie.</p><button class="button" data-nav="channels">I miei canali</button></div>`;
      if (data.errors?.length) markup += `<details class="home-error"><summary class="muted">Stato dei canali</summary>${data.errors.map(e=>`<p class="muted">${escapeHTML(e.name || 'Canale')}: ${escapeHTML(e.error)}</p>`).join('')}</details>`;
      $('#home-content').innerHTML = markup; renderHero(); hideBrokenImages($('#home-view'));
      if ((data.hero || []).length > 1 && !matchMedia('(prefers-reduced-motion: reduce)').matches) heroTimer = setInterval(()=>{if(view==='home'&&!document.querySelector('dialog[open]')){heroIndex++;renderHero();}},7000);
    } catch (error) { if (request === catalogRequest) { $('#hero').hidden=true;$('#home-content').innerHTML=`<div class="home-empty"><h2>La videoteca non è disponibile</h2><p>${escapeHTML(error.message)}</p><button class="button" data-nav="channels">Controlla i canali</button></div>`; } }
  }
  async function loadDiscover(more=false) {
    const request = ++catalogRequest;
    if (!more) { discoverPage=1;discoverItems=[];$('#discover-categories').innerHTML='';$('#discover-results').innerHTML=loadingMarkup('Carico i titoli…'); }
    const params = {kind:discoverKind,genre:$('#discover-genre').value,platform:$('#discover-platform').value,year:$('#discover-year').value,sort:$('#discover-sort').value,page:String(more ? discoverNext : 1)};
    try {
      const data = await api(`/api/discover?${new URLSearchParams(params)}`);if(request!==catalogRequest)return;
      discoverNext=data.next_page;discoverItems.push(...(data.items || []));items=[];
      const genres=data.genres || data.categories || [];
      const previous=$('#discover-genre').value;
      if(genres.length){$('#discover-genre').innerHTML='<option value="">Tutti i generi</option>'+genres.map(g=>`<option value="${escapeHTML(g.id)}">${escapeHTML(g.name)}</option>`).join('');$('#discover-genre').value=previous;}
      if(data.platforms?.length){const platform=$('#discover-platform').value;$('#discover-platform').innerHTML='<option value="">Tutte le piattaforme</option>'+data.platforms.map(p=>`<option value="${escapeHTML(p.id)}">${escapeHTML(p.name)}</option>`).join('');$('#discover-platform').value=platform;}
      const filtered=Boolean(params.genre||params.platform||params.year||params.sort!=='popular');
      $('#discover-filters').hidden = !filtered && !discoverFiltersVisible;
      if (!$('#toggle-discover-filters')) $('#discover-view .page-title').insertAdjacentHTML('beforeend','<div class="page-tools"><button class="icon-button" id="toggle-discover-filters" aria-label="Mostra o nascondi filtri" title="Filtri">'+icon('settings')+'</button></div>');
      $('#discover-categories').hidden=filtered;
      $('#discover-categories').innerHTML=(data.categories||[]).map((c,i)=>`<button class="category-tile" data-category="${escapeHTML(c.id)}">${c.image?`<img src="${escapeHTML(imageURL(c.image))}" alt="" loading="${i<15?'eager':'lazy'}">`:''}<span>${escapeHTML(c.name)}</span></button>`).join('');
      $('#discover-results').innerHTML=discoverItems.length?`<div class="media-grid">${discoverItems.map(m=>cardMarkup(m)).join('')}</div>`:emptyMarkup('search','Nessun titolo disponibile con questi filtri');
      $('#discover-more').hidden=!discoverNext;hideBrokenImages($('#discover-view'));
    } catch(error){if(request===catalogRequest)$('#discover-results').innerHTML=`<div class="message error">${escapeHTML(error.message)}</div>`;}
  }
  async function loadCollection() {
    $('#collection-content').innerHTML=loadingMarkup();
    try {
      const data=await api(view==='history'?'/api/history':'/api/watchlists');
      if(view==='history'){historyItems=(data.items||[]).map(row=>row.media?{...row.media,...(data.progress?.[row.media.url]||{}),watched:row.watched,watched_at:row.watched_at}:row);if(data.progress)state.progress={...state.progress,...data.progress};}else watchlists=data.watchlists||[];
      renderCollection();
    }catch(error){$('#collection-content').innerHTML=`<div class="message error">${escapeHTML(error.message)}</div>`;}
  }
  function currentCollectionItems(){const all=view==='history'?historyItems:activeWatchlist==='favorites'?state.favorites:watchlists.find(l=>l.id===activeWatchlist)?.items||[];return all.filter(m=>collectionKind==='series'?isSeries(m):!isSeries(m));}
  function renderCollection() {
    const history=view==='history', list=watchlists.find(l=>l.id===activeWatchlist);
    $('#collection-title').textContent=history?'Visti':activeWatchlist==='favorites'?'I miei preferiti':list?.name||'Watchlists';
    $('#watchlist-select').hidden=history;$('#new-watchlist').hidden=history;$('#collection-menu').hidden=history;
    $('#watchlist-select').innerHTML='<option value="favorites">I miei preferiti</option>'+watchlists.map(l=>`<option value="${escapeHTML(l.id)}">${escapeHTML(l.name)}</option>`).join('');$('#watchlist-select').value=activeWatchlist;
    $('#selection-toolbar').hidden=!selectionMode;$('#selection-count').textContent=`${selected.size} selezionati`;
    const data=currentCollectionItems();items=[];
    $('#collection-content').innerHTML=data.length?`<div class="media-grid">${data.map(m=>cardMarkup(m,{collection:true})).join('')}</div>`:emptyMarkup(history?'play':'star',history?'Non hai ancora visto nessun video':'Non hai ancora inserito nessun elemento');
    hideBrokenImages($('#collection-content'));
  }
  function actionDialog(title,body,onSubmit) {
    const dialog=$('#action-dialog');dialog.classList.remove('image-dialog');$('#action-content').innerHTML=`<h2>${escapeHTML(title)}</h2><div id="action-error" class="message error" role="alert" hidden></div>${body}`;
    const form=dialog.querySelector('form');if(form&&onSubmit)form.onsubmit=async e=>{e.preventDefault();const button=form.querySelector('button[type=submit]');if(button)button.disabled=true;$('#action-error').hidden=true;try{await onSubmit(new FormData(form));if(dialog.open)dialog.close();}catch(error){showMessage($('#action-error'),error.message,true);}finally{if(button)button.disabled=false;}};
    if(!dialog.open)dialog.showModal();dialog.querySelector('input,select,textarea')?.focus();
  }
  function watchlistNameDialog(rename=false) {
    const list=watchlists.find(l=>l.id===activeWatchlist);if(rename&&!list)return;
    actionDialog(rename?'Rinomina lista':'Nuova watchlist',`<form><label for="watchlist-name">Nome della lista</label><input id="watchlist-name" name="name" maxlength="80" value="${escapeHTML(rename?list.name:'')}" required><div class="actions"><button class="button" type="submit">Salva</button></div></form>`,async form=>{const result=await api('/api/watchlists',{...(rename?{id:list.id}:{}),name:form.get('name')});watchlists=result.watchlists||[];if(!rename)activeWatchlist=watchlists.at(-1)?.id||'favorites';renderCollection();});
  }
  async function removeSelected() {
    if(!selected.size)return;
    for(const url of selected){if(view==='history')await api('/api/history',{url},'DELETE');else if(activeWatchlist==='favorites'){const media=state.favorites.find(m=>m.url===url);if(media)applyState(await api('/api/favorite',{media,enabled:false}));}else await api('/api/watchlists',{id:activeWatchlist,url},'DELETE');}
    selected.clear();selectionMode=false;await reloadState();await loadCollection();toast('Titoli rimossi dalla raccolta');
  }
  async function addToWatchlist() {
    const data=await api('/api/watchlists');watchlists=data.watchlists||[];
    if(!watchlists.length){actionDialog('Crea una lista',`<p>Non hai ancora creato una watchlist.</p><form><label>Nome della lista<input name="name" required maxlength="80"></label><button class="button" type="submit">Crea e aggiungi titolo</button></form>`,async form=>{const created=await api('/api/watchlists',{name:form.get('name')});watchlists=created.watchlists||[];const id=watchlists.at(-1)?.id;if(id)await api('/api/watchlists',{id,media:mediaPayload(detail),enabled:true});toast('Titolo aggiunto alla lista');});return;}
    actionDialog('Aggiungi a una watchlist',`<form><label for="target-watchlist">Lista</label><select id="target-watchlist" name="id">${watchlists.map(l=>`<option value="${escapeHTML(l.id)}">${escapeHTML(l.name)}</option>`).join('')}</select><button class="button" type="submit">Aggiungi</button></form>`,async form=>{await api('/api/watchlists',{id:form.get('id'),media:mediaPayload(detail),enabled:true});toast('Titolo aggiunto alla lista');});
  }
  async function saveSetting(key,value) { const result=await api('/api/settings',{settings:{[key]:value}});settings={...settings,...result.settings};applySettings();if(view==='settings')layoutSettingsMobile(); }
  function applySettings(){document.documentElement.style.setProperty('--poster-size',({small:'120px',medium:'140px',large:'180px'})[settings.poster_size]||'140px');}
  async function fetchSettings(){try{const data=await api('/api/settings');settings={...settings,...data.settings};applySettings();}catch{/* Il resto dell'app resta utilizzabile durante l'aggiornamento del server. */}}
  async function fetchOptionalState(){await Promise.all([api('/api/profiles').then(data=>{profiles=data.profiles||[];activeProfile=data.active_profile||'';}).catch(()=>{}),api('/api/integrations').then(data=>{integrations=data.services||[];}).catch(()=>{})]);}
  function settingRow(title,description,control){return `<div class="setting-row"><div class="setting-copy"><h2>${escapeHTML(title)}</h2><p>${escapeHTML(description)}</p></div><div class="setting-value">${control}</div></div>`;}
  function selectSetting(key,options){return `<select data-setting="${key}" aria-label="${key}">${options.map(([value,label])=>`<option value="${value}" ${String(settings[key])===String(value)?'selected':''}>${label}</option>`).join('')}</select>`;}
  async function loadSettingsView(){await fetchSettings();try{const data=await api('/api/profiles');profiles=data.profiles||[];activeProfile=data.active_profile||'';}catch{profiles=[];}try{const data=await api('/api/integrations');integrations=data.services||[];}catch{integrations=[];}renderSettings();}
  function renderSettings(){
    $('#settings-content').innerHTML=`<h2 class="settings-group-title">⌂ &nbsp; Home</h2>${settingRow('Mostra “Riproduci da URL”','Mostra il componente per riprodurre un video da URL nella Home',selectSetting('show_url',[[false,'NO'],[true,'SÌ']]))}${settingRow('Trailer automatici','Avvia automaticamente i trailer video diretti disponibili in background. I trailer ospitati su servizi esterni si aprono solo su richiesta.',selectSetting('trailer_autoplay',[[false,'NO'],[true,'SÌ']]))}${settingRow('Dimensione locandine','Seleziona la dimensione delle locandine',selectSetting('poster_size',[['small','PICCOLE'],['medium','MEDIE'],['large','GRANDI']]))}<h2 class="settings-group-title">▷ &nbsp; Riproduzione video</h2>${settingRow('Player di default','Seleziona il player avviato dopo la scelta della sorgente',selectSetting('default_player',[['integrated','INTEGRATO'],['mpv','MPV']]))}${settingRow('Dimensioni del buffer del Player Integrato','Minuti di video mantenuti nel buffer, quando la sorgente HLS li rende disponibili',selectSetting('buffer_minutes',[[1,'1 MIN'],[2,'2 MIN'],[3,'3 MIN'],[5,'5 MIN']]))}${settingRow('Lingua sottotitoli','Lingua preferita tra le tracce rese disponibili dalla sorgente',selectSetting('subtitle_language',[['it','ITALIANO'],['en','INGLESE'],['es','SPAGNOLO'],['fr','FRANCESE']]))}${settingRow('Autoplay','Riproduce automaticamente l’episodio successivo quando è disponibile una sorgente compatibile',selectSetting('autoplay_next',[[false,'NO'],[true,'SÌ']]))}<h2 class="settings-group-title">↓ &nbsp; Download</h2>${settingRow('Destinazione download',settings.download_dir||'Cartella predefinita dell’app','<button class="button ghost" data-action="download-dir">Imposta cartella</button>')}<h2 class="settings-group-title">↗ &nbsp; Servizi esterni</h2><div class="setting-row setting-disabled"><div class="setting-copy"><h2>Account e sincronizzazione cloud</h2><p>Google, Trakt.tv, Real-Debrid e TorBox non sono configurati in questa app indipendente. I dati vengono salvati sul computer.</p></div><div class="setting-value">NON CONFIGURATI</div></div><h2 class="settings-group-title">▤ &nbsp; Dati e backup</h2>${settingRow('Esporta lista canali','Salva un file JSON dei canali aggiunti','<button class="button ghost" data-action="export-channels">Esporta</button>')}${settingRow('Esporta backup','Salva canali, preferenze, watchlists e progressi in un file','<button class="button ghost" data-action="export-backup">Esporta</button>')}${settingRow('Importa backup','Unisci un backup ai dati salvati. Il server valida il file prima di importarlo.','<button class="button ghost" data-action="import-backup">Scegli file</button>')}<h2 class="settings-group-title">ⓘ &nbsp; Informazioni</h2>${settingRow('Lume','App locale indipendente. Analisi non ufficiale di Veezie.st. Nessun modulo pubblicitario integrato.','<span>LOCALE</span>')}`;
    if(window.LumeCloud){
      $('#settings-content .setting-disabled p').textContent='I dati sono salvati nel browser di questo dispositivo. Trasferiscili con un backup. Le connessioni ai servizi esterni restano disponibili nella versione PC.';
      const player=$('#settings-content [data-setting="default_player"]');if(player){player.value='integrated';player.disabled=true;}
      $('#settings-content [data-action="download-dir"]')?.closest('.setting-row')?.remove();
      $('#settings-content').insertAdjacentHTML('afterbegin','<p class="message">Lume online · Funziona con il PC spento. Profili, liste e progressi rimangono su questo dispositivo.</p>');
    }
    if(integrations.length)$('#settings-content .setting-disabled').outerHTML=integrations.map(service=>settingRow(service.name,service.connected?`Account ${service.account?.name||'collegato'}${service.validated_at?' · Verificato '+friendlyDate(service.validated_at):''}`:'Configurazione disponibile: richiede il tuo account e le tue credenziali.',`<button class="button ghost" data-integration="${escapeHTML(service.id)}">${service.connected?'Gestisci connessione':'Configura'}</button>`)).join('');
    if(profiles.length)$('#settings-content').insertAdjacentHTML('beforeend',`<h2 class="settings-group-title">Profili locali</h2>${settingRow('Profilo attivo','Preferiti, progressi, watchlists e impostazioni sono separati per profilo. I canali sono condivisi.',`<select id="profile-select" aria-label="Profilo attivo">${profiles.map(p=>`<option value="${escapeHTML(p.id)}" ${p.id===activeProfile?'selected':''}>${escapeHTML(p.name)}</option>`).join('')}</select>`)}<div class="library-actions"><button class="button ghost" data-action="profile-create">Nuovo profilo</button><button class="button ghost" data-action="profile-rename">Rinomina profilo attivo</button>${profiles.length>1?'<button class="button ghost" data-action="profile-delete">Elimina un altro profilo</button>':''}</div>`);
    layoutSettingsMobile();document.fonts.ready.then(layoutSettingsMobile);
  }
  function layoutSettingsMobile(){
    const mobile=matchMedia('(max-width:600px)').matches,canvas=document.createElement('canvas'),context=canvas.getContext('2d');
    $$('#settings-content .setting-row').forEach(row=>{
      row.classList.remove('setting-inline','setting-below','setting-stack');if(!mobile){row.querySelectorAll('.setting-value select').forEach(s=>s.style.removeProperty('width'));return;}
      const title=row.querySelector('.setting-copy h2'),value=row.querySelector('.setting-value');if(!title||!value)return;
      const select=value.querySelector('select');if(select){const selectStyle=getComputedStyle(select);context.font=`${selectStyle.fontWeight} ${selectStyle.fontSize} ${selectStyle.fontFamily}`;select.style.width=`${Math.ceil(context.measureText(select.selectedOptions[0]?.textContent||'').width)+8}px`;}
      const style=getComputedStyle(row),available=row.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight);
      const valueWidth=Math.ceil(value.getBoundingClientRect().width),titleStyle=getComputedStyle(title);context.font=`${titleStyle.fontWeight} ${titleStyle.fontSize} ${titleStyle.fontFamily}`;
      row.style.setProperty('--setting-control-width',`${valueWidth}px`);
      if(valueWidth>120||row.classList.contains('setting-disabled'))row.classList.add('setting-stack');
      else if(context.measureText(title.textContent).width+valueWidth+12<=available)row.classList.add('setting-inline');
      else{row.classList.add('setting-below');row.style.setProperty('--setting-title-height',`${Math.ceil(title.getBoundingClientRect().height)}px`);}
    });
  }
  function downloadJSON(data,name){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  async function loadLibrary(){
    $('#library-content').innerHTML=loadingMarkup('Sincronizzo la libreria…');
    try{libraryData=await api('/api/library');renderLibrary();await loadDownloads();}catch(error){$('#library-content').innerHTML=`<div class="message error">${escapeHTML(error.message)}</div>`;}
  }
  function renderLibrary(){
    items=[];const videos=(libraryData.items||[]).filter(m=>libraryKind==='local'||(libraryKind==='series'?isSeries(m):!isSeries(m)));
    $('#library-content').innerHTML=videos.length?`<div class="media-grid">${videos.map(m=>cardMarkup(m)).join('')}</div>`:emptyMarkup('download','', 'In questa sezione puoi visualizzare i video scaricati o presenti nelle cartelle del computer. Configura una cartella oppure sincronizza la libreria.','<button class="button secondary" data-action="pick-folder">Sincronizza</button>');
    $('#library-content').insertAdjacentHTML('beforeend',`<div class="library-actions"><button class="button secondary" data-action="pick-folder">Scegli cartella</button><button class="button ghost" data-action="library-path">Aggiungi percorso</button></div>${(libraryData.folders||[]).map(folder=>`<div class="library-path"><span>${escapeHTML(typeof folder==='string'?folder:folder.path)}</span><button class="icon-button" data-remove-folder="${escapeHTML(typeof folder==='string'?folder:folder.path)}" aria-label="Rimuovi cartella dalla libreria">${icon('trash')}</button></div>`).join('')}`);
    if(libraryData.truncated)$('#library-content').insertAdjacentHTML('beforeend','<p class="muted">La scansione ha raggiunto il limite di file. Puoi aggiungere una cartella più specifica.</p>');hideBrokenImages($('#library-content'));
  }
  async function loadDownloads(){const data=await api('/api/downloads');const jobs=data.items||[];$('#download-jobs').innerHTML=jobs.length?`<h2>Download in coda</h2>${jobs.map(j=>`<article class="job-row"><div class="job-content"><h3>${escapeHTML(j.title)}</h3><p>${escapeHTML(j.error||({queued:'In coda',downloading:'Download in corso',completed:'Completato',cancelled:'Annullato',failed:'Non riuscito'})[j.status]||j.status)}${j.bytes?' · '+(j.bytes/1024/1024).toFixed(1)+' MB':''}</p>${j.path?`<p>${escapeHTML(j.path)}</p>`:''}<div class="job-progress"><span style="width:${Math.min(100,Math.max(0,Number(j.progress)||0))}%"></span></div></div><button class="button ghost" data-download-cancel="${escapeHTML(j.id)}" data-download-done="${['completed','failed','cancelled'].includes(j.status)}">${['completed','failed','cancelled'].includes(j.status)?'Rimuovi':'Annulla'}</button></article>`).join('')}`:'';}
  async function loadCalendar(){
    if(!$('#calendar-tabs'))$('#calendar-view .page-title').insertAdjacentHTML('afterend','<div class="kind-tabs calendar-tabs" id="calendar-tabs"><button data-calendar-tab="schedule">Calendario</button><button data-calendar-tab="search">Cerca serie</button><button data-calendar-tab="notifications">Notifiche</button></div>');
    $$('#calendar-tabs button').forEach(b=>b.setAttribute('aria-selected',String(b.dataset.calendarTab===calendarView)));
    $('#calendar-view .calendar-controls').hidden=calendarView!=='schedule';
    if(calendarView==='notifications'){renderCalendarNotifications();return;}
    if(calendarView==='search'){$('#calendar-content').innerHTML='<form id="calendar-search-form" class="home-url-form"><label class="sr-only" for="calendar-search-input">Nome della serie</label><input id="calendar-search-input" placeholder="Cerca una serie TV…" required><button class="button" type="submit">Cerca serie</button></form><div id="calendar-search-results"></div>';return;}
    const request=++catalogRequest;$('#calendar-content').innerHTML=loadingMarkup('Carico il calendario…');
    try{const data=await api(`/api/calendar?${new URLSearchParams({date:$('#calendar-date').value})}`);if(request!==catalogRequest)return;calendarItems=data.items||[];
      $('#calendar-content').innerHTML=calendarItems.length?`<div class="calendar-grid">${calendarItems.map((m,i)=>`<article class="calendar-item">${m.image?`<img src="${escapeHTML(imageURL(m.image))}" alt="" loading="lazy">`:''}<div><h3>${escapeHTML(m.title)}</h3><p>${escapeHTML(m.episode||'')}${m.season?` · S${escapeHTML(m.season)} E${escapeHTML(m.number||'')}`:''}</p><p>${escapeHTML(m.time||'')}</p><div class="calendar-item-actions"><button class="button ghost" data-search-title="${escapeHTML(m.title)}">Cerca nei canali</button>${m.show_id?`<button class="button ghost" data-follow-episode="${i}">${calendarFollows().some(s=>String(s.id)===String(m.show_id))?'Non seguire più':'Segui serie'}</button>`:''}</div></div></article>`).join('')}</div>`:emptyMarkup('calendar','Nessun episodio nel calendario per questa data','Calendario pubblico TVMaze; la disponibilità nei canali è distinta dalla messa in onda.');hideBrokenImages($('#calendar-content'));if($('#calendar-date').value===localDate())scheduleCalendarAlerts(calendarItems);
    }catch(error){if(request===catalogRequest)$('#calendar-content').innerHTML=`<div class="message error">${escapeHTML(error.message)}</div>`;}
  }
  function calendarStorageKey(suffix){return`lume.calendar.${activeProfile||'default'}.${suffix}`;}
  function calendarFollows(){try{return JSON.parse(localStorage.getItem(calendarStorageKey('follows'))||'[]');}catch{return[];}}
  function calendarNotificationsEnabled(){return localStorage.getItem(calendarStorageKey('notifications'))==='true';}
  function toggleCalendarFollow(show){const follows=calendarFollows();const index=follows.findIndex(s=>String(s.id)===String(show.id));if(index>=0)follows.splice(index,1);else follows.push({id:show.id,title:show.title});localStorage.setItem(calendarStorageKey('follows'),JSON.stringify(follows));toast(index>=0?'Serie rimossa dalle seguite':'Serie seguita');loadTodayAlerts().catch(()=>{});}
  function renderCalendarNotifications(){const supported='Notification'in window,permission=supported?Notification.permission:'unsupported',follows=calendarFollows();$('#calendar-content').innerHTML=`<div class="setting-row"><div class="setting-copy"><h2>Notifiche delle serie seguite</h2><p>Le notifiche funzionano mentre Lume è aperta, per le messe in onda del calendario pubblico di oggi. Non indicano la disponibilità del video nei canali.</p></div><div class="setting-value plain">${supported&&permission!=='denied'?`<button class="button secondary" data-action="calendar-notifications">${calendarNotificationsEnabled()?'Disattiva':'Attiva notifiche'}</button>`:`<span>${supported?'BLOCCATE DAL BROWSER':'NON SUPPORTATE'}</span>`}</div></div><h2>Serie seguite</h2>${follows.length?follows.map(s=>`<div class="library-path"><span>${escapeHTML(s.title)}</span><button class="button ghost" data-unfollow-show="${escapeHTML(s.id)}">Non seguire più</button></div>`).join(''):emptyMarkup('calendar','Non segui ancora una serie','Usa “Cerca serie” o scegli una serie dal calendario.')}`;}
  function scheduleCalendarAlerts(episodes){calendarTimers.forEach(clearTimeout);calendarTimers=[];if(!calendarNotificationsEnabled()||!('Notification'in window)||Notification.permission!=='granted')return;const follows=calendarFollows();for(const episode of episodes){if(!follows.some(s=>String(s.id)===String(episode.show_id)))continue;const delay=Date.parse(episode.airstamp||'')-Date.now();if(!Number.isFinite(delay)||delay<0||delay>24*60*60*1000)continue;calendarTimers.push(setTimeout(()=>{if(Notification.permission==='granted')new Notification(episode.title,{body:episode.episode||'È iniziato un nuovo episodio',tag:`lume-${episode.show_id}-${episode.airstamp}`});},delay));}}
  async function loadTodayAlerts(){if(!calendarNotificationsEnabled()){calendarTimers.forEach(clearTimeout);calendarTimers=[];return;}const data=await api(`/api/calendar?date=${localDate()}`);scheduleCalendarAlerts(data.items||[]);}
  async function searchCalendar(query){$('#calendar-search-results').innerHTML=loadingMarkup('Cerco la serie…');try{const data=await api(`/api/calendar/search?${new URLSearchParams({q:query})}`);calendarShows=data.items||[];$('#calendar-search-results').innerHTML=calendarShows.length?`<div class="calendar-grid">${calendarShows.map((show,i)=>`<article class="calendar-item">${show.image?`<img src="${escapeHTML(imageURL(show.image))}" alt="">`:''}<div><h3>${escapeHTML(show.title)}</h3><button class="button secondary" data-follow-show="${i}">${calendarFollows().some(s=>String(s.id)===String(show.id))?'Non seguire più':'Segui serie'}</button><button class="button ghost" data-search-title="${escapeHTML(show.title)}">Cerca nei canali</button></div></article>`).join('')}</div>`:emptyMarkup('search','Nessuna serie trovata');hideBrokenImages($('#calendar-search-results'));}catch(error){$('#calendar-search-results').innerHTML=`<div class="message error">${escapeHTML(error.message)}</div>`;}}
  function formatTime(seconds){if(!Number.isFinite(seconds))return'0:00';const s=Math.max(0,Math.floor(seconds));return(s>=3600?`${Math.floor(s/3600)}:`:'')+`${Math.floor(s/60)%60}`.padStart(s>=3600?2:1,'0')+`:${String(s%60).padStart(2,'0')}`;}
  function updatePlayerControls(){const video=$('#video');$('#video-position').textContent=formatTime(video.currentTime);$('#video-duration').textContent=formatTime(video.duration);$('#video-seek').value=video.duration>0?String(video.currentTime/video.duration*1000):'0';$('#video-play').innerHTML=video.paused?icon('play'):'<span aria-hidden="true">Ⅱ</span>';$('#video-play').setAttribute('aria-label',video.paused?'Riproduci':'Pausa');$('#video-mute').setAttribute('aria-pressed',String(video.muted));$('#video-volume').value=String(video.muted?0:video.volume);}
  function resetTrackControls(){for(const id of ['audio','subtitles','quality']){$(`#video-${id}`).innerHTML=id==='audio'?'<option value="0">Predefinita</option>':id==='quality'?'<option value="-1">Auto</option>':'<option value="-1">Disattivati</option>';$(`#video-${id}`).disabled=true;}}
  function updateTrackControls(){
    const video=$('#video'),audio=hls?.audioTracks||Array.from(video.audioTracks||[]),subs=hls?.subtitleTracks||Array.from(video.textTracks||[]),levels=hls?.levels||[];
    $('#video-audio').innerHTML=audio.length?audio.map((track,i)=>`<option value="${i}">${escapeHTML(track.name||track.label||track.lang||track.language||`Traccia ${i+1}`)}</option>`).join(''):'<option value="0">Predefinita</option>';
    $('#video-audio').disabled=audio.length<2;if(hls&&hls.audioTrack>=0)$('#video-audio').value=String(hls.audioTrack);
    $('#video-subtitles').innerHTML='<option value="-1">Disattivati</option>'+subs.map((track,i)=>`<option value="${i}">${escapeHTML(track.name||track.label||track.lang||track.language||`Traccia ${i+1}`)}</option>`).join('');$('#video-subtitles').disabled=!subs.length;
    const preferred=subs.findIndex(track=>String(track.lang||track.language||'').slice(0,2)===settings.subtitle_language);
    if(hls){if(!subtitlePreferenceApplied&&subs.length){subtitlePreferenceApplied=true;if(hls.subtitleTrack<0&&preferred>=0){hls.subtitleTrack=preferred;hls.subtitleDisplay=true;}}$('#video-subtitles').value=String(hls.subtitleTrack);}else{const showing=subs.findIndex(t=>t.mode==='showing');$('#video-subtitles').value=String(showing);}
    $('#video-quality').innerHTML='<option value="-1">Auto</option>'+levels.map((level,i)=>`<option value="${i}">${escapeHTML(level.height?`${level.height}p`:`${Math.round((level.bitrate||0)/1000)} kb/s`)}</option>`).join('');$('#video-quality').disabled=levels.length<2;if(hls)$('#video-quality').value=String(hls.autoLevelEnabled?-1:hls.currentLevel);
  }
  function nextEpisode(){if(!currentPlayback?.media.episode||!detail?.episodes?.length)return null;const current=detail.episodes.findIndex(e=>e.url===currentPlayback.media.episode.url);return current>=0?detail.episodes[current+1]||null:null;}
  async function playNextEpisode(){const episode=nextEpisode();if(!episode)return;await saveProgress();await resolveSource(episode,true);}
  async function markWatched(media){await api('/api/history',{media:mediaPayload(media),watched:true});toast('Titolo segnato come visto');}
  async function queueDownload(){if(!currentPlayback)return;const button=$('#download-source');setBusy(button,true,'Aggiungo…');try{await api('/api/downloads',{url:currentPlayback.source.url,referer:currentPlayback.referer,title:currentPlayback.media.title});toast('Download aggiunto alla coda');}catch(error){showMessage($('#player-message'),error.message,true);}finally{setBusy(button,false);}}
  function openPlayerHosts(){if(!currentPlayback||currentPlayback.source.kind==='local')return;$('#video').pause();saveProgress();playerHosts=detail?.sources?.length?detail.sources:currentPlayback.media.episode?[currentPlayback.media.episode]:[currentPlayback.source];actionDialog('Sorgenti disponibili',`<p>${playerHosts.length} ${playerHosts.length===1?'sorgente disponibile':'sorgenti disponibili'} per questo titolo.</p><div class="source-list">${playerHosts.map((source,i)=>`<button class="source-button" data-player-host="${i}">${icon('play')}<span>${escapeHTML(source.label||`Sorgente ${i+1}`)}</span>${icon('arrow')}</button>`).join('')}</div>`);}
  async function handleAction(action){
    if(action==='calendar-notifications'){if(calendarNotificationsEnabled()){localStorage.setItem(calendarStorageKey('notifications'),'false');calendarTimers.forEach(clearTimeout);calendarTimers=[];}else{if(!('Notification'in window))throw new Error('Questo browser non supporta le notifiche.');const permission=await Notification.requestPermission();if(permission!=='granted')throw new Error('Le notifiche non sono state abilitate nel browser.');localStorage.setItem(calendarStorageKey('notifications'),'true');await loadTodayAlerts();}renderCalendarNotifications();return;}
    if(action==='profile-create'||action==='profile-rename'){const renaming=action==='profile-rename',profile=profiles.find(p=>p.id===activeProfile);actionDialog(renaming?'Rinomina profilo':'Nuovo profilo locale',`<form><label>Nome<input name="name" maxlength="60" required value="${escapeHTML(renaming?profile?.name||'':'')}"></label><button class="button" type="submit">Salva</button></form>`,async form=>{await api('/api/profiles',{action:renaming?'rename':'create',...(renaming?{id:activeProfile}:{}),name:form.get('name')});await loadSettingsView();toast('Profilo salvato');});return;}
    if(action==='profile-delete'){actionDialog('Elimina profilo locale',`<form><p>Verranno eliminati i dati del profilo scelto. Il profilo attivo non può essere eliminato.</p><select name="id">${profiles.filter(p=>p.id!==activeProfile).map(p=>`<option value="${escapeHTML(p.id)}">${escapeHTML(p.name)}</option>`).join('')}</select><button class="button danger" type="submit">Elimina profilo</button></form>`,async form=>{await api('/api/profiles',{id:form.get('id')},'DELETE');await loadSettingsView();});return;}
    if(action==='detail-play'){const target=$('#detail-episode-section')||$('#detail-source-section');if(target){target.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion:reduce)').matches?'auto':'smooth',block:'start'});target.querySelector('button')?.focus();}else toast('Nessuna sorgente disponibile per questo titolo.',true);}
    else if(action==='detail-watchlist')await addToWatchlist();
    else if(action==='detail-watched')await markWatched(detail);
    else if(action==='detail-trailer'){
      const trailer=detail?.trailer;if(!trailer?.url)return;
      if(['video','hls'].includes(trailer.kind))await playResolved(trailer,{title:`${detail.title} · Trailer`,url:trailer.url,kind:'trailer'},detail.url);
      else if(trailer.kind==='embed'){const result=await api('/api/resolve',{url:trailer.url,referer:detail.url});if(!result.sources?.length)throw new Error(result.error||'Trailer non disponibile.');await playResolved(result.sources[0],{title:`${detail.title} · Trailer`,url:trailer.url,kind:'trailer'},detail.url);}
      else if(/^https?:\/\//i.test(trailer.url))window.open(trailer.url,'_blank','noopener,noreferrer');
    }
    else if(action==='export-channels')downloadJSON(await api('/api/channels/export'),'lume-canali.json');
    else if(action==='export-backup')downloadJSON(await api('/api/backup'),`lume-backup-${localDate()}.json`);
    else if(action==='import-backup')$('#backup-file').click();
    else if(action==='download-dir')actionDialog('Destinazione download',`<form><label for="download-dir">Percorso cartella sul computer</label><input id="download-dir" name="path" value="${escapeHTML(settings.download_dir||'')}" required><button class="button" type="submit">Salva cartella</button></form>`,async form=>{await saveSetting('download_dir',form.get('path'));renderSettings();});
    else if(action==='library-path')actionDialog('Aggiungi cartella alla libreria','<form><label for="folder-path">Percorso sul computer</label><input id="folder-path" name="path" placeholder="C:\\Video" required><button class="button" type="submit">Aggiungi e sincronizza</button></form>',async form=>{libraryData=await api('/api/library',{path:form.get('path')});renderLibrary();});
    else if(action==='pick-folder'){const result=await api('/api/library/pick',{});if(!result.cancelled){libraryData=result;renderLibrary();}}
  }
  async function channelDialog(kind){
    const list=kind==='list';
    actionDialog(list?'Imposta lista canali automatica':'Aggiungi canale',`<form><p>${list?'La lista verrà aggiornata automaticamente all’avvio, quando l’ultimo aggiornamento supera le 6 ore.':'Inserisci uno o più collegamenti, uno per riga.'}</p><label>${list?'Indirizzo della lista':'Indirizzi'}${list?`<input name="urls" type="url" value="${escapeHTML(state.list_url||LIST_URL)}" required>`:'<textarea name="urls" rows="5" required placeholder="https://…"></textarea>'}</label><button class="button" type="submit">${list?'Salva e aggiorna':'Inserisci'}</button></form>`,async form=>{for(const url of String(form.get('urls')).split(/\r?\n/).map(s=>s.trim()).filter(Boolean))applyState(await api('/api/channels',{url}));await reloadState();if(view==='channels')renderChannels();toast('Canali aggiornati');});
  }
  function integrationDialog(id){const service=integrations.find(s=>s.id===id);if(!service)return;actionDialog(service.name,`<form><p>${service.id==='trakt'?'Inserisci un access token OAuth già ottenuto e il client ID della tua app Trakt. Lume non usa le credenziali di Veezie.':'Inserisci il token del tuo account. Verrà verificato dal servizio e conservato cifrato sul computer.'}</p><label for="integration-token">${service.id==='trakt'?'Access token OAuth':'API token'}</label><input id="integration-token" name="token" type="password" autocomplete="new-password" required>${service.requires?.includes('client_id')?'<label for="integration-client">Client ID della tua app</label><input id="integration-client" name="client_id" type="text" autocomplete="off" required>':''}<div class="actions">${service.connected?`<button class="button danger" type="button" data-integration-disconnect="${escapeHTML(service.id)}">Scollega</button>`:''}<button class="button" type="submit">${service.connected?'Aggiorna credenziali':'Verifica e collega'}</button></div></form>`,async form=>{const data={token:String(form.get('token')||''),...(form.has('client_id')?{client_id:String(form.get('client_id'))}:{})};await api(`/api/integrations/${encodeURIComponent(id)}/connect`,data);await loadSettingsView();toast('Connessione verificata');});}
  function showGallery(index){const images=detail?.galleries||[];if(!images.length)return;galleryIndex=(index+images.length)%images.length;const image=images[galleryIndex];actionDialog(detail.title,`<img class="gallery-full" src="${escapeHTML(imageURL(typeof image==='string'?image:image.url))}" alt="Immagine ${galleryIndex+1} di ${escapeHTML(detail.title)}"><div class="actions gallery-navigation"><button class="button ghost" data-gallery="${galleryIndex-1}">Precedente</button><span>${galleryIndex+1} / ${images.length}</span><button class="button ghost" data-gallery="${galleryIndex+1}">Successiva</button></div>`);$('#action-dialog').classList.add('image-dialog');}
  document.addEventListener('click',async event => {
    const nav = event.target.closest('[data-nav]');
    if (nav) { event.preventDefault(); if($('#action-dialog').open)$('#action-dialog').close();if($('#detail-dialog').open)$('#detail-dialog').close();await navigate(nav.dataset.nav);nav.blur();$('#content').focus({preventScroll:true}); return; }
    const media = event.target.closest('[data-media]');
    if (media) {
      const selectedMedia=items[Number(media.dataset.media)];if(!selectedMedia)return;
      if(selectionMode&&media.classList.contains('collection-card')){selected.has(selectedMedia.url)?selected.delete(selectedMedia.url):selected.add(selectedMedia.url);renderCollection();return;}
      if(selectedMedia.kind==='local'||selectedMedia.url?.startsWith('/api/local/file?'))await playResolved({url:selectedMedia.url,kind:'local',label:'FILE LOCALE'},selectedMedia,'');
      else if(selectedMedia.episode){await openDetail({...selectedMedia,url:selectedMedia.series_url||selectedMedia.url,title:selectedMedia.title.split(' · ')[0]});const episode=detail.episodes?.find(e=>e.url===selectedMedia.episode.url||e.label===selectedMedia.episode.label)||selectedMedia.episode;await resolveSource(episode,true);}
      else await openDetail(selectedMedia);return;
    }
    const close = event.target.closest('[data-close]');
    if (close) { $(`#${close.dataset.close}`).close(); return; }
    const explore = event.target.closest('[data-channel]');
    if (explore) { channel = explore.dataset.channel; $('#channel-select').value = channel; await navigate('catalog'); window.scrollTo({top:0}); return; }
    const remove = event.target.closest('[data-remove]');
    if (remove) {
      remove.disabled = true;
      try { applyState(await api('/api/channels',{id:remove.dataset.remove},'DELETE')); await reloadState(); toast('Canale rimosso'); }
      catch (error) { toast(error.message,true); remove.disabled = false; }
      return;
    }
    if (event.target.closest('#favorite-button')) { await toggleFavorite(); return; }
    const source = event.target.closest('[data-source]');
    if (source) { if($('#action-dialog').open)$('#action-dialog').close();await resolveSource(detail.sources[Number(source.dataset.source)]); return; }
    const episode = event.target.closest('[data-episode]');
    if (episode) { await resolveSource(detail.episodes[Number(episode.dataset.episode)],true); return; }
    const episodeSource = event.target.closest('[data-episode-source]');
    if (episodeSource) { await resolveEpisodeSource(detail.episodeSources[Number(episodeSource.dataset.episodeSource)]); return; }
    const resolved = event.target.closest('[data-resolved]');
    if (resolved) await playResolved(detail.resolvedSources[Number(resolved.dataset.resolved)],detail.resolvedMedia,detail.resolvedReferer);
  });
  $('#search-form').addEventListener('submit',async event => {
    event.preventDefault(); query = $('#search-input').value.trim();
    await navigate('search');
  });
  $('#channel-select').addEventListener('change',async event => { channel = event.target.value; await navigate(view); });
  $('#refresh-catalog').addEventListener('click',async () => { if (view === 'search' && query) await loadSearch(); else await loadCatalog(); });
  $('#load-more').addEventListener('click',() => loadCatalog(true));
  $('#refresh-channels').addEventListener('click',refreshChannels);
  $('#list-form').addEventListener('submit',async event => {
    event.preventDefault();
    const url = $('#list-url').value.trim();
    if (url) await addChannels([url],$('#import-list'));
  });
  $('#manual-form').addEventListener('submit',async event => {
    event.preventDefault();
    const urls = [...new Set($('#manual-urls').value.split(/\r?\n/).map(url => url.trim()).filter(Boolean))];
    if (urls.length) await addChannels(urls,$('#add-channel'));
  });
  $('#detail-dialog').addEventListener('close',() => { detailRequest++; sourceRequest++; });
  $('#player-dialog').addEventListener('close',() => {
    saveProgress(); destroyVideo(); currentPlayback = null; renderGrid();
  });
  $('#video').addEventListener('pause',() => saveProgress());
  $('#mpv-button').addEventListener('click',launchMPV);
  $('#fullscreen-button').addEventListener('click',async () => {
    try { if ($('#video-frame').requestFullscreen) await $('#video-frame').requestFullscreen(); else toast('Schermo intero non disponibile in questo browser.',true); }
    catch { toast('Non è stato possibile aprire lo schermo intero.',true); }
  });
  document.addEventListener('click',async event=>{
    try{
      const hero=event.target.closest('[data-hero]');if(hero){heroIndex=Number(hero.dataset.hero);renderHero();return;}
      if(event.target.closest('#player-hosts')){openPlayerHosts();return;}
      const playerHost=event.target.closest('[data-player-host]');if(playerHost){const source=playerHosts[Number(playerHost.dataset.playerHost)];$('#action-dialog').close();await resolveSource(source,Boolean(currentPlayback?.media.episode));return;}
      const platform=event.target.closest('[data-platform]');if(platform){await navigate('discover');$('#discover-platform').value=platform.dataset.platform;await loadDiscover();return;}
      const category=event.target.closest('[data-category]');if(category){$('#discover-genre').value=category.dataset.category;await loadDiscover();return;}
      if(event.target.closest('#toggle-discover-filters')){discoverFiltersVisible=!discoverFiltersVisible;$('#discover-filters').hidden=!discoverFiltersVisible;return;}
      const tab=event.target.closest('[data-tabs] [data-kind]');if(tab){const type=tab.closest('[data-tabs]').dataset.tabs;tab.closest('[data-tabs]').querySelectorAll('button').forEach(b=>b.setAttribute('aria-selected',String(b===tab)));if(type==='discover'){discoverKind=tab.dataset.kind;await loadDiscover();}else if(type==='collection'){collectionKind=tab.dataset.kind;selected.clear();renderCollection();}else{libraryKind=tab.dataset.kind;renderLibrary();}return;}
      const action=event.target.closest('[data-action]');if(action){await handleAction(action.dataset.action);return;}
      const channelAction=event.target.closest('[data-channel-dialog]');if(channelAction){await channelDialog(channelAction.dataset.channelDialog);return;}
      const integration=event.target.closest('[data-integration]');if(integration){integrationDialog(integration.dataset.integration);return;}
      const disconnect=event.target.closest('[data-integration-disconnect]');if(disconnect){await api(`/api/integrations/${encodeURIComponent(disconnect.dataset.integrationDisconnect)}`,{},'DELETE');$('#action-dialog').close();await loadSettingsView();toast('Servizio scollegato');return;}
      const integrateSource=event.target.closest('[data-integration-resolve]');if(integrateSource){const source=detail?.sources?.[Number(integrateSource.dataset.hostIndex)];if(!source)return;const request=++sourceRequest;showMessage($('#source-feedback'),'Risolvo il collegamento con il servizio scelto…');const result=await api(`/api/integrations/${encodeURIComponent(integrateSource.dataset.integrationResolve)}/resolve`,{url:source.url});if(request!==sourceRequest)return;if(!result.sources?.length)throw new Error(result.error||'Il servizio non ha restituito un video riproducibile.');detail.resolvedSources=result.sources;detail.resolvedMedia=detail;detail.resolvedReferer=detail.url;$('#source-feedback').hidden=true;if(result.sources.length===1)await playResolved(result.sources[0],detail,detail.url);else $('#resolved-sources').innerHTML=`<div class="source-list">${sourceButtons(result.sources,true)}</div>`;return;}
      if(event.target.closest('#player-trakt')){if(!currentPlayback)return;const video=$('#video');await api('/api/integrations/trakt/scrobble',{media:currentPlayback.media,position:video.currentTime,duration:video.duration});toast('Avanzamento sincronizzato su Trakt');return;}
      const gallery=event.target.closest('[data-gallery]');if(gallery){showGallery(Number(gallery.dataset.gallery));return;}
      const calendarTab=event.target.closest('[data-calendar-tab]');if(calendarTab){calendarView=calendarTab.dataset.calendarTab;await loadCalendar();return;}
      const followShow=event.target.closest('[data-follow-show]');if(followShow){const show=calendarShows[Number(followShow.dataset.followShow)];toggleCalendarFollow(show);followShow.textContent=calendarFollows().some(s=>String(s.id)===String(show.id))?'Non seguire più':'Segui serie';return;}
      const followEpisode=event.target.closest('[data-follow-episode]');if(followEpisode){const episode=calendarItems[Number(followEpisode.dataset.followEpisode)];toggleCalendarFollow({id:episode.show_id,title:episode.title});await loadCalendar();return;}
      const unfollow=event.target.closest('[data-unfollow-show]');if(unfollow){const show=calendarFollows().find(s=>String(s.id)===unfollow.dataset.unfollowShow);if(show)toggleCalendarFollow(show);renderCalendarNotifications();return;}
      const similar=event.target.closest('[data-similar]');if(similar){const media=detail.similar[Number(similar.dataset.similar)];await openDetail(media);return;}
      const seek=event.target.closest('[data-seek]');if(seek){const video=$('#video');video.currentTime=Math.max(0,Math.min(Number.isFinite(video.duration)?video.duration:Infinity,video.currentTime+Number(seek.dataset.seek)));return;}
      const search=event.target.closest('[data-search-title]');if(search){query=search.dataset.searchTitle;$('#search-input').value=query;await navigate('search');return;}
      const cancel=event.target.closest('[data-download-cancel]');if(cancel){await api('/api/downloads',{id:cancel.dataset.downloadCancel,...(cancel.dataset.downloadDone==='true'?{clear:true}:{})},'DELETE');await loadDownloads();return;}
      const removeFolder=event.target.closest('[data-remove-folder]');if(removeFolder){libraryData=await api('/api/library',{path:removeFolder.dataset.removeFolder},'DELETE');renderLibrary();return;}
      const rename=event.target.closest('[data-list-rename]');if(rename){$('#action-dialog').close();watchlistNameDialog(true);return;}
      const deleteList=event.target.closest('[data-list-delete]');if(deleteList){const id=activeWatchlist;actionDialog('Elimina watchlist','<form><p>Vuoi eliminare questa lista? I video e le altre raccolte rimarranno disponibili.</p><button class="button danger" type="submit">Elimina lista</button></form>',async()=>{const result=await api('/api/watchlists',{id},'DELETE');watchlists=result.watchlists||[];activeWatchlist='favorites';renderCollection();});return;}
    }catch(error){toast(error.message,true);}
  });
  document.addEventListener('submit',async event=>{
    if(event.target.id==='calendar-search-form'){event.preventDefault();await searchCalendar($('#calendar-search-input').value.trim());return;}
    if(event.target.id!=='home-url-form')return;event.preventDefault();const url=$('#home-video-url').value.trim();
    try{const result=await api('/api/resolve',{url});if(!result.sources?.length)throw new Error(result.error||'Il collegamento non contiene un video riproducibile.');await playResolved(result.sources[0],{title:'Video da URL',url,kind:'video'},url);}catch(error){toast(error.message,true);}
  });
  document.addEventListener('change',async event=>{
    if(event.target.id==='menu-watchlist'){activeWatchlist=event.target.value;selectionMode=false;selected.clear();$('#action-dialog').close();renderCollection();return;}
    if(event.target.id==='profile-select'){try{await api('/api/profiles',{action:'switch',id:event.target.value});await reloadState();await loadSettingsView();calendarTimers.forEach(clearTimeout);calendarTimers=[];await loadTodayAlerts();toast('Profilo cambiato');}catch(error){toast(error.message,true);await loadSettingsView();}return;}
    if(event.target.id==='season-filter'){$$('[data-episode]').forEach(b=>b.hidden=Boolean(event.target.value&&b.dataset.season!==event.target.value));return;}
    const input=event.target.closest('[data-setting]');if(input){let value=input.value;if(['show_url','trailer_autoplay','autoplay_next'].includes(input.dataset.setting))value=value==='true';if(input.dataset.setting==='buffer_minutes')value=Number(value);try{await saveSetting(input.dataset.setting,value);toast('Impostazione salvata');}catch(error){toast(error.message,true);await loadSettingsView();}}
  });
  $('#discover-filters').addEventListener('submit',event=>{event.preventDefault();loadDiscover();});
  $('#discover-reset').addEventListener('click',()=>{$('#discover-filters').reset();loadDiscover();});
  $('#discover-more').addEventListener('click',()=>loadDiscover(true));
  $('#watchlist-select').addEventListener('change',event=>{activeWatchlist=event.target.value;selectionMode=false;selected.clear();renderCollection();});
  $('#new-watchlist').addEventListener('click',()=>watchlistNameDialog());
  $('#collection-select').addEventListener('click',()=>{selectionMode=!selectionMode;selected.clear();renderCollection();});
  $('#collection-menu').addEventListener('click',()=>actionDialog('Gestisci watchlists',`<label for="menu-watchlist">Lista</label><select id="menu-watchlist"><option value="favorites">I miei preferiti</option>${watchlists.map(l=>`<option value="${escapeHTML(l.id)}" ${l.id===activeWatchlist?'selected':''}>${escapeHTML(l.name)}</option>`).join('')}</select><div class="source-list"><button class="source-button" id="menu-new-list">Nuova lista</button>${activeWatchlist!=='favorites'?'<button class="source-button" data-list-rename>Rinomina lista</button><button class="source-button" data-list-delete>Elimina lista</button>':''}<button class="source-button" data-nav="history" data-close="action-dialog">Visti</button></div>`));
  document.addEventListener('click',event=>{if(event.target.closest('#menu-new-list')){$('#action-dialog').close();watchlistNameDialog();}});
  $('#selection-all').addEventListener('click',()=>{currentCollectionItems().forEach(m=>selected.add(m.url));renderCollection();});
  $('#selection-cancel').addEventListener('click',()=>{selectionMode=false;selected.clear();renderCollection();});
  $('#selection-remove').addEventListener('click',()=>removeSelected().catch(error=>toast(error.message,true)));
  $('#library-refresh').addEventListener('click',loadLibrary);
  $('#calendar-date').addEventListener('change',loadCalendar);
  $('#calendar-today').addEventListener('click',()=>{$('#calendar-date').value=localDate();loadCalendar();});
  $('#backup-file').addEventListener('change',async event=>{
    const file=event.target.files[0];if(!file)return;
    try{if(file.size>10*1024*1024)throw new Error('Il backup supera il limite di 10 MB.');const backup=JSON.parse(await file.text());actionDialog('Importa backup','<form><p>Il backup verrà unito ai dati attuali. Il server verifica il contenuto e conserva una copia dei dati precedenti.</p><button class="button" type="submit">Importa e unisci</button></form>',async()=>{await api('/api/backup',{backup,mode:'merge'});await reloadState();await fetchSettings();toast('Backup importato');if(view==='settings')renderSettings();});}catch(error){toast(error.message,true);}event.target.value='';
  });
  $('#video-play').addEventListener('click',()=>{const video=$('#video');if(video.paused)video.play().catch(error=>showMessage($('#player-message'),error.message,true));else video.pause();});
  $('#video-mute').addEventListener('click',()=>{const video=$('#video');video.muted=!video.muted;updatePlayerControls();});
  $('#video-volume').addEventListener('input',event=>{const video=$('#video');video.volume=Number(event.target.value);video.muted=video.volume===0;updatePlayerControls();});
  $('#video-seek').addEventListener('input',event=>{const video=$('#video');if(Number.isFinite(video.duration))video.currentTime=Number(event.target.value)/1000*video.duration;updatePlayerControls();});
  $('#video-speed').addEventListener('change',event=>{$('#video').playbackRate=Number(event.target.value);});
  $('#video-audio').addEventListener('change',event=>{if(hls)hls.audioTrack=Number(event.target.value);else Array.from($('#video').audioTracks||[]).forEach((track,i)=>track.enabled=i===Number(event.target.value));});
  $('#video-subtitles').addEventListener('change',event=>{if(hls){hls.subtitleTrack=Number(event.target.value);hls.subtitleDisplay=Number(event.target.value)>=0;}else Array.from($('#video').textTracks||[]).forEach((track,i)=>track.mode=i===Number(event.target.value)?'showing':'disabled');});
  $('#video-quality').addEventListener('change',event=>{if(hls)hls.currentLevel=Number(event.target.value);});
  for(const name of ['timeupdate','play','pause','volumechange','durationchange'])$('#video').addEventListener(name,updatePlayerControls);
  $('#video').addEventListener('ended',async()=>{if(currentPlayback&&currentPlayback.media.kind!=='trailer')try{await api('/api/history',{media:currentPlayback.media,watched:true});if(settings.autoplay_next&&nextEpisode())await playNextEpisode();}catch(error){showMessage($('#player-message'),error.message,true);}});
  $('#next-episode').addEventListener('click',()=>playNextEpisode().catch(error=>showMessage($('#player-message'),error.message,true)));
  $('#download-source').addEventListener('click',queueDownload);
  $('#player-mark-watched').addEventListener('click',()=>{if(currentPlayback)markWatched(currentPlayback.media).catch(error=>toast(error.message,true));});
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&$('#detail-dialog').open&&!$('#player-dialog').open&&!$('#action-dialog').open){$('#detail-dialog').close();event.preventDefault();return;}
    if($('#player-dialog').open&&event.key.toLowerCase()==='h'&&!event.target.closest('input,textarea,select')){event.preventDefault();openPlayerHosts();return;}
    if(!$('#player-dialog').open||event.target.closest('input,textarea,select,button'))return;
    const video=$('#video');
    if([' ','ArrowLeft','ArrowRight','ArrowUp','ArrowDown','m','M','f','F'].includes(event.key))event.preventDefault();
    if(event.key===' ')$('#video-play').click();else if(event.key==='ArrowLeft')video.currentTime=Math.max(0,video.currentTime-10);else if(event.key==='ArrowRight')video.currentTime=Math.min(Number.isFinite(video.duration)?video.duration:Infinity,video.currentTime+10);else if(event.key==='ArrowUp')video.volume=Math.min(1,video.volume+.05);else if(event.key==='ArrowDown')video.volume=Math.max(0,video.volume-.05);else if(event.key.toLowerCase()==='m')$('#video-mute').click();else if(event.key.toLowerCase()==='f')$('#fullscreen-button').click();
  });
  window.addEventListener('pagehide',() => {
    if (!currentPlayback) return;
    const video = $('#video');
    if (video.currentTime > 1 && Number.isFinite(video.duration)) {
      const progress = {url:currentPlayback.media.url,position:video.currentTime,duration:video.duration,media:currentPlayback.media,...(currentPlayback.media.episode?{episode:currentPlayback.media.episode}:{})};
      if (window.LumeCloud) window.LumeCloud.request('/api/progress',progress).catch(()=>{});
      else navigator.sendBeacon('/api/progress',new Blob([JSON.stringify(progress)],{type:'application/json'}));
    }
  });
  window.addEventListener('hashchange',() => { if (location.hash === '#home') navigate('home'); });
  window.addEventListener('resize',()=>{if(view==='settings')layoutSettingsMobile();});
  (async () => {
    try { await reloadState();
      if(window.LumeCloud && !state.channels.length && !localStorage.getItem('lume-cloud-initialized')) {
        showMessage($('#global-message'),'Preparo i canali della tua lista…');
        try {applyState(await api('/api/channels',{url:LIST_URL}));localStorage.setItem('lume-cloud-initialized','1');}
        catch(error){showMessage($('#global-message'),'La lista non si è caricata: '+error.message+'. Puoi importarla dalla sezione Canali.',true);}
        if(state.channels.length)$('#global-message').hidden=true;
      }
      await fetchSettings(); await fetchOptionalState(); await refreshStaleList(); await navigate('home'); if(calendarNotificationsEnabled())loadTodayAlerts().catch(()=>{}); }
    catch (error) {
      showMessage($('#global-message'),`${window.LumeCloud?'Il servizio online':'Il server locale'} non risponde: ${error.message}`,true);
      items = []; renderGrid(); emptyState('failed',window.LumeCloud?'Controlla la connessione e ricarica la pagina.':'Ricarica la pagina o riavvia Lume dal collegamento sul computer.');
    }
  })();
})();
