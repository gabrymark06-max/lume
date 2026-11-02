"""Funzioni locali di Lume: impostazioni, raccolte, backup, download e libreria.

Il modulo riceve le dipendenze dal server e non importa il suo stato globale.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


VIDEO_EXTENSIONS = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.m4v', '.mpeg', '.mpg', '.ts'}
MEDIA_FIELDS = ('id', 'title', 'url', 'poster', 'year', 'kind', 'channel_id', 'channel_name')
PROFILE_FIELDS = ('favorites', 'progress', 'history', 'watchlists', 'settings')
SECRET_KEY = re.compile(r'(?:^|_)(?:token|password|secret|cookie|authorization|api_key|id_token)(?:$|_)', re.I)
SECRET_QUERY = re.compile(r'^(?:token|access_token|id_token|api_key|key|password|secret|signature|sig|authorization)$', re.I)


def _identifier(value):
    return hashlib.sha256(str(value).encode('utf-8')).hexdigest()[:20]


def _safe_url(value, *, local=False):
    if not isinstance(value, str) or len(value) > 8192:
        raise ValueError('Indirizzo non valido.')
    if local and value.startswith('/api/local/file?id='):
        return value
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('Serve un indirizzo HTTP o HTTPS senza credenziali.')
    return value


def _filename(value):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(value)).strip(' .')[:140]
    if not text:
        text = 'video'
    if text.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *('COM' + str(i) for i in range(1, 10)), *('LPT' + str(i) for i in range(1, 10))}:
        text = '_' + text
    return text


def _media(value):
    if not isinstance(value, dict):
        raise ValueError('Il titolo deve essere un oggetto.')
    url = _safe_url(value.get('url', ''), local=True)
    title = value.get('title', '')
    if not isinstance(title, str) or not title.strip() or len(title) > 500:
        raise ValueError('Il titolo deve avere un nome valido.')
    result = {key: str(value.get(key, ''))[:8192] for key in MEDIA_FIELDS}
    result.update(url=url, title=title.strip(), id=str(value.get('id') or _identifier(url)))
    if value.get('series_url'):
        result['series_url'] = _safe_url(value['series_url'], local=True)
    if isinstance(value.get('episode'), dict):
        episode = value['episode']
        result['episode'] = {'url': _safe_url(episode.get('url', ''), local=True),
                             'label': str(episode.get('label', 'Episodio'))[:300],
                             'kind': str(episode.get('kind', 'embed'))[:30]}
        for key in ('season', 'number'):
            if episode.get(key) is not None:
                number = int(episode[key])
                if not 0 <= number <= 10000:
                    raise ValueError('Numero episodio non valido.')
                result['episode'][key] = number
    return result


def _redact(value):
    if isinstance(value, dict):
        return {(_redact(key) if isinstance(key, str) else key): _redact(item) for key, item in value.items() if not SECRET_KEY.search(str(key))}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str) and value.startswith(('http://', 'https://')):
        p = urlsplit(value)
        if p.username or p.password:
            host = p.hostname or ''
            if p.port:
                host += ':' + str(p.port)
        else:
            host = p.netloc
        query = urlencode([(key, val) for key, val in parse_qsl(p.query, keep_blank_values=True) if not SECRET_QUERY.match(key)])
        return urlunsplit((p.scheme, host, p.path, query, ''))
    return value


class Features:
    def __init__(self, context):
        self.context = context
        self.state = context['state']
        self.lock = context['lock']
        self.save = context['save']
        self.request = context['request']
        self.resolve = context['resolve']
        self.root = Path(context['root'])
        self.data_dir = Path(context['data_dir'])
        self.Error = context.get('SourceError', ValueError)
        self.jobs = {}
        self.job_lock = threading.RLock()
        self.download_semaphore = threading.Semaphore(2)
        self.local_files = {}
        self.library_items = []
        self.closed = threading.Event()
        with self.lock:
            self.state.setdefault('settings', {})
            self.state.setdefault('watchlists', [])
            self.state.setdefault('history', [])
            self.state.setdefault('library_paths', [])
            self.state.setdefault('downloads', [])
            self._initialize_profiles()
        self._restore_downloads()

    def _profile_snapshot(self):
        return {key: copy.deepcopy(self.state.get(key, {} if key in ('progress', 'settings') else [])) for key in PROFILE_FIELDS}

    def _initialize_profiles(self):
        profiles = self.state.get('profiles')
        if not isinstance(profiles, list) or not profiles:
            profile_id = uuid.uuid4().hex
            self.state['profiles'] = [{'id': profile_id, 'name': 'Principale', 'data': self._profile_snapshot()}]
            self.state['active_profile'] = profile_id
        elif not any(p.get('id') == self.state.get('active_profile') for p in profiles):
            # Se uno stato precedente manca dell'id attivo, i dati top-level restano autorevoli.
            self.state['active_profile'] = profiles[0]['id']
            profiles[0]['data'] = self._profile_snapshot()

    def _profiles(self):
        with self.lock:
            return {'profiles': [{'id': item['id'], 'name': item['name']} for item in self.state['profiles']],
                    'active_profile': self.state['active_profile']}

    def _change_profiles(self, method, data):
        with self.lock:
            before = copy.deepcopy(self.state)
            profiles = self.state['profiles']
            profile_id = data.get('id')
            target = next((p for p in profiles if p['id'] == profile_id), None)
            action = 'delete' if method == 'DELETE' else data.get('action')
            if action in ('create', 'rename'):
                name = data.get('name', '')
                if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
                    raise self.Error('Il nome del profilo deve avere da 1 a 80 caratteri.')
                name = name.strip()
                if any(p['name'].casefold() == name.casefold() and (action != 'rename' or p is not target) for p in profiles):
                    raise self.Error('Esiste già un profilo con questo nome.')
            if action == 'create':
                profiles.append({'id': uuid.uuid4().hex, 'name': name,
                                 'data': {key: {} if key in ('progress', 'settings') else [] for key in PROFILE_FIELDS}})
            elif action == 'rename':
                if not target:
                    raise self.Error('Profilo non trovato.')
                target['name'] = name
            elif action == 'switch':
                if not target:
                    raise self.Error('Profilo non trovato.')
                if target['id'] == self.state['active_profile']:
                    return self._profiles()
                current = next(p for p in profiles if p['id'] == self.state['active_profile'])
                current['data'] = self._profile_snapshot()
                for key in PROFILE_FIELDS:
                    self.state[key] = copy.deepcopy(target.get('data', {}).get(key, {} if key in ('progress', 'settings') else []))
                self.state['active_profile'] = target['id']
            elif action == 'delete':
                if not target:
                    raise self.Error('Profilo non trovato.')
                if len(profiles) <= 1 or target['id'] == self.state['active_profile']:
                    raise self.Error('Non puoi eliminare il profilo attivo o l’ultimo profilo.')
                profiles.remove(target)
            else:
                raise self.Error('Operazione profilo non valida.')
            try:
                self.save()
            except Exception:
                self.state.clear()
                self.state.update(before)
                raise
            return self._profiles()

    def defaults(self):
        return {'show_url': False, 'show_news': True, 'trailer_autoplay': True,
                'poster_size': 'medium', 'default_player': 'integrated', 'buffer_minutes': 2,
                'subtitle_language': 'it', 'autoplay_next': False,
                'download_method': 'integrated', 'download_dir': str(Path.home() / 'Downloads' / 'Lume')}

    def settings(self):
        with self.lock:
            result = self.defaults()
            result.update({k: v for k, v in self.state.get('settings', {}).items() if k in result})
            return result

    def _validate_settings(self, data):
        if not isinstance(data, dict):
            raise self.Error('Le impostazioni devono essere un oggetto JSON.')
        defaults = self.defaults()
        unknown = set(data) - set(defaults)
        if unknown:
            raise self.Error('Impostazioni non riconosciute: ' + ', '.join(sorted(unknown)))
        result = {}
        for key, value in data.items():
            if key in ('show_url', 'show_news', 'trailer_autoplay', 'autoplay_next'):
                if not isinstance(value, bool):
                    raise self.Error(f'Il valore di {key} deve essere sì o no.')
            elif key == 'poster_size':
                if value not in ('small', 'medium', 'large'):
                    raise self.Error('Dimensione locandine non valida.')
            elif key == 'default_player':
                if value not in ('integrated', 'mpv'):
                    raise self.Error('Player non disponibile: scegli Integrato o MPV.')
            elif key == 'download_method':
                if value != 'integrated':
                    raise self.Error('È disponibile il downloader integrato di Lume.')
            elif key == 'buffer_minutes':
                if isinstance(value, bool) or not isinstance(value, (int, float)) or value not in (0.5, 1, 2, 3, 5, 10):
                    raise self.Error('Il buffer deve essere 0,5, 1, 2, 3, 5 o 10 minuti.')
            elif key == 'subtitle_language':
                if value not in ('it', 'en', 'es', 'fr', 'de', 'none'):
                    raise self.Error('Lingua sottotitoli non valida.')
            elif key == 'download_dir':
                if not isinstance(value, str) or not value.strip() or len(value) > 1000:
                    raise self.Error('Cartella di download non valida.')
                destination = Path(value).expanduser()
                if not destination.is_absolute() or str(destination.resolve()) == destination.anchor:
                    raise self.Error('Scegli una cartella assoluta, non la radice del disco.')
                if destination.exists() and not destination.is_dir():
                    raise self.Error('La destinazione selezionata non è una cartella.')
                value = str(destination)
            result[key] = value
        return result

    def _watchlists(self):
        with self.lock:
            return {'watchlists': copy.deepcopy(self.state['watchlists'])}

    def _change_watchlists(self, method, data):
        with self.lock:
            lists = self.state['watchlists']
            list_id = data.get('id') or data.get('list_id')
            entry = next((item for item in lists if item['id'] == list_id), None)
            if method == 'DELETE':
                if not entry:
                    raise self.Error('Lista non trovata.')
                if data.get('url'):
                    entry['items'] = [item for item in entry['items'] if item['url'] != data['url']]
                    entry['updated_at'] = time.time()
                else:
                    lists.remove(entry)
            elif data.get('media') is not None:
                if not entry:
                    raise self.Error('Scegli una lista esistente.')
                try:
                    media = _media(data['media'])
                except ValueError as exc:
                    raise self.Error(str(exc)) from exc
                entry['items'] = [item for item in entry['items'] if item['url'] != media['url']]
                if data.get('enabled', True):
                    entry['items'].append(media)
                entry['updated_at'] = time.time()
            else:
                name = data.get('name', '').strip() if isinstance(data.get('name', ''), str) else ''
                if not name or len(name) > 80:
                    raise self.Error('Il nome della lista deve avere da 1 a 80 caratteri.')
                if any(x['name'].casefold() == name.casefold() and x is not entry for x in lists):
                    raise self.Error('Esiste già una lista con questo nome.')
                if entry:
                    entry.update(name=name, updated_at=time.time())
                else:
                    entry = {'id': uuid.uuid4().hex, 'name': name, 'items': [], 'updated_at': time.time()}
                    lists.append(entry)
            self.save()
            return self._watchlists()

    def _export(self):
        with self.lock:
            keys = ('channels', 'favorites', 'progress', 'settings', 'watchlists', 'history', 'list_url', 'profiles', 'active_profile')
            state = {key: copy.deepcopy(self.state[key]) for key in keys if key in self.state}
            for profile in state.get('profiles', []):
                if profile['id'] == state.get('active_profile'):
                    profile['data'] = self._profile_snapshot()
        return {'format': 'lume-backup', 'version': 1, 'created_at': time.time(), 'state': _redact(state)}

    def _validate_import(self, payload):
        if not isinstance(payload, dict):
            raise self.Error('Il backup deve essere un oggetto JSON.')
        payload = payload.get('backup', payload)
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except ValueError as exc:
                raise self.Error('Il file non contiene JSON valido.') from exc
        if not isinstance(payload, dict):
            raise self.Error('Il backup non è valido.')
        if payload.get('format') not in (None, 'lume-backup') or payload.get('version', 1) != 1:
            raise self.Error('Formato o versione del backup non supportati.')
        source = payload.get('state', payload)
        if not isinstance(source, dict):
            raise self.Error('Lo stato del backup non è valido.')
        allowed = {'channels', 'favorites', 'progress', 'settings', 'watchlists', 'history', 'list_url', 'profiles', 'active_profile'}
        if not any(key in source for key in allowed):
            raise self.Error('Il backup non contiene dati Lume riconoscibili.')
        clean = {}
        try:
            for name in ('channels', 'favorites', 'watchlists', 'history'):
                if name in source and (not isinstance(source[name], list) or len(source[name]) > 10000):
                    raise ValueError('Raccolta non valida o troppo grande: ' + name)
            if 'channels' in source:
                clean['channels'] = []
                for item in source['channels']:
                    if not isinstance(item, dict):
                        raise ValueError('Canale non valido.')
                    url = _safe_url(item.get('url', ''))
                    clean['channels'].append({'id': str(item.get('id') or _identifier(url)), 'name': str(item.get('name') or urlsplit(url).hostname)[:200],
                                              'url': url, 'status': 'pending', 'error': '', 'count': 0})
            if 'favorites' in source:
                clean['favorites'] = [_media(item) for item in source['favorites']]
            if 'history' in source:
                clean['history'] = []
                for item in source['history']:
                    media = _media(item.get('media', item))
                    watched_at = float(item.get('watched_at', time.time()))
                    if not 0 <= watched_at <= 1e12:
                        raise ValueError('Data della cronologia non valida.')
                    clean['history'].append({'media': media, 'watched_at': watched_at, 'watched': bool(item.get('watched', False))})
            if 'settings' in source:
                clean['settings'] = self._validate_settings(source['settings'])
            if 'progress' in source:
                if not isinstance(source['progress'], dict) or len(source['progress']) > 10000:
                    raise ValueError('Avanzamenti non validi.')
                clean['progress'] = {}
                for url, item in source['progress'].items():
                    _safe_url(url, local=True)
                    if not isinstance(item, dict):
                        raise ValueError('Avanzamento non valido.')
                    position, duration = float(item.get('position', 0)), float(item.get('duration', 0))
                    if not (0 <= position <= 1e8 and 0 <= duration <= 1e8):
                        raise ValueError('Avanzamento fuori intervallo.')
                    clean['progress'][url] = {'position': position, 'duration': duration}
            if 'watchlists' in source:
                clean['watchlists'] = []
                for item in source['watchlists']:
                    if not isinstance(item, dict) or not isinstance(item.get('items', []), list) or len(item.get('items', [])) > 10000:
                        raise ValueError('Lista personale non valida.')
                    name = str(item.get('name', '')).strip()
                    if not name or len(name) > 80:
                        raise ValueError('Nome della lista non valido.')
                    clean['watchlists'].append({'id': str(item.get('id') or uuid.uuid4().hex), 'name': name,
                                               'items': [_media(media) for media in item.get('items', [])], 'updated_at': time.time()})
            if 'list_url' in source:
                clean['list_url'] = _safe_url(source['list_url'])
            if 'profiles' in source:
                if not isinstance(source['profiles'], list) or not 1 <= len(source['profiles']) <= 100:
                    raise ValueError('Elenco profili non valido.')
                clean['profiles'] = []
                ids, names = set(), set()
                for profile in source['profiles']:
                    if not isinstance(profile, dict) or not isinstance(profile.get('data'), dict):
                        raise ValueError('Profilo del backup non valido.')
                    profile_id = str(profile.get('id', ''))
                    name = str(profile.get('name', '')).strip()
                    if not profile_id or len(profile_id) > 100 or not name or len(name) > 80 or profile_id in ids or name.casefold() in names:
                        raise ValueError('Identificativo o nome profilo duplicato/non valido.')
                    ids.add(profile_id)
                    names.add(name.casefold())
                    content = {key: profile['data'].get(key, {} if key in ('progress', 'settings') else []) for key in PROFILE_FIELDS}
                    validated = self._validate_import({'state': content})
                    clean['profiles'].append({'id': profile_id, 'name': name, 'data': validated})
                active = source.get('active_profile')
                if active not in ids:
                    raise ValueError('Il profilo attivo del backup non esiste.')
                clean['active_profile'] = active
            elif 'active_profile' in source:
                raise ValueError('Il backup deve includere i profili per specificare quello attivo.')
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            raise self.Error(str(exc)) from exc
        return clean

    def _import(self, data):
        clean = self._validate_import(data)
        replace = data.get('mode') == 'replace'
        with self.lock:
            self.data_dir.joinpath('backups').mkdir(parents=True, exist_ok=True)
            backup = self.data_dir / 'backups' / (time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8] + '.json')
            backup.write_text(json.dumps(self._export(), ensure_ascii=False, indent=2), encoding='utf-8')
            before = copy.deepcopy(self.state)
            try:
                self._apply_import(clean, replace)
                self.save()
            except Exception:
                self.state.clear()
                self.state.update(before)
                raise
        return {'ok': True, 'imported': list(clean), 'mode': 'replace' if replace else 'merge', 'previous_backup': backup.name}

    def _apply_import(self, clean, replace):
        with self.lock:
            for key, imported in clean.items():
                if key in ('profiles', 'active_profile'):
                    continue
                if 'profiles' in clean and key in PROFILE_FIELDS:
                    # Nei backup multi-profilo i dati annidati sono autorevoli:
                    # non mescolare il profilo esportato con quello attualmente aperto.
                    continue
                if replace or key not in self.state:
                    self.state[key] = imported
                elif key in ('settings', 'progress'):
                    self.state[key].update(imported)
                elif key in ('channels', 'favorites'):
                    by_url = {entry['url']: entry for entry in self.state[key]}
                    by_url.update({entry['url']: entry for entry in imported})
                    self.state[key] = list(by_url.values())
                elif key == 'watchlists':
                    existing = {entry['id']: entry for entry in self.state[key]}
                    for entry in imported:
                        if entry['id'] in existing:
                            old = existing[entry['id']]
                            items = {m['url']: m for m in old['items']}
                            items.update({m['url']: m for m in entry['items']})
                            entry['items'] = list(items.values())
                        existing[entry['id']] = entry
                    self.state[key] = list(existing.values())
                elif key == 'history':
                    existing = {entry['media']['url']: entry for entry in self.state[key]}
                    existing.update({entry['media']['url']: entry for entry in imported})
                    self.state[key] = list(existing.values())
                else:
                    self.state[key] = imported
            current = next(p for p in self.state['profiles'] if p['id'] == self.state['active_profile'])
            current['data'] = self._profile_snapshot()
            if 'profiles' in clean:
                if replace:
                    self.state['profiles'] = copy.deepcopy(clean['profiles'])
                    self.state['active_profile'] = clean['active_profile']
                    active = next(p for p in self.state['profiles'] if p['id'] == clean['active_profile'])
                    for key in PROFILE_FIELDS:
                        self.state[key] = copy.deepcopy(active['data'][key])
                else:
                    profiles = self.state['profiles']
                    for incoming in clean['profiles']:
                        incoming = copy.deepcopy(incoming)
                        old = next((p for p in profiles if p['id'] == incoming['id']), None)
                        if old and old['name'].casefold() == incoming['name'].casefold():
                            old['data'] = self._merge_profile_data(old['data'], incoming['data'])
                            if old['id'] == self.state['active_profile']:
                                for key in PROFILE_FIELDS:
                                    self.state[key] = copy.deepcopy(old['data'][key])
                        else:
                            if old:
                                incoming['id'] = uuid.uuid4().hex
                            name = incoming['name']
                            suffix = 1
                            while any(p['name'].casefold() == incoming['name'].casefold() for p in profiles):
                                incoming['name'] = name[:60] + (' (importato)' if suffix == 1 else f' (importato {suffix})')
                                suffix += 1
                            profiles.append(incoming)

    def _merge_profile_data(self, existing, incoming):
        result = copy.deepcopy(existing)
        for key in PROFILE_FIELDS:
            value = incoming[key]
            if key in ('settings', 'progress'):
                result.setdefault(key, {}).update(value)
            elif key == 'watchlists':
                by_id = {entry['id']: entry for entry in result.get(key, [])}
                for entry in value:
                    entry = copy.deepcopy(entry)
                    if entry['id'] in by_id:
                        items = {m['url']: m for m in by_id[entry['id']]['items']}
                        items.update({m['url']: m for m in entry['items']})
                        entry['items'] = list(items.values())
                    by_id[entry['id']] = entry
                result[key] = list(by_id.values())
            else:
                url_for = (lambda entry: entry['media']['url']) if key == 'history' else (lambda entry: entry['url'])
                entries = {url_for(entry): entry for entry in result.get(key, [])}
                entries.update({url_for(entry): copy.deepcopy(entry) for entry in value})
                result[key] = list(entries.values())
        return result

    def _restore_downloads(self):
        for item in self.state.get('downloads', [])[-200:]:
            if not isinstance(item, dict) or not item.get('id'):
                continue
            job = {key: copy.deepcopy(item[key]) for key in ('id', 'title', 'filename', 'status', 'bytes', 'total', 'created_at', 'error', 'path') if key in item}
            if job.get('status') not in ('completed', 'cancelled', 'error'):
                job.update(status='interrupted', error='Download interrotto alla chiusura dell’app. Avvialo di nuovo dalla sorgente.')
            self.jobs[job['id']] = job

    def _job_view(self, job):
        return {key: copy.deepcopy(value) for key, value in job.items() if key not in ('cancel', 'thread', 'process', 'response', 'url', 'referer')}

    def _persist_downloads(self):
        with self.job_lock:
            items = [self._job_view(job) for job in self.jobs.values()][-200:]
        with self.lock:
            self.state['downloads'] = items
            self.save()

    def _download_list(self):
        with self.job_lock:
            return {'items': [self._job_view(job) for job in sorted(self.jobs.values(), key=lambda item: item.get('created_at', 0), reverse=True)]}

    def _start_download(self, data):
        try:
            url = _safe_url(data.get('url', ''))
            referer = data.get('referer', '')
            if referer:
                _safe_url(referer)
        except ValueError as exc:
            raise self.Error(str(exc)) from exc
        title = str(data.get('title') or 'Video')[:300]
        job_id = uuid.uuid4().hex
        job = {'id': job_id, 'title': title, 'filename': '', 'status': 'queued', 'bytes': 0, 'total': None,
               'created_at': time.time(), 'error': '', 'url': url, 'referer': referer, 'cancel': threading.Event(),
               'destination': self.settings()['download_dir']}
        with self.job_lock:
            self.jobs[job_id] = job
        thread = threading.Thread(target=self._download_worker, args=(job,), name='lume-download-' + job_id[:8], daemon=True)
        job['thread'] = thread
        self._persist_downloads()
        thread.start()
        return {'ok': True, 'job': self._job_view(job), **self._download_list()}

    def _reserve_destination(self, name, suffix, folder=None):
        destination = Path(folder or self.settings()['download_dir']).expanduser()
        destination.mkdir(parents=True, exist_ok=True)
        basename = _filename(name)
        if Path(basename).suffix.lower() in VIDEO_EXTENSIONS:
            basename = str(Path(basename).with_suffix(''))
        for number in range(10000):
            filename = basename + (f' ({number})' if number else '') + suffix
            path = destination / filename
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                return path
            except FileExistsError:
                continue
        raise self.Error('Impossibile scegliere un nome libero per il download.')

    def _ffmpeg_path(self):
        candidates = [self.root / 'bin' / 'ffmpeg.exe', Path(os.environ.get('LOCALAPPDATA', '')) / 'Programs/Veezie.st/resources/app.asar.unpacked/node_modules/ffmpeg-static/ffmpeg.exe']
        executable = next((str(candidate) for candidate in candidates if candidate.is_file()), None)
        return executable or shutil.which('ffmpeg')

    def _download_worker(self, job):
        partial, output = None, None
        with self.download_semaphore:
            if job['cancel'].is_set() or self.closed.is_set():
                job['status'] = 'cancelled'
                self._persist_downloads()
                return
            try:
                job['status'] = 'resolving'
                sources = self.resolve(job['url'], job.get('referer', ''))
                if not sources:
                    raise self.Error('La sorgente non ha restituito un video da scaricare.')
                source = sources[0]
                url = source['url']
                referer = (source.get('headers') or {}).get('Referer') or job.get('referer', '')
                is_hls = source.get('kind') == 'hls' or urlsplit(url).path.endswith('.m3u8')
                suffix = '.mp4' if is_hls else Path(urlsplit(url).path).suffix.lower()
                if suffix not in VIDEO_EXTENSIONS:
                    suffix = '.mp4'
                output = self._reserve_destination(job['title'], suffix, job.get('destination'))
                partial = output.with_name(output.name + '.' + job['id'][:8] + '.part')
                job.update(filename=output.name, path=str(output), status='downloading')
                self._persist_downloads()
                if is_hls:
                    self._download_hls(job, url, referer, partial)
                else:
                    self._download_http(job, url, referer, partial)
                if job['cancel'].is_set() or self.closed.is_set():
                    job['status'] = 'cancelled'
                else:
                    os.replace(partial, output)
                    partial = None
                    job.update(status='completed', bytes=output.stat().st_size, total=output.stat().st_size, completed_at=time.time())
            except Exception as exc:
                job.update(status='cancelled' if job['cancel'].is_set() or self.closed.is_set() else 'error',
                           error='' if job['cancel'].is_set() else str(exc)[:500])
            finally:
                response = job.pop('response', None)
                if response is not None:
                    response.close()
                # Elimina solo i due file creati da questo job; mai file preesistenti.
                for path in (partial, output if job.get('status') != 'completed' else None):
                    if path and path.exists():
                        try:
                            path.unlink()
                        except OSError:
                            pass
                job.pop('process', None)
                self._persist_downloads()

    def _download_http(self, job, url, referer, partial):
        response = self.request(url, referer, stream=True)
        job['response'] = response
        ctype = response.headers.get('Content-Type', '').lower()
        if any(kind in ctype for kind in ('text/html', 'application/json')):
            raise self.Error('La sorgente ha restituito una pagina, non un file video.')
        length = response.headers.get('Content-Length')
        try:
            job['total'] = int(length) if length else None
        except ValueError:
            job['total'] = None
        with partial.open('xb') as handle:
            last_update = 0
            for chunk in response.iter_content(256 * 1024):
                if job['cancel'].is_set() or self.closed.is_set():
                    return
                if not chunk:
                    continue
                handle.write(chunk)
                job['bytes'] += len(chunk)
                if time.monotonic() - last_update > 1:
                    last_update = time.monotonic()
                    self._persist_downloads()
        response.close()
        job.pop('response', None)
        if job['total'] is not None and job['bytes'] != job['total'] and not response.headers.get('Content-Encoding'):
            raise self.Error('Download incompleto: la connessione è stata interrotta.')

    def _download_hls(self, job, url, referer, partial):
        executable = self._ffmpeg_path()
        if not executable:
            raise self.Error('FFmpeg non è disponibile per il download HLS.')
        media_proxy = self.context.get('media_proxy')
        if not callable(media_proxy):
            raise self.Error('Il proxy locale per il download HLS non è configurato.')
        proxy_url = media_proxy(url, referer)
        proxy = urlsplit(proxy_url)
        if proxy.scheme != 'http' or proxy.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise self.Error('Il download HLS richiede il proxy locale verificato.')
        # Ogni manifest/segmento attraversa il proxy, che rivalida destinazioni e redirect.
        response = self.request(url, referer, stream=True)
        response.close()
        header_lines = []
        if referer:
            header_lines.append('Referer: ' + referer)
        if (urlsplit(referer).hostname or '').endswith('.vidxgo.co'):
            header_lines.extend(['Sec-Fetch-Dest: empty', 'Sec-Fetch-Mode: cors', 'Sec-Fetch-Site: cross-site'])
        args = [executable, '-hide_banner', '-nostdin', '-loglevel', 'error', '-progress', 'pipe:1', '-nostats']
        if header_lines:
            args += ['-headers', '\r\n'.join(header_lines) + '\r\n']
        args += ['-protocol_whitelist', 'http,https,tcp,tls,crypto', '-i', proxy_url, '-c', 'copy', '-f', 'mp4', str(partial)]
        # stderr contiene talvolta URL firmati: non viene memorizzato né restituito.
        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                   encoding='utf-8', errors='replace', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        job['process'] = process
        try:
            if process.stdout is not None:
                for line in process.stdout:
                    if job['cancel'].is_set() or self.closed.is_set():
                        process.terminate()
                        break
                    key, _, value = line.strip().partition('=')
                    if key == 'total_size' and value.isdigit():
                        job['bytes'] = int(value)
                    elif key == 'out_time_us' and value.isdigit():
                        job['seconds'] = int(value) / 1_000_000
            try:
                code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                code = -1
            if code and not job['cancel'].is_set() and not self.closed.is_set():
                raise self.Error('FFmpeg non ha completato il download HLS. La sorgente potrebbe essere scaduta o non supportata.')
        finally:
            if process.stdout is not None:
                process.stdout.close()

    def _cancel_download(self, data):
        job_id = data.get('id')
        with self.job_lock:
            job = self.jobs.get(job_id)
            if not job:
                raise self.Error('Download non trovato.')
            if data.get('clear') and job.get('status') in ('completed', 'cancelled', 'error', 'interrupted'):
                del self.jobs[job_id]
            else:
                event = job.get('cancel')
                if event:
                    event.set()
                process = job.get('process')
                if process and process.poll() is None:
                    process.terminate()
                response = job.get('response')
                if response is not None:
                    response.close()
                if job.get('status') == 'queued':
                    job['status'] = 'cancelled'
        self._persist_downloads()
        return {'ok': True, **self._download_list()}

    def _scan_library(self, paths):
        items, files = [], {}
        for value in paths:
            folder = Path(value).expanduser().resolve()
            if not folder.is_dir() or folder == Path(folder.anchor) or folder.is_symlink():
                raise self.Error('Scegli una cartella video esistente, non la radice del disco.')
            for current, dirs, names in os.walk(folder, followlinks=False):
                current = Path(current)
                depth = len(current.relative_to(folder).parts)
                dirs[:] = [name for name in dirs if not name.startswith('.') and not (current / name).is_symlink()
                           and not getattr(current / name, 'is_junction', lambda: False)()]
                if depth >= 4:
                    dirs[:] = []
                for name in sorted(names, key=str.casefold):
                    path = current / name
                    if path.suffix.lower() not in VIDEO_EXTENSIONS or path.is_symlink():
                        continue
                    resolved = path.resolve()
                    if not resolved.is_relative_to(folder):
                        continue
                    key = _identifier(str(resolved))
                    if key in files:
                        continue
                    files[key] = resolved
                    items.append({'id': key, 'title': path.stem, 'url': '/api/local/file?id=' + key,
                                  'poster': '', 'year': '', 'kind': 'local', 'channel_id': 'local',
                                  'channel_name': folder.name, 'filename': name, 'size': path.stat().st_size})
                    if len(items) >= 1000:
                        self.local_files, self.library_items = files, items
                        return {'items': items, 'folders': list(paths), 'truncated': True}
        self.local_files, self.library_items = files, items
        return {'items': copy.deepcopy(items), 'folders': list(paths), 'truncated': False}

    def lookup_local(self, file_id):
        path = self.local_files.get(str(file_id))
        return path if path and path.is_file() else None

    def dispatch(self, method, path, data=None):
        data = data or {}
        if not isinstance(data, dict):
            raise self.Error('Richiesta JSON non valida.')
        if path == '/api/profiles':
            if method == 'GET':
                return self._profiles()
            if method in ('POST', 'DELETE'):
                return self._change_profiles(method, data)
        if path == '/api/settings':
            if method == 'POST':
                settings = self._validate_settings(data.get('settings', data))
                with self.lock:
                    self.state['settings'].update(settings)
                    self.save()
            elif method != 'GET':
                raise self.Error('Operazione impostazioni non disponibile.')
            return {'settings': self.settings()}
        if path == '/api/watchlists':
            if method == 'GET':
                return self._watchlists()
            if method in ('POST', 'DELETE'):
                return self._change_watchlists(method, data)
        if path == '/api/history':
            with self.lock:
                if method == 'DELETE':
                    url = data.get('url')
                    self.state['history'] = [item for item in self.state['history'] if item.get('media', item).get('url') != url] if url else []
                    if url:
                        self.state.get('progress', {}).pop(url, None)
                    self.save()
                elif method == 'POST':
                    try:
                        media = _media(data['media'])
                    except (ValueError, KeyError) as exc:
                        raise self.Error('Titolo della cronologia non valido.') from exc
                    self.state['history'] = [item for item in self.state['history'] if item.get('media', item).get('url') != media['url']]
                    self.state['history'].insert(0, {'media': media, 'watched_at': time.time(), 'watched': bool(data.get('watched', False))})
                    self.state['history'] = self.state['history'][:1000]
                    self.save()
                elif method != 'GET':
                    raise self.Error('Operazione cronologia non disponibile.')
                return {'items': copy.deepcopy(self.state['history']), 'progress': copy.deepcopy(self.state.get('progress', {}))}
        if path == '/api/backup':
            if method == 'GET':
                return self._export()
            if method == 'POST':
                return self._import(data)
        if path == '/api/downloads':
            if method == 'GET':
                return self._download_list()
            if method == 'POST':
                return self._start_download(data)
            if method == 'DELETE':
                return self._cancel_download(data)
        if path == '/api/library':
            with self.lock:
                paths = list(self.state.get('library_paths', []))
            if method == 'POST':
                value = data.get('path')
                if value:
                    if not isinstance(value, str):
                        raise self.Error('Percorso della cartella non valido.')
                    value = str(Path(value).expanduser().resolve())
                    if value not in paths:
                        paths.append(value)
                result = self._scan_library(paths)
                with self.lock:
                    self.state['library_paths'] = paths
                    self.save()
                return result
            if method == 'DELETE':
                paths = [value for value in paths if value != data.get('path')]
                result = self._scan_library(paths)
                with self.lock:
                    self.state['library_paths'] = paths
                    self.save()
                return result
            if method == 'GET':
                return self._scan_library(paths)
        return None

    def close(self):
        self.closed.set()
        with self.job_lock:
            for job in self.jobs.values():
                event = job.get('cancel')
                if event:
                    event.set()
                process = job.get('process')
                if process and process.poll() is None:
                    process.terminate()
                response = job.get('response')
                if response is not None:
                    response.close()
