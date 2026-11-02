"""Lume: cataloghi pubblici e player locale. Nessun codice remoto eseguito."""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import html
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import socket
import subprocess
import threading
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('LUME_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'Lume')))
STATE_FILE = DATA / 'state.json'
LIST_URL = 'https://www.giardiniblog.it/canali-veezie/'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36'
LOCK = threading.RLock()
CACHE = {}
MPV = []
FEATURES = None
CATALOG_FEATURES = None
INTEGRATIONS = None
HTTP_PORT = 8766


class SourceError(Exception):
    pass


def public_url(url):
    url = str(url).strip()
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        raise SourceError('Serve un indirizzo HTTP o HTTPS pubblico, senza credenziali.')
    if p.port not in (None, 80, 443):
        raise SourceError('Le sorgenti devono usare le porte HTTP/HTTPS standard.')
    try:
        addresses = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == 'https' else 80), type=socket.SOCK_STREAM)
        if any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise SourceError('Gli indirizzi di rete privata o locale non sono sorgenti ammesse.')
    except socket.gaierror as exc:
        raise SourceError('Il dominio del canale non è raggiungibile tramite DNS.') from exc
    return url


def request_url(url, referer='', stream=False, extra=None):
    headers = {'User-Agent': UA, 'Accept': '*/*'}
    if referer and urlsplit(referer).scheme in ('http', 'https'):
        headers['Referer'] = referer
        headers['Origin'] = origin(referer)
    # L'host distingue l'HTML del player dalle richieste a documenti generici.
    # Protocollo osservato nel client nativo; nessuna challenge viene eseguita.
    if (urlsplit(url).hostname or '').endswith('.vidxgo.co') and source_kind(url) == 'embed':
        headers.pop('Origin', None)
        if referer:
            headers['Referer'] = origin(referer)
        headers['Sec-Fetch-Dest'] = 'iframe'
    elif (urlsplit(referer).hostname or '').endswith('.vidxgo.co'):
        headers['Referer'] = origin(referer)
        headers.update({'Sec-Fetch-Dest': 'empty', 'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Site': 'cross-site'})
    headers.update(extra or {})
    for _ in range(7):
        public_url(url)
        try:
            r = requests.get(url, headers=headers, timeout=(7, 18), allow_redirects=False, stream=True)
        except requests.RequestException as exc:
            raise SourceError('Connessione non riuscita o scaduta per questa sorgente.') from exc
        if r.status_code in (301, 302, 303, 307, 308):
            target = r.headers.get('Location')
            r.close()
            if not target:
                raise SourceError('Reindirizzamento senza destinazione.')
            url = urljoin(url, target)
            continue
        if r.status_code >= 400:
            status = r.status_code
            r.close()
            if status in (401, 403):
                raise SourceError(f'La sorgente nega l’accesso (HTTP {status}). Nessun video riproducibile verificato.')
            raise SourceError(f'La sorgente ha risposto HTTP {status}.')
        if stream:
            return r
        chunks, size = [], 0
        try:
            for chunk in r.iter_content(65536):
                size += len(chunk)
                if size > 8 * 1024 * 1024:
                    raise SourceError('Documento troppo grande: massimo 8 MB per un catalogo.')
                chunks.append(chunk)
            content = b''.join(chunks)
            text = content.decode('utf-8', 'replace')
            if text.count('\ufffd') > 20:
                text = content.decode('windows-1252', 'replace')
            title = re.search(r'<title[^>]*>(.*?)</title>', text, re.I | re.S)
            title_text = title.group(1).lower() if title else ''
            if r.headers.get('cf-mitigated') == 'challenge' or any(t in title_text for t in ('just a moment', 'attention required', 'verify you are human')):
                raise SourceError('La sorgente richiede una verifica umana. Il controllo non viene aggirato.')
            return text, r.url, r.headers.get('Content-Type', '')
        finally:
            r.close()
    raise SourceError('Troppi reindirizzamenti della sorgente.')


def fetch(url, referer='', ttl=180):
    key = (url, referer)
    with LOCK:
        cached = CACHE.get(key)
        if cached and time.time() - cached[0] < ttl:
            return cached[1]
    value = request_url(url, referer)
    with LOCK:
        if len(CACHE) > 200:
            CACHE.clear()
        CACHE[key] = (time.time(), value)
    return value


def origin(url):
    p = urlsplit(url)
    return f'{p.scheme}://{p.netloc}'


def ident(url):
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c))


def load_state():
    if STATE_FILE.exists():
        try:
            result = json.loads(STATE_FILE.read_text(encoding='utf-8'))
            if isinstance(result, dict):
                return result
        except (ValueError, OSError):
            pass
    return {'channels': [], 'favorites': [], 'progress': {}, 'list_url': LIST_URL, 'last_refresh': None}


STATE = load_state()


def save_state():
    with LOCK:
        DATA.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix('.tmp')
        tmp.write_text(json.dumps(STATE, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, STATE_FILE)


def get_state():
    with LOCK:
        return json.loads(json.dumps(STATE))


def image_url(img, base):
    if not img:
        return ''
    raw = img.get('data-src') or img.get('data-lazy-src') or img.get('src') or ''
    return urljoin(base, raw) if raw and not raw.startswith('data:') else ''


def parse_cards(markup, base, channel):
    soup = BeautifulSoup(markup, 'html.parser')
    items, seen = [], set()
    for a in soup.select('a[href]'):
        href = urljoin(base, a.get('href', ''))
        if origin(href) != origin(base) or not re.search(r'/(?:titles/\d+|[^?#]*\d+[^/?#]*\.html|serie/[^/?#]+|film/[^/?#]+)', href):
            continue
        if '/watching' in href:
            continue
        img = next((a.select_one(sel) for sel in ('.poster-image', 'img.img-mobile', 'img.d-xl-block', 'img') if a.select_one(sel)), None)
        container = a.find_parent(class_=re.compile(r'movieItem|short|poster|item'))
        title = a.get('data-title') or a.get('aria-label') or a.get('title') or (img.get('alt') if img else '')
        if not title and container:
            title = container.get('data-title')
        if not title:
            title = a.get_text(' ', strip=True)
        title = re.sub(r'\s+(?:streaming|streaming ita)$', '', title or '', flags=re.I).strip()
        if not title or len(title) > 200 or href in seen:
            continue
        # I link di solo titolo vengono uniti alle relative immagini, senza duplicati.
        if not img and container:
            img = container.find('img')
        if not img:
            continue
        if 'logo' in str(img.get('src', '')).lower() or a.find_parent(['header', 'nav']):
            continue
        seen.add(href)
        year = a.get('data-year') or (container.get('data-year') if container else '') or ''
        kind = a.get('data-kind') or ('series' if any(x in href for x in ('serie', '/tv/')) else 'movie')
        poster = image_url(img, base).replace('/w92/', '/w342/')
        holder = a if a.get('data-title') else container
        category = (holder.get('data-category','') if holder else '')
        items.append({'id': ident(href), 'title': title, 'url': href, 'poster': poster, 'year': year,
                      'backdrop': (holder.get('data-preview','') if holder else ''),
                      'description': (holder.get('data-plot') or holder.get('data-text','') if holder else ''),
                      'genres': [g.strip() for g in re.split(r'\s{2,}|\s*/\s*|,', category) if g.strip()],
                      'rating': (holder.get('data-imdb') or holder.get('data-rate') if holder else None),
                      'imdb': (holder.get('data-imdbid','') if holder else ''),
                      'kind': kind, 'channel_id': channel['id'], 'channel_name': channel['name']})
        if holder and holder.get('data-sctrailer')=='1' and re.fullmatch(r'tt\d+',items[-1].get('imdb','')):
            items[-1]['trailer']={'url':'https://v.vidxgo.co/'+items[-1]['imdb'][2:]+'?content=trailer&player=false&info=0','label':'Trailer','kind':'embed'}
    from catalog_features import enrich_cards
    return enrich_cards(items, markup, hydration, base), soup


def get_channel(cid):
    with LOCK:
        c = next((dict(x) for x in STATE['channels'] if x['id'] == cid), None)
    if not c:
        raise SourceError('Canale non trovato. Aggiorna la lista dei canali.')
    return c


def channel_mode(channel):
    h = urlsplit(channel['url']).hostname or ''
    if 'altadefinizion' in h or 'streaming-community' in h or 'streamingcommunity' in h:
        return 'next'
    if 'guardaseriex' in h:
        return 'dle'
    if 'guardoseries' in h:
        return 'wordpress'
    return 'generic'


def catalog(channel, page=1, query=''):
    base, mode = channel['url'].rstrip('/') + '/', channel_mode(channel)
    if 'streaming-community' in channel['url']:
        return get_catalog_features().archive(channel,page,query=query)
    params = {'page': page}
    if mode == 'next':
        if query:
            params['search'] = query
        target = urljoin(base, '/archivio') + '?' + urlencode(params)
    elif mode == 'dle':
        target = urljoin(base, '/index.php') + '?' + urlencode({'do': 'search', 'subaction': 'search', 'story': query}) if query else (base if page == 1 else urljoin(base, f'/page/{page}/'))
    elif mode == 'wordpress':
        target = base + '?' + urlencode({'s': query}) if query else urljoin(base, f'/serie/page/{page}/' if page > 1 else '/serie/')
    else:
        target = base + '?' + urlencode({'s': query}) if query else base
    markup, final, _ = fetch(target)
    items, soup = parse_cards(markup, final, channel)
    if query:
        terms = normalize(query).split()
        items = [x for x in items if all(t in normalize(x['title']) for t in terms)]
    if not items and not query:
        raise SourceError('Il sito risponde, ma il formato del catalogo non è riconosciuto.')
    has_next = bool(soup.select_one('a[rel=next], .nextpostslink, a.next.page-numbers'))
    if mode == 'next' and len(items) >= 30:
        has_next = True
    return {'items': items, 'next_page': page + 1 if has_next else None}


def list_candidates(markup, url):
    if markup.lstrip().startswith(('{', '[')):
        try:
            value = json.loads(markup)
            found = []
            def collect(item):
                if isinstance(item, str) and item.startswith(('https://', 'http://')):
                    found.append(item)
                elif isinstance(item, dict):
                    for v in item.values():
                        collect(v)
                elif isinstance(item, list):
                    for v in item:
                        collect(v)
            collect(value)
            return list(dict.fromkeys(found))[:80]
        except ValueError:
            raise SourceError('La lista JSON non è valida.')
    if 'giardiniblog.it' in (urlsplit(url).hostname or ''):
        soup = BeautifulSoup(markup, 'html.parser')
        heading = next((x for x in soup.select('h2') if 'lista canali' in x.get_text(' ', strip=True).lower()), None)
        if not heading:
            raise SourceError('La sezione Lista Canali non è stata trovata nella pagina.')
        chunks = []
        for sibling in heading.next_siblings:
            if getattr(sibling, 'name', None) == 'h2':
                break
            if hasattr(sibling, 'get_text'):
                chunks.append(sibling.get_text(' ', strip=True))
        text = '\n'.join(chunks)
    else:
        text = BeautifulSoup(markup, 'html.parser').get_text('\n') if '<html' in markup[:500].lower() else markup
    urls = re.findall(r'https?://[^\s<>"\[\]{}]+', text)
    return list(dict.fromkeys(u.rstrip('.,;)') for u in urls))[:80]


def add_channel(url, from_list=False):
    public_url(url)
    text, final, ctype = fetch(url, ttl=0)
    is_list = 'giardiniblog.it' in (urlsplit(final).hostname or '') or (any(t in ctype for t in ('text/plain', 'application/json')) and not '<html' in text[:300].lower())
    if is_list and not from_list:
        candidates = list_candidates(text, final)
        if not candidates:
            raise SourceError('La pagina non contiene indirizzi di canali riconoscibili.')
        with LOCK:
            STATE['list_url'] = url
        for candidate in candidates:
            register(candidate, list_source=url)
        save_state()
        return refresh_channels()
    register(final)
    save_state()
    return refresh_channels()


def register(url, list_source=''):
    p = urlsplit(url)
    if p.scheme not in ('http', 'https') or not p.hostname:
        return
    # Il controllo rete viene eseguito prima di ogni richiesta; la lista conserva anche i canali offline.
    canonical = origin(url) + '/'
    with LOCK:
        existing = next((c for c in STATE['channels'] if c['url'].rstrip('/') == canonical.rstrip('/')), None)
        if existing:
            if list_source:
                existing['list_source'] = list_source
            return
        STATE['channels'].append({'id': ident(canonical), 'name': p.hostname.removeprefix('www.'), 'url': canonical,
                                  'status': 'pending', 'error': '', 'count': 0, 'list_source': list_source})


def refresh_channels(update_list=False):
    list_error = None
    if update_list and STATE.get('list_url'):
        try:
            markup, final, _ = fetch(STATE['list_url'], ttl=0)
            candidates = list_candidates(markup, final)
            if not candidates:
                raise SourceError('Nessun canale trovato: la lista precedente è stata conservata.')
            for u in candidates:
                register(u, list_source=STATE['list_url'])
            # I canali spariti dalla lista non vengono eliminati, ma segnalati.
            active = {origin(u) + '/' for u in candidates}
            with LOCK:
                for c in STATE['channels']:
                    if c.get('list_source') == STATE['list_url']:
                        c['in_current_list'] = c['url'] in active
        except SourceError as exc:
            list_error = str(exc)
    channels = get_state()['channels']
    def inspect(c):
        try:
            result = catalog(c)
            return c['id'], 'ready', '', len(result['items'])
        except SourceError as exc:
            return c['id'], 'error', str(exc), 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(inspect, channels))
    with LOCK:
        for cid, status, error, count in results:
            c = next((x for x in STATE['channels'] if x['id'] == cid), None)
            if c:
                c.update(status=status, error=error, count=count)
        STATE['last_refresh'] = time.strftime('%Y-%m-%dT%H:%M:%S%z')
        STATE['list_error'] = list_error
        save_state()
    return get_state()


def hydration(markup):
    parts = []
    for m in re.finditer(r'self\.__next_f\.push\(\[1,("(?:\\.|[^"\\])*")\]\)', markup):
        try:
            parts.append(json.loads(m.group(1)))
        except ValueError:
            continue
    return ''.join(parts)


def js_property(text, key):
    m = re.search(r'"' + re.escape(key) + r'"\s*:', text)
    if m:
        try:
            return json.JSONDecoder().raw_decode(text[m.end():].lstrip())[0]
        except ValueError:
            pass
    return None


def source_kind(url):
    path = urlsplit(url).path.lower()
    return 'hls' if path.endswith('.m3u8') else 'video' if path.endswith(('.mp4', '.webm', '.mkv', '.m4v', '.mov')) else 'embed'


def rewrite_hls(text, base_url, referer=''):
    def proxied(target):
        return '/api/media?' + urlencode({'url': urljoin(base_url, target), 'referer': referer})
    lines = []
    for line in text.splitlines():
        if line and not line.startswith('#'):
            line = proxied(line)
        elif 'URI="' in line:
            line = re.sub(r'URI="([^"]+)"', lambda m: 'URI="' + proxied(m.group(1)) + '"', line)
        lines.append(line)
    return '\n'.join(lines) + '\n'


def extract_sources(markup, base):
    soup = BeautifulSoup(markup, 'html.parser')
    sources = []
    for node in soup.select('iframe[src], video[src], source[src], [data-link], [data-url]'):
        raw = node.get('src') or node.get('data-link') or node.get('data-url') or ''
        if not raw or raw.startswith(('javascript:', 'data:', '#')):
            continue
        u = urljoin(base, html.unescape(raw))
        if urlsplit(u).scheme not in ('http', 'https') or any(x in u.lower() for x in ('trailer', 'youtube.com', 'youtu.be', 'doubleclick', 'googlesyndication')):
            continue
        if node.name not in ('iframe', 'video', 'source') and not any(x in u.lower() for x in ('embed', 'player', 'vidx', 'vixsrc', '.m3u8', '.mp4', 'mixdrop', 'supervideo')):
            continue
        label = node.get('title') or node.get_text(' ', strip=True)[:60] or urlsplit(u).hostname
        sources.append({'label': label, 'url': u, 'kind': source_kind(u)})
    # Legge assegnazioni letterali; non usa eval e non esegue script di host.
    for m in re.finditer(r'(?:\bfile|\bsource|\bvideoUrl|\bplaylistUrl)\s*[:=]\s*[\x22\x27](https?[^\x22\x27\s]+)', markup):
        u = html.unescape(m.group(1).replace('\\/', '/'))
        if source_kind(u) != 'embed':
            sources.append({'label': 'Video', 'url': u, 'kind': source_kind(u)})
    return list({s['url']: s for s in sources}.values())


def parse_vidxgo(markup):
    """Legge i literal del player offuscati con XOR; non valuta codice JS."""
    results = []
    pattern = r'var\s+[A-Za-z_$][\w$]*\s*=\s*([\x22\x27])([^\x22\x27]+)\1\s*,\s*d\s*=\s*atob\(\s*([\x22\x27])([A-Za-z0-9+/=]+)\3\s*\)'
    for m in re.finditer(pattern, markup):
        key = m.group(2).encode('latin-1', 'replace')
        try:
            raw = base64.b64decode(m.group(4), validate=True)
        except ValueError:
            continue
        if not key or len(raw) > 2 * 1024 * 1024:
            continue
        decoded = bytes(v ^ key[i % len(key)] for i, v in enumerate(raw)).decode('utf-8', 'replace')
        decoded = decoded.replace('\\/', '/')
        for match in re.finditer(r'[\x22\x27](https?://[^\x22\x27\s<>]+\.m3u8[^\x22\x27\s<>]*)[\x22\x27]', decoded):
            link = html.unescape(match.group(1))
            results.append({'label': 'Player integrato · HLS', 'url': link, 'kind': 'hls',
                            'headers': {'Referer': 'https://v.vidxgo.co'}})
    return list({x['url']: x for x in results}.values())


def detail(url, channel):
    if origin(url) != origin(channel['url']):
        # Il sito può avere aggiornato il dominio; un catalogo già aperto mantiene la propria origine.
        public_url(url)
    markup, final, _ = fetch(url)
    soup = BeautifulSoup(markup, 'html.parser')
    og = lambda prop: (soup.find('meta', property=prop) or {}).get('content', '')
    h1 = soup.find('h1')
    title = (h1.get_text(' ', strip=True) if h1 else '') or og('og:title') or (soup.title.text if soup.title else 'Titolo')
    if h1 and not h1.get_text(' ', strip=True) and h1.find('img'):
        title = h1.find('img').get('alt') or title
    description = og('og:description') or (soup.find('meta', attrs={'name': 'description'}) or {}).get('content', '')
    sources = extract_sources(markup, final)
    for a in soup.select('a[href]'):
        if a['href'].endswith('/watching'):
            sources.append({'label': 'Player del canale', 'url': urljoin(final, a['href']), 'kind': 'embed'})
            break
    data = hydration(markup)
    seasons = js_property(data, 'seasons') or []
    episodes = []
    imdb = js_property(data, 'imdbId') or js_property(data, 'imdb_id')
    if not imdb:
        match = re.search(r"\bimdb\s*=\s*['\x22](tt\d+)['\x22]", markup)
        imdb = match.group(1) if match else None
    player_url = next((s['url'] for s in sources if 'vidxgo' in s['url']), '')
    if not player_url and imdb:
        player_url = 'https://v.vidxgo.co/' + imdb.removeprefix('tt')
    if isinstance(seasons, list) and player_url:
        stem = re.sub(r'/\d+/\d+/?$', '', urlsplit(player_url).path)
        for season in seasons:
            if not isinstance(season, dict):
                continue
            sn = season.get('number') or season.get('season_number')
            for ep in season.get('episodes', []):
                en = ep.get('number') or ep.get('episode_number')
                if sn and en:
                    episodes.append({'label': f'S{sn} · E{en} — {ep.get("title") or ep.get("name") or "Episodio"}',
                                     'url': origin(player_url) + stem + f'/{sn}/{en}?se=0&info=0', 'kind': 'embed'})
    if not episodes and player_url:
        for node in soup.select('[data-episode]'):
            value = node['data-episode']
            if re.fullmatch(r'\d+-\d+', value):
                sn, en = value.split('-')
                stem = re.sub(r'/\d+/\d+/?$', '', urlsplit(player_url).path)
                episodes.append({'label': f'S{sn} · E{en}', 'url': origin(player_url) + stem + f'/{sn}/{en}?se=0', 'kind': 'embed'})
    if not sources and player_url:
        sources.append({'label': 'Player indicato dal canale', 'url': player_url, 'kind': 'embed'})
    result = {'title': title, 'url': final, 'poster': og('og:image'), 'description': description, 'year': '',
              'sources': list({s['url']: s for s in sources}.values()), 'episodes': episodes}
    return get_catalog_features().enrich_detail(result, markup, final, channel)


def resolve(url, referer='', depth=0, visited=None):
    public_url(url)
    if source_kind(url) != 'embed':
        # Verifica una piccola porzione senza scaricare l'intero film.
        r = request_url(url, referer, stream=True, extra={'Range': 'bytes=0-1023'})
        r.close()
        return [{'label': 'Video diretto', 'url': url, 'kind': source_kind(url), 'headers': {'Referer': referer}}]
    if depth > 3:
        raise SourceError('Il collegamento richiede ulteriori passaggi non supportati.')
    visited = visited or set()
    if url in visited:
        raise SourceError('La sorgente rimanda a un collegamento già visitato.')
    visited.add(url)
    markup, final, ctype = fetch(url, referer, ttl=30)
    if 'mpegurl' in ctype or markup.lstrip().startswith('#EXTM3U'):
        return [{'label': 'Stream HLS', 'url': final, 'kind': 'hls', 'headers': {'Referer': referer}}]
    if (urlsplit(final).hostname or '').endswith('.vidxgo.co'):
        parsed = parse_vidxgo(markup)
        if parsed:
            return parsed
    found = extract_sources(markup, final)
    direct = [s for s in found if s['kind'] in ('hls', 'video')]
    if direct:
        for s in direct:
            s['headers'] = {'Referer': final}
        return direct
    errors = []
    for s in found[:5]:
        try:
            return resolve(s['url'], final, depth + 1, visited)
        except SourceError as exc:
            errors.append(str(exc))
    if errors:
        raise SourceError(errors[0])
    raise SourceError('Nessun flusso video diretto rilevato. Questo host richiede un adapter dedicato o nega l’accesso; nessun controllo viene aggirato.')


def get_features():
    global FEATURES
    with LOCK:
        if FEATURES is None:
            from features import Features
            FEATURES = Features({'state':STATE,'lock':LOCK,'save':save_state,'request':request_url,'resolve':resolve,
                                 'root':ROOT,'data_dir':DATA,'SourceError':SourceError,
                                 'media_proxy':lambda u,r:'http://127.0.0.1:'+str(HTTP_PORT)+'/api/media?'+urlencode({'url':u,'referer':r})})
    return FEATURES


def get_catalog_features():
    global CATALOG_FEATURES
    with LOCK:
        if CATALOG_FEATURES is None:
            from catalog_features import CatalogFeatures
            CATALOG_FEATURES = CatalogFeatures({'state':get_state,'normalize':normalize,'fetch':fetch,'parse_cards':parse_cards,
                                                'hydration':hydration,'channel_mode':channel_mode,'catalog':catalog})
    return CATALOG_FEATURES


def get_integrations():
    global INTEGRATIONS
    with LOCK:
        if INTEGRATIONS is None:
            from integrations import Integrations
            INTEGRATIONS = Integrations({'data_dir':DATA,'Error':SourceError})
    return INTEGRATIONS


class AppServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    server_version = 'Lume/0.1'

    def log_message(self, fmt, *args):
        # Non registra URL di stream o token temporanei nei log.
        pass

    def json_response(self, body, status=200):
        raw = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def is_local_request(self):
        expected = f'127.0.0.1:{self.server.server_port}'
        return self.headers.get('Host') == expected and self.headers.get('Origin', 'http://' + expected) == 'http://' + expected

    def do_GET(self):
        if not self.is_local_request():
            self.json_response({'error': 'Origine della richiesta non ammessa.'}, 403)
            return
        p = urlsplit(self.path)
        args = {k: v[0] for k, v in parse_qs(p.query).items()}
        try:
            extra = get_features().dispatch('GET', p.path, args)
            if extra is None and p.path.startswith('/api/integrations'):
                extra = get_integrations().dispatch('GET',p.path,args)
            if extra is not None:
                self.json_response(extra)
                return
            if p.path == '/api/health':
                self.json_response({'app': 'lume', 'version': '0.2.0'})
            elif p.path == '/api/state':
                self.json_response(get_state())
            elif p.path == '/api/home':
                self.json_response(get_catalog_features().home())
            elif p.path == '/api/discover':
                self.json_response(get_catalog_features().discover(args))
            elif p.path == '/api/calendar':
                self.json_response(get_catalog_features().calendar(args.get('date')))
            elif p.path == '/api/calendar/search':
                self.json_response(get_catalog_features().calendar_search(args.get('q','')))
            elif p.path == '/api/channels/export':
                self.json_response({'channels': {c['name']:c['url'] for c in get_state()['channels']}})
            elif p.path == '/api/local/file':
                self.local_file(args.get('id',''))
            elif p.path == '/api/catalog':
                self.json_response(catalog(get_channel(args.get('channel')), max(1, min(500, int(args.get('page', 1))))))
            elif p.path == '/api/search':
                q = args.get('q', '').strip()[:150]
                if len(q) < 2:
                    raise SourceError('Scrivi almeno due caratteri per cercare.')
                channels = [get_channel(args['channel'])] if args.get('channel') else get_state()['channels']
                def search(c):
                    try:
                        return catalog(c, query=q)['items'], None
                    except SourceError as exc:
                        return [], {'name': c['name'], 'error': str(exc)}
                with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
                    results = list(pool.map(search, channels))
                self.json_response({'items': [m for ms, _ in results for m in ms], 'errors': [e for _, e in results if e]})
            elif p.path == '/api/detail':
                self.json_response(detail(args['url'], get_channel(args['channel'])))
            elif p.path in ('/api/media', '/api/image'):
                self.proxy(args, image=p.path.endswith('image'))
            else:
                self.static(p.path)
        except (SourceError, KeyError, ValueError) as exc:
            self.json_response({'error': str(exc)}, 422)
        except (BrokenPipeError, ConnectionError):
            pass
        except Exception:
            self.json_response({'error': 'Errore locale durante la lettura della sorgente.'}, 500)

    def do_POST(self):
        self.mutate('POST')

    def do_DELETE(self):
        self.mutate('DELETE')

    def mutate(self, method):
        if not self.is_local_request() or not self.headers.get('Content-Type', '').startswith('application/json'):
            # Windows può resettare un socket chiuso con body HTTP ancora in lettura.
            # Svuotare solo richieste piccole e con lunghezza esplicita prima del403.
            try:
                rejected_length = int(self.headers.get('Content-Length','0'))
                if 0<=rejected_length<=100000:
                    self.connection.settimeout(5)
                    self.rfile.read(rejected_length)
            except (ValueError,OSError):
                pass
            self.close_connection = True
            self.json_response({'error': 'Richiesta non ammessa.'}, 403)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length > (10*1024*1024 if urlsplit(self.path).path=='/api/backup' else 100000):
                raise SourceError('Richiesta troppo grande.')
            data = json.loads(self.rfile.read(length) or '{}')
            path = urlsplit(self.path).path
            extra = get_features().dispatch(method,path,data)
            if extra is None and path.startswith('/api/integrations'):
                extra = get_integrations().dispatch(method,path,data)
            if extra is not None:
                self.json_response(extra)
                return
            if path == '/api/channels' and method == 'POST':
                result = add_channel(data['url'])
            elif path == '/api/channels' and method == 'DELETE':
                with LOCK:
                    STATE['channels'] = [c for c in STATE['channels'] if c['id'] != data['id']]
                    save_state()
                result = get_state()
            elif path == '/api/refresh':
                with LOCK:
                    CACHE.clear()
                result = refresh_channels(update_list=True)
            elif path == '/api/resolve':
                result = {'sources': resolve(data['url'], data.get('referer', ''))}
            elif path == '/api/favorite':
                media = data['media']
                if not isinstance(media, dict) or not media.get('url'):
                    raise SourceError('Titolo non valido.')
                with LOCK:
                    STATE['favorites'] = [x for x in STATE['favorites'] if x['url'] != media['url']]
                    if data.get('enabled'):
                        STATE['favorites'].append({k: media.get(k, '') for k in ('id','title','url','poster','year','kind','channel_id','channel_name')})
                    save_state()
                result = get_state()
            elif path == '/api/progress':
                pos, dur = float(data.get('position', 0)), float(data.get('duration', 0))
                if not (0 <= pos <= 1e8 and 0 <= dur <= 1e8):
                    raise SourceError('Avanzamento non valido.')
                with LOCK:
                    STATE['progress'][data['url']] = {'position': pos, 'duration': dur}
                    media = data.get('media')
                    if isinstance(media,dict) and media.get('title'):
                        safe = {k:media.get(k,'') for k in ('id','title','url','poster','backdrop','year','kind','channel_id','channel_name','series_url')}
                        ep = media.get('episode') or data.get('episode')
                        if isinstance(ep,dict):
                            safe['episode'] = {k:ep.get(k,'') for k in ('url','label','kind')}
                        safe['url'] = data['url']
                        STATE['history'] = [x for x in STATE.get('history',[]) if x.get('media',x).get('url')!=data['url']]
                        STATE['history'].insert(0,{'media':safe,'watched_at':time.time(),'watched':bool(dur and pos/dur>=.95)})
                        STATE['history'] = STATE['history'][:1000]
                    save_state()
                result = {'ok': True}
            elif path == '/api/library/pick':
                picker = "[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); $app=New-Object -ComObject Shell.Application; $folder=$app.BrowseForFolder(0,'Scegli la cartella dei video per Lume',0,0); if($folder){$folder.Self.Path}"
                chosen = subprocess.run(['powershell.exe','-NoProfile','-STA','-Command',picker],capture_output=True,text=True,encoding='utf-8',timeout=180,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)).stdout.strip()
                result = get_features().dispatch('POST','/api/library',{'path':chosen}) if chosen else {'cancelled':True}
            elif path == '/api/mpv':
                public_url(data['url'])
                if source_kind(data['url']) == 'embed':
                    raise SourceError('Seleziona prima un flusso video risolto, non una pagina web.')
                candidates = [ROOT / 'bin/mpv.exe', Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Veezie.st/resources/bin/mpv.exe']
                executable = next((str(x) for x in candidates if x.is_file()), None)
                if not executable:
                    raise SourceError('MPV non è installato. Il player interno resta disponibile per MP4/HLS compatibili.')
                args = [executable, '--no-config', '--no-terminal', '--force-window=yes', '--title=Lume', '--user-agent=' + UA]
                if data.get('referer'):
                    args.append('--referrer=' + data['referer'])
                    if (urlsplit(data['referer']).hostname or '').endswith('.vidxgo.co'):
                        args.append('--http-header-fields=Sec-Fetch-Dest: empty,Sec-Fetch-Mode: cors,Sec-Fetch-Site: cross-site')
                MPV[:] = [p for p in MPV if p.poll() is None]
                MPV.append(subprocess.Popen(args + ['--', data['url']], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)))
                result = {'ok': True}
            else:
                self.json_response({'error': 'Operazione sconosciuta.'}, 404)
                return
            self.json_response(result)
        except (SourceError, KeyError, ValueError, TypeError) as exc:
            self.json_response({'error': str(exc)}, 422)
        except (BrokenPipeError, ConnectionError):
            pass
        except Exception:
            self.json_response({'error': 'Operazione non riuscita.'}, 500)

    def static(self, path):
        path = path if path != '/' else '/index.html'
        f = (ROOT / 'web' / path.lstrip('/')).resolve()
        if not f.is_relative_to((ROOT / 'web').resolve()) or not f.is_file():
            self.send_error(404)
            return
        raw = f.read_bytes()
        self.send_response(200)
        ctype = mimetypes.guess_type(str(f))[0] or 'application/octet-stream'
        self.send_header('Content-Type', ctype + ('; charset=utf-8' if ctype.startswith(('text/', 'application/javascript')) else ''))
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; worker-src 'self' blob:; frame-src 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(raw)

    def local_file(self, file_id):
        path = get_features().lookup_local(file_id)
        if path is None or not path.is_file():
            raise SourceError('File locale non trovato. Rileggi la cartella della libreria.')
        size = path.stat().st_size
        start,end,status = 0,max(0,size-1),200
        requested = self.headers.get('Range','')
        if requested:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)',requested)
            if not match or not any(match.groups()):
                self.send_error(416); return
            if match.group(1):
                start = int(match.group(1)); end = min(size-1,int(match.group(2))) if match.group(2) else size-1
            else:
                start = max(0,size-int(match.group(2)))
            if start>=size or end<start:
                self.send_response(416); self.send_header('Content-Range',f'bytes */{size}'); self.end_headers(); return
            status = 206
        self.send_response(status)
        self.send_header('Content-Type',mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
        self.send_header('Accept-Ranges','bytes')
        self.send_header('Content-Length',str(end-start+1 if size else 0))
        if status==206:
            self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        with path.open('rb') as stream:
            stream.seek(start); remaining=end-start+1 if size else 0
            while remaining>0:
                chunk=stream.read(min(65536,remaining))
                if not chunk:break
                self.wfile.write(chunk); remaining-=len(chunk)

    def proxy(self, args, image=False):
        url = args['url']
        headers = {}
        if self.headers.get('Range') and not image:
            headers['Range'] = self.headers['Range']
        r = request_url(url, args.get('referer', ''), stream=True, extra=headers)
        ctype = r.headers.get('Content-Type', '').lower()
        is_hls = not image and ('mpegurl' in ctype or urlsplit(r.url).path.endswith('.m3u8'))
        try:
            if image and not ctype.startswith('image/'):
                raise SourceError('La sorgente non è un’immagine.')
            if is_hls:
                raw = bytearray()
                for chunk in r.iter_content(65536):
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 * 1024:
                        raise SourceError('Manifest HLS troppo grande.')
                text = raw.decode('utf-8-sig')
                data = rewrite_hls(text, r.url, args.get('referer', '')).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/vnd.apple.mpegurl')
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)
                return
            self.send_response(r.status_code)
            self.send_header('Content-Type', r.headers.get('Content-Type', 'application/octet-stream'))
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Cache-Control', 'private, max-age=600' if image else 'no-store')
            # requests decodifica content-encoding: non inoltrare una lunghezza compressa.
            for name in ('Content-Range', 'Accept-Ranges'):
                if r.headers.get(name):
                    self.send_header(name, r.headers[name])
            self.end_headers()
            size = 0
            for chunk in r.iter_content(65536):
                size += len(chunk)
                if image and size > 12 * 1024 * 1024:
                    break
                self.wfile.write(chunk)
        finally:
            r.close()


def main():
    global HTTP_PORT
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--import-list', action='store_true')
    parser.add_argument('--open', action='store_true')
    options = parser.parse_args()
    if options.import_list:
        try:
            add_channel(LIST_URL)
        except SourceError:
            pass
    server = AppServer(('127.0.0.1', options.port), Handler)
    HTTP_PORT = server.server_port
    address = f'http://127.0.0.1:{server.server_port}/'
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / 'running.json').write_text(json.dumps({'pid': os.getpid(), 'url': address}), encoding='utf-8')
    print(address, flush=True)
    if options.open:
        edge = Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe'
        if edge.exists():
            subprocess.Popen([str(edge), '--app=' + address, '--user-data-dir=' + str(DATA / 'browser')], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        else:
            import webbrowser
            webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if FEATURES is not None:
            FEATURES.close()
        server.server_close()


if __name__ == '__main__':
    main()
