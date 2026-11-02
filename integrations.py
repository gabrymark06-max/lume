"""Connettori opzionali, attivati solo da azioni esplicite dell'utente.

Credenziali in DPAPI per l'utente Windows corrente, fuori da repository e backup.
Implementazione da documentazione ufficiale; nessun account reale usato nei test.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import threading
import time
from urllib.parse import urlsplit

import requests


DOCS = {
    'rd': 'https://api.real-debrid.com/',
    'torbox': 'https://api-docs.torbox.app/',
    'torbox_schema': 'https://api.torbox.app/openapi.json',
    'trakt': 'https://developer.trakt.tv/',
    'trakt_legacy': 'https://trakt.docs.apiary.io/reference/users/settings/retrieve-settings',
}
BASE = {'rd': 'https://api.real-debrid.com/rest/1.0', 'torbox': 'https://api.torbox.app/v1/api', 'trakt': 'https://api.trakt.tv'}
NAMES = {'rd': 'Real-Debrid', 'torbox': 'TorBox', 'trakt': 'Trakt.tv'}
LOCK = threading.RLock()


class _DataBlob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(value: bytes, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('L’archiviazione sicura dei token richiede Windows DPAPI. Nessun token salvato in chiaro.')
    source_buffer = ctypes.create_string_buffer(value)
    source = _DataBlob(len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_ubyte)))
    destination = _DataBlob()
    crypto = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    description = ctypes.c_wchar_p()
    if decrypt:
        function = crypto.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(_DataBlob), ctypes.POINTER(ctypes.c_wchar_p), ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob)]
        function.restype = wintypes.BOOL
        ok = function(ctypes.byref(source), ctypes.byref(description), None, None, None, 1, ctypes.byref(destination))
    else:
        function = crypto.CryptProtectData
        function.argtypes = [ctypes.POINTER(_DataBlob), ctypes.c_wchar_p, ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob)]
        function.restype = wintypes.BOOL
        ok = function(ctypes.byref(source), 'Lume — integrazioni personali', None, None, None, 1, ctypes.byref(destination))
    if not ok:
        raise RuntimeError('Windows non ha potuto proteggere o leggere le credenziali. Ricollega il servizio con questo utente Windows.')
    try:
        return ctypes.string_at(destination.pbData, destination.cbData)
    finally:
        if destination.pbData:
            kernel.LocalFree(ctypes.cast(destination.pbData, ctypes.c_void_p))
        if decrypt and description:
            kernel.LocalFree(ctypes.cast(description, ctypes.c_void_p))


class Integrations:
    def __init__(self, context):
        self.Error = context['Error']
        self.directory = Path(context['data_dir']).resolve()
        repo = Path(__file__).resolve().parents[2]
        if self.directory.is_relative_to(repo):
            raise self.Error('I token delle integrazioni devono essere conservati fuori dalla repository.')
        self.path = self.directory / 'integrations.dpapi'
        self.request = context.get('request') or requests.request

    def _read(self):
        if not self.path.exists():
            return {}
        try:
            value = json.loads(_dpapi(self.path.read_bytes(), decrypt=True).decode('utf-8'))
            if value.get('version') != 1 or not isinstance(value.get('services'), dict):
                raise ValueError()
            return value['services']
        except Exception:
            raise self.Error('Le credenziali protette non sono leggibili per questo utente Windows. Nessun segreto è stato esportato.') from None

    def _write(self, services):
        try:
            encrypted = _dpapi(json.dumps({'version': 1, 'services': services}, ensure_ascii=False).encode('utf-8'))
            self.directory.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix('.tmp')
            with temp.open('wb') as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        except Exception:
            raise self.Error('Salvataggio sicuro delle credenziali non riuscito. Nessun token è stato salvato in chiaro.') from None

    def _credential(self, service):
        if service not in NAMES:
            raise self.Error('Integrazione sconosciuta.')
        credential = self._read().get(service)
        if not credential:
            raise self.Error(f'Collega prima il tuo account {NAMES[service]} nelle impostazioni.')
        return credential

    def _call(self, service, method, path, credential, *, form=None, body=None, params=None):
        headers = {'Authorization': 'Bearer ' + credential['token'], 'Accept': 'application/json', 'User-Agent': 'Lume/0.2'}
        if service == 'trakt':
            headers.update({'trakt-api-key': credential['client_id'], 'trakt-api-version': '2', 'Content-Type': 'application/json'})
        response = None
        try:
            response = self.request(method, BASE[service] + path, headers=headers, data=form, json=body, params=params,
                                    timeout=(7, 20), allow_redirects=False)
            status = response.status_code
            if status in (401, 403):
                raise self.Error(f'{NAMES[service]} non ha accettato le credenziali o i permessi dell’account.')
            if status == 429:
                raise self.Error(f'{NAMES[service]} ha raggiunto il limite di richieste. Riprova più tardi.')
            if not 200 <= status < 300:
                raise self.Error(f'{NAMES[service]} non ha completato la richiesta (HTTP {status}).')
            result = response.json()
            if service == 'torbox' and (not isinstance(result, dict) or result.get('success') is not True):
                raise self.Error('TorBox non ha completato l’operazione. Controlla il servizio e il tuo piano.')
            if service == 'rd' and isinstance(result, dict) and result.get('error'):
                raise self.Error('Real-Debrid non ha potuto elaborare questo collegamento.')
            return result
        except self.Error:
            raise
        except Exception:
            # Le eccezioni HTTP possono contenere URL con API token: mai propagarle.
            raise self.Error(f'Connessione o risposta non valida da {NAMES[service]}. Nessuna credenziale mostrata nei log.') from None
        finally:
            if response is not None:
                response.close()

    def _token(self, value, name='token'):
        if not isinstance(value, str) or not 4 <= len(value) <= 4096 or re.search(r'\s|[\x00-\x1f\x7f]', value):
            raise self.Error(f'Inserisci un {name} valido, senza spazi o caratteri di controllo.')
        return value

    def _account(self, service, result, credential):
        if service == 'rd':
            if not isinstance(result, dict) or result.get('id') is None or not result.get('username'):
                raise self.Error('Real-Debrid non ha restituito un account valido.')
            name, kind = result['username'], result.get('type', '')
        elif service == 'torbox':
            data = result.get('data')
            if not isinstance(data, dict) or not any(data.get(k) for k in ('id', 'email', 'username')):
                raise self.Error('TorBox non ha restituito un account valido.')
            name, kind = data.get('username') or data.get('email') or str(data['id']), str(data.get('plan', ''))
        else:
            data = result.get('user', {}) if isinstance(result, dict) else {}
            name, kind = data.get('username') or data.get('ids', {}).get('slug'), ''
            if not name:
                raise self.Error('Trakt non ha restituito un account valido per questa applicazione.')
        def safe(value):
            text = str(value)[:200]
            for key in ('token', 'client_id'):
                if credential.get(key):
                    text = text.replace(credential[key], '[omesso]')
            return text
        return {'name': safe(name), 'type': safe(kind)}

    def status(self, service=None):
        with LOCK:
            services = self._read()
        def item(sid):
            value = services.get(sid)
            return {'id': sid, 'name': NAMES[sid], 'connected': bool(value), 'account': value.get('account') if value else None,
                    'requires': ['token', 'client_id'] if sid == 'trakt' else ['token'],
                    'verification': 'validated-on-connect' if value else 'not-configured',
                    'validated_at': value.get('validated_at') if value else None}
        return item(service) if service else {'services': [item(sid) for sid in NAMES]}

    def connect(self, service, data):
        if service not in NAMES:
            raise self.Error('Integrazione sconosciuta.')
        credential = {'token': self._token(data.get('token'))}
        if service == 'trakt':
            credential['client_id'] = self._token(data.get('client_id'), 'client_id della tua applicazione Trakt')
        endpoint = {'rd': '/user', 'torbox': '/user/me', 'trakt': '/users/settings'}[service]
        account = self._account(service, self._call(service, 'GET', endpoint, credential), credential)
        credential.update(account=account, validated_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'))
        with LOCK:
            services = self._read()
            services[service] = credential
            self._write(services)
        return {'ok': True, 'service': self.status(service)}

    def disconnect(self, service):
        if service not in NAMES:
            raise self.Error('Integrazione sconosciuta.')
        with LOCK:
            services = self._read()
            if service in services:
                del services[service]
                self._write(services)
        return {'ok': True, 'service': self.status(service)}

    def _public_source(self, url):
        if not isinstance(url, str) or len(url) > 8192:
            raise self.Error('Collegamento video non valido.')
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise self.Error('Il collegamento deve essere HTTP/HTTPS pubblico e senza credenziali.')
        try:
            if parsed.port not in (None, 80, 443):
                raise self.Error('Porta non supportata per il collegamento.')
            addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
            if any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
                raise self.Error('Gli indirizzi locali o privati non possono essere inviati al servizio.')
        except socket.gaierror:
            raise self.Error('Il dominio del collegamento non è risolvibile.') from None
        except ValueError:
            raise self.Error('Indirizzo o porta del collegamento non valido.') from None
        return url

    def _source(self, url, label, credential=None):
        self._public_source(url)
        for key in ('token', 'client_id'):
            secret = (credential or {}).get(key)
            if secret and secret in url:
                raise self.Error('Il servizio ha restituito un collegamento che espone le credenziali: non verrà inoltrato al player.')
            if secret:
                label = label.replace(secret, '[omesso]')
        return {'label': label, 'url': url, 'kind': 'hls' if urlsplit(url).path.lower().endswith('.m3u8') else 'video'}

    def resolve(self, service, url):
        """Operazione remota esplicita; non chiamata da catalogo, ricerca o avvio."""
        self._public_source(url)
        credential = self._credential(service)
        if service == 'rd':
            result = self._call('rd', 'POST', '/unrestrict/link', credential, form={'link': url})
            values = result if isinstance(result, list) else [result]
            sources = [self._source(value['download'], 'Real-Debrid · ' + str(value.get('filename') or 'Video')[:120], credential)
                       for value in values if isinstance(value, dict) and isinstance(value.get('download'), str)
                       and (str(value.get('mimeType', '')).startswith('video/') or re.search(r'\.(?:mp4|mkv|webm|m4v|mov|m3u8)$', str(value.get('filename') or urlsplit(value['download']).path), re.I))]
            if not sources:
                raise self.Error('Real-Debrid non ha restituito un collegamento video diretto.')
            return {'sources': sources}
        if service == 'torbox':
            # Solo cache: non avvia download remoti o consumi inattesi per sorgenti non disponibili.
            result = self._call('torbox', 'POST', '/webdl/createwebdownload', credential,
                                form={'link': url, 'add_only_if_cached': 'true', 'as_queued': 'false'})
            data = result.get('data') or {}
            web_id = data.get('webdownload_id') or data.get('web_id') or data.get('id') if isinstance(data, dict) else None
            if not isinstance(web_id, int) or web_id < 0:
                raise self.Error('TorBox non ha restituito un elemento web già disponibile nella cache.')
            listing = self._call('torbox', 'GET', '/webdl/mylist', credential, params={'id': web_id, 'bypass_cache': 'true'})
            records = listing.get('data')
            records = records if isinstance(records, list) else [records] if isinstance(records, dict) else []
            record = next((r for r in records if r.get('id') == web_id), None)
            if not record or not (record.get('download_finished') or record.get('download_state') in ('completed', 'cached')):
                raise self.Error('Il file TorBox non è ancora disponibile per la riproduzione. Nessun download nuovo viene avviato automaticamente.')
            sources = []
            for file in record.get('files', [])[:30]:
                if not isinstance(file, dict) or not re.search(r'\.(?:mp4|mkv|webm|m4v|mov|m3u8)$', str(file.get('name') or file.get('short_name') or ''), re.I):
                    continue
                file_id = file.get('id')
                if not isinstance(file_id, int):
                    continue
                link = self._call('torbox', 'GET', '/webdl/requestdl', credential,
                                  params={'token': credential['token'], 'web_id': web_id, 'file_id': file_id, 'redirect': 'false'})
                if isinstance(link.get('data'), str):
                    sources.append(self._source(link['data'], 'TorBox · ' + str(file.get('short_name') or file.get('name') or 'Video')[:120], credential))
            if not sources:
                raise self.Error('TorBox non ha restituito file video riproducibili per questa sorgente.')
            return {'sources': sources}
        raise self.Error('Trakt sincronizza la visione e non risolve collegamenti video.')

    def sync_trakt(self, media, position, duration):
        """Salva una pausa su Trakt solo se il chiamante la richiede esplicitamente."""
        try:
            position, duration = float(position), float(duration)
        except (TypeError, ValueError):
            raise self.Error('Avanzamento video non valido.') from None
        if not math.isfinite(position) or not math.isfinite(duration) or duration <= 0 or position < 0:
            raise self.Error('Avanzamento video non valido.')
        imdb = str(media.get('imdb') or media.get('imdb_id') or media.get('ids', {}).get('imdb') or '')
        if not re.fullmatch(r'tt\d{5,12}', imdb):
            raise self.Error('Per sincronizzare Trakt serve l’identificativo IMDb del film o dell’episodio.')
        kind = media.get('kind')
        if kind in ('series', 'tv', 'serie'):
            raise self.Error('Seleziona un episodio identificato, non l’intera serie, per la sincronizzazione Trakt.')
        item = 'episode' if kind == 'episode' else 'movie'
        body = {item: {'ids': {'imdb': imdb}}, 'progress': min(100, position / duration * 100), 'app_version': '0.2'}
        result = self._call('trakt', 'POST', '/scrobble/pause', self._credential('trakt'), body=body)
        return {'ok': True, 'action': result.get('action'), 'progress': result.get('progress')}

    def dispatch(self, method, path, data=None):
        data = data or {}
        if path == '/api/integrations' and method == 'GET':
            return self.status()
        match = re.fullmatch(r'/api/integrations/(rd|torbox|trakt)(?:/(connect|resolve|scrobble))?', path)
        if not match:
            return None
        service, action = match.groups()
        if method == 'POST' and action == 'connect':
            return self.connect(service, data)
        if method == 'DELETE' and action is None:
            return self.disconnect(service)
        if method == 'POST' and action == 'resolve':
            return self.resolve(service, data.get('url'))
        if method == 'POST' and action == 'scrobble' and service == 'trakt':
            return self.sync_trakt(data.get('media') or {}, data.get('position'), data.get('duration'))
        return None
