(() => {
  'use strict';
  if (!window.LUME_CLOUD) return;
  const storageKey = 'lume-cloud-state-v1';
  let state = {};
  try { state = JSON.parse(localStorage.getItem(storageKey) || '{}'); } catch { /* Stato iniziale vuoto. */ }
  let queue = Promise.resolve(), readyPromise;
  const auth = async () => {
    const response = await fetch('/api/session', {cache:'no-store'});
    if (!response.ok) throw new Error('Il servizio online non è disponibile. Riprova tra poco.');
    const session = await response.json();
    if (session.authenticated) return;
    await new Promise(resolve => {
      const overlay = document.createElement('dialog');
      overlay.className = 'cloud-access';
      overlay.setAttribute('aria-labelledby','cloud-title');
      overlay.innerHTML = '<form><div class="cloud-mark">L</div><p class="eyebrow">LA TUA VIDEOTECA, OVUNQUE</p><h1 id="cloud-title">Entra in Lume</h1><p>Inserisci il tuo codice privato per usare Lume su questo dispositivo.</p><label for="cloud-code">Codice di accesso</label><input id="cloud-code" type="password" autocomplete="current-password" required maxlength="100"><p id="cloud-error" role="alert" hidden></p><button class="button" type="submit">Entra</button><p class="form-note">Preferiti e avanzamento si salvano su questo dispositivo. Per trasferirli usa Esporta e Importa backup nelle impostazioni.</p></form>';
      document.body.append(overlay); overlay.showModal();
      overlay.addEventListener('cancel', e => e.preventDefault());
      overlay.querySelector('input').focus();
      overlay.querySelector('form').onsubmit = async event => {
        event.preventDefault();
        const button = overlay.querySelector('button'), error = overlay.querySelector('#cloud-error');
        button.disabled = true; error.hidden = true;
        try {
          const response = await fetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:overlay.querySelector('input').value})});
          const result = await response.json();
          if (!response.ok) throw new Error(result.error || 'Accesso non riuscito.');
          overlay.close(); overlay.remove(); resolve();
        } catch (failure) { error.textContent = failure.message; error.hidden = false; }
        finally { button.disabled = false; }
      };
    });
  };
  const ready = () => readyPromise ||= auth();
  const request = (path, data, method) => {
    const task = queue.then(async () => {
      await ready();
      const response = await fetch('/api/cloud', {
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({path,method:method || (data === undefined ? 'GET' : 'POST'),data:data || {},state})
      });
      if (response.status === 401) { readyPromise = null; await ready(); return requestRetry(path,data,method); }
      return consume(response);
    });
    queue = task.catch(() => {});
    return task;
  };
  async function requestRetry(path,data,method) {
    const response = await fetch('/api/cloud',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path,method:method || (data===undefined?'GET':'POST'),data:data || {},state})});
    return consume(response);
  }
  async function consume(response) {
    let envelope;
    try { envelope = await response.json(); } catch { throw new Error('Il servizio online ha interrotto la richiesta. Riprova.'); }
    if (!response.ok) throw new Error(envelope.result?.error || envelope.error || 'Richiesta non riuscita.');
    if (envelope.state) {
      state = envelope.state;
      try { localStorage.setItem(storageKey,JSON.stringify(state)); }
      catch { throw new Error('Memoria del dispositivo piena: esporta il backup prima di continuare.'); }
    }
    return envelope.result;
  }
  window.LumeCloud = {ready,request};
  document.documentElement.classList.add('cloud-mode');
  const footer = document.querySelector('.app-footer');
  if (footer) footer.textContent = 'Lume · La tua videoteca online. App indipendente, non affiliata a Veezie.st.';
})();
