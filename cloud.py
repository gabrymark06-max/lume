"""Adapter stateless: motore locale riusato in isolamento, media in streaming."""
from __future__ import annotations

import copy
import hashlib
import hmac
import io
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

import server as engine

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
RPC_LOCK = threading.Lock()
COOKIE = '__Host-lume'
TTL = 30 * 86400
ALLOWED = {'/api/state', '/api/health', '/api/home', '/api/discover', '/api/calendar',
           '/api/calendar/search', '/api/channels/export', '/api/catalog', '/api/search',
           '/api/detail', '/api/channels', '/api/refresh', '/api/resolve', '/api/favorite',
           '/api/progress', '/api/profiles', '/api/settings', '/api/watchlists', '/api/history',
           '/api/backup', '/api/integrations', '/api/downloads', '/api/library'}


def secret():
    return os.environ.get('LUME_ACCESS_KEY', '')


def signature(value):
    return hmac.new(secret().encode(), value.encode(), hashlib.sha256).hexdigest()


def valid_session(value):
    try:
        expires, mac = value.split('.', 1)
        return bool(secret()) and int(expires) > time.time() and int(expires) <= time.time() + TTL + 60 and hmac.compare_digest(mac, signature(expires))
    except (ValueError, AttributeError):
        return False


@app.middleware('http')
async def protect(request: Request, call_next):
    path = request.url.path
    if not secret():
        return JSONResponse({'error': 'Accesso cloud non configurato.'}, status_code=503)
    if request.method not in ('GET', 'HEAD'):
        origin = request.headers.get('origin', '')
        # Il dominio effettivo deve coincidere, anche dietro il proxy HTTPS Vercel.
        if urlsplit(origin).netloc != request.headers.get('host') or urlsplit(origin).scheme != 'https':
            if not (os.environ.get('LUME_CLOUD_DEV') == '1' and origin == str(request.base_url).rstrip('/')):
                return JSONResponse({'error': 'Origine non ammessa.'}, status_code=403)
    if path != '/api/session' and not valid_session(request.cookies.get(COOKIE, '')):
        return JSONResponse({'error': 'Inserisci il codice di accesso a Lume.'}, status_code=401)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


async def bounded_json(request, limit=2_000_000):
    if 'application/json' not in request.headers.get('content-type', ''):
        raise ValueError('Serve una richiesta JSON.')
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > limit:
            raise ValueError('Dati troppo grandi: esporta e alleggerisci la cronologia.')
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError('Richiesta non valida.')
    return result


@app.api_route('/api/session', methods=['GET', 'POST', 'DELETE'])
async def session(request: Request):
    if request.method == 'GET':
        return JSONResponse({'authenticated': valid_session(request.cookies.get(COOKIE, '')), 'mode': 'cloud', 'version': '0.3.0'})
    if request.method == 'DELETE':
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE, secure=True, httponly=True, samesite='strict')
        return response
    try:
        data = await bounded_json(request, 1024)
    except (ValueError, json.JSONDecodeError) as exc:
        return JSONResponse({'error': str(exc)}, status_code=400)
    if not hmac.compare_digest(str(data.get('code', '')), secret()):
        await __import__('asyncio').sleep(1)
        return JSONResponse({'error': 'Codice non corretto.'}, status_code=401)
    expires = str(int(time.time()) + TTL)
    response = JSONResponse({'ok': True})
    response.set_cookie(COOKIE, expires + '.' + signature(expires), max_age=TTL,
                        secure=True, httponly=True, samesite='strict', path='/')
    return response


def clean_state(value):
    if not isinstance(value, dict):
        raise ValueError('Stato non valido.')
    state = {'channels': [], 'favorites': [], 'progress': {}, 'list_url': engine.LIST_URL, 'last_refresh': None}
    for key in ('channels', 'favorites', 'history', 'watchlists', 'profiles'):
        if key in value:
            if not isinstance(value[key], list) or len(value[key]) > 2000 or any(not isinstance(item, dict) for item in value[key]):
                raise ValueError('Raccolta non valida: ' + key)
            state[key] = copy.deepcopy(value[key])
    for key in ('settings', 'progress'):
        if key in value:
            if not isinstance(value[key], dict):
                raise ValueError('Impostazioni non valide.')
            state[key] = copy.deepcopy(value[key])
    for key in ('active_profile', 'list_url', 'last_refresh'):
        if key in value:
            state[key] = copy.deepcopy(value[key])
    for channel in state['channels']:
        if not all(isinstance(channel.get(key), str) for key in ('id', 'url', 'name')):
            raise ValueError('Canale non valido.')
    if len(state['channels']) > 50:
        raise ValueError('Sono ammessi al massimo50 canali.')
    if not isinstance(state['list_url'], str):
        raise ValueError('Lista non valida.')
    state['library_paths'], state['downloads'] = [], []
    state.setdefault('settings', {})['default_player'] = 'integrated'
    return state


class Bridge(engine.Handler):
    def is_local_request(self):
        return True  # Già autenticata e verificata dal gateway; mai esposta come server HTTP.

    def json_response(self, body, status=200):
        self.result, self.status = body, status


def dispatch(envelope):
    path, method = envelope.get('path', ''), envelope.get('method', 'GET')
    if not isinstance(path, str) or urlsplit(path).path not in ALLOWED or not path.startswith('/api/') or method not in ('GET', 'POST', 'DELETE'):
        return {'error': 'Operazione cloud non disponibile.'}, 404
    route = urlsplit(path).path
    if route in ('/api/library', '/api/downloads'):
        if method == 'GET':
            return {'result': {'items': [], 'folders': [], 'downloads': [], 'jobs': []}, 'state': clean_state(envelope.get('state', {}))}, 200
        return {'error': 'Cartelle del PC e download in background sono disponibili nella versione desktop.'}, 422
    if route == '/api/integrations':
        return {'result': {'services': []}, 'state': clean_state(envelope.get('state', {}))}, 200
    state = clean_state(envelope.get('state', {}))
    payload = envelope.get('data', {})
    if not isinstance(payload, dict):
        raise ValueError('Dati non validi.')
    if route == '/api/settings':
        settings = payload.get('settings', payload)
        if isinstance(settings, dict) and 'default_player' in settings:
            settings['default_player'] = 'integrated'
    # Le vecchie API usano globali. Il lock copre l'intera operazione e il ripristino:
    # due sessioni concorrenti non possono condividere profili o progressi.
    with RPC_LOCK, tempfile.TemporaryDirectory(prefix='lume-rpc-') as directory:
        previous = {key: getattr(engine, key) for key in ('STATE', 'FEATURES', 'CATALOG_FEATURES', 'INTEGRATIONS', 'DATA', 'STATE_FILE', 'save_state')}
        try:
            engine.STATE, engine.FEATURES, engine.CATALOG_FEATURES, engine.INTEGRATIONS = state, None, None, None
            engine.DATA = Path(directory)
            engine.STATE_FILE = engine.DATA / 'state.json'
            engine.save_state = lambda: None
            bridge = Bridge.__new__(Bridge)
            body = json.dumps(payload).encode()
            bridge.path, bridge.headers = path, {'Content-Type': 'application/json', 'Content-Length': str(len(body))}
            bridge.rfile, bridge.wfile = io.BytesIO(body), io.BytesIO()
            bridge.result, bridge.status = {'error': 'Operazione non disponibile.'}, 404
            if method == 'GET':
                bridge.do_GET()
            else:
                bridge.mutate(method)
            state = copy.deepcopy(engine.STATE)
            state.pop('library_paths', None)
            state.pop('downloads', None)
            return {'result': bridge.result, 'state': state}, bridge.status
        finally:
            if engine.FEATURES is not None:
                engine.FEATURES.close()
            for key, value in previous.items():
                setattr(engine, key, value)


@app.post('/api/cloud')
async def rpc(request: Request):
    try:
        body = await bounded_json(request)
        result, status = await run_in_threadpool(dispatch, body)
        return JSONResponse(result, status_code=status)
    except (ValueError, TypeError, KeyError) as exc:
        return JSONResponse({'error': str(exc)}, status_code=422)


def remote_media(url, referer, requested_range, image):
    headers = {'Range': requested_range} if requested_range and not image else {}
    response = engine.request_url(url, referer, stream=True, extra=headers)
    ctype = response.headers.get('content-type', '').lower()
    if image and not ctype.startswith('image/'):
        response.close()
        raise engine.SourceError('Immagine non disponibile.')
    if not image and ('mpegurl' in ctype or urlsplit(response.url).path.endswith('.m3u8')):
        try:
            raw = bytearray()
            for chunk in response.iter_content(65536):
                raw.extend(chunk)
                if len(raw) > 2_000_000:
                    raise engine.SourceError('Manifest troppo grande.')
            return Response(engine.rewrite_hls(raw.decode('utf-8-sig'), response.url, referer), media_type='application/vnd.apple.mpegurl')
        finally:
            response.close()
    def chunks():
        started, size = time.monotonic(), 0
        try:
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if time.monotonic() - started > 250 or (image and size > 12_000_000):
                    break
                yield chunk
        finally:
            response.close()
    forwarded = {key: response.headers[key] for key in ('Content-Range', 'Accept-Ranges') if key in response.headers}
    return StreamingResponse(chunks(), status_code=response.status_code, media_type=ctype or 'application/octet-stream', headers=forwarded)


@app.get('/api/media')
@app.get('/api/image')
def media(request: Request, url: str, referer: str = ''):
    try:
        return remote_media(url, referer, request.headers.get('range', ''), request.url.path.endswith('image'))
    except (engine.SourceError, ValueError):
        return JSONResponse({'error': 'La sorgente non è raggiungibile dal server online.'}, status_code=422)
