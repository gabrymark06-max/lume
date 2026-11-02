import copy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from features import Features, _filename


class FakeResponse:
    def __init__(self, chunks, ctype='video/mp4'):
        self.chunks = chunks
        self.headers = {'Content-Type': ctype, 'Content-Length': str(sum(map(len, chunks)))}
        self.closed = False

    def iter_content(self, size):
        yield from self.chunks

    def close(self):
        self.closed = True


class FeaturesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = {'channels': [{'id': 'one', 'name': 'Uno', 'url': 'https://one.example/'}],
                      'favorites': [], 'progress': {}, 'list_url': 'https://list.example/'}
        self.saved = []
        self.features = Features({'state': self.state, 'lock': threading.RLock(),
                                  'save': lambda: self.saved.append(copy.deepcopy(self.state)),
                                  'request': lambda *a, **k: FakeResponse([b'video-fixture']),
                                  'resolve': lambda url, ref: [{'url': url, 'kind': 'video'}],
                                  'root': self.root, 'data_dir': self.root / 'data', 'SourceError': ValueError})
        self.media = {'url': 'https://one.example/film/1', 'title': 'Città', 'kind': 'movie'}

    def tearDown(self):
        self.features.close()
        for job in list(self.features.jobs.values()):
            thread = job.get('thread')
            if thread:
                thread.join(timeout=5)
        self.tmp.cleanup()

    def test_settings_validate_before_mutating(self):
        old = self.features.settings()
        with self.assertRaises(ValueError):
            self.features.dispatch('POST', '/api/settings', {'settings': {'show_url': True, 'buffer_minutes': -5}})
        self.assertEqual(self.features.settings(), old)
        self.features.dispatch('POST', '/api/settings', {'settings': {'show_url': True, 'poster_size': 'large'}})
        self.assertTrue(self.features.settings()['show_url'])
        self.assertEqual(self.state['settings']['poster_size'], 'large')
        with self.assertRaises(ValueError):
            self.features.dispatch('POST', '/api/settings', {'token': 'never-store'})

    def test_watchlist_creation_add_remove_and_duplicate_name(self):
        result = self.features.dispatch('POST', '/api/watchlists', {'name': 'Da vedere'})
        list_id = result['watchlists'][0]['id']
        self.features.dispatch('POST', '/api/watchlists', {'id': list_id, 'media': self.media})
        self.features.dispatch('POST', '/api/watchlists', {'id': list_id, 'media': self.media})
        self.assertEqual(len(self.state['watchlists'][0]['items']), 1)
        with self.assertRaises(ValueError):
            self.features.dispatch('POST', '/api/watchlists', {'name': 'da vedere'})
        self.features.dispatch('DELETE', '/api/watchlists', {'id': list_id, 'url': self.media['url']})
        self.assertEqual(self.state['watchlists'][0]['items'], [])

    def test_backup_merge_preserves_existing_and_creates_previous_backup(self):
        backup = {'format': 'lume-backup', 'version': 1, 'state': {'favorites': [self.media],
                  'channels': [{'name': 'Due', 'url': 'https://two.example/'}], 'settings': {'show_url': True}}}
        result = self.features.dispatch('POST', '/api/backup', backup)
        self.assertEqual(len(self.state['channels']), 2)
        self.assertEqual(self.state['favorites'][0]['title'], 'Città')
        previous = self.root / 'data' / 'backups' / result['previous_backup']
        self.assertTrue(previous.is_file())
        self.assertEqual(len(json.loads(previous.read_text(encoding='utf-8'))['state']['channels']), 1)

    def test_invalid_backup_never_mutates_state_or_writes_previous_backup(self):
        old = copy.deepcopy(self.state)
        with self.assertRaises(ValueError):
            self.features.dispatch('POST', '/api/backup', {'state': {'channels': [{'url': 'file:///private'}]}})
        self.assertEqual(self.state, old)
        self.assertFalse((self.root / 'data' / 'backups').exists())

    def test_backup_omits_secret_fields_and_signed_query(self):
        self.state['settings']['api_token'] = 'private'
        self.state['favorites'] = [{'title': 'Titolo', 'url': 'https://example.org/title?token=private&q=film', 'id_token': 'private'}]
        self.state['progress']['https://example.org/title?token=private'] = {'position': 1, 'duration': 2}
        result = self.features.dispatch('GET', '/api/backup')
        serialized = json.dumps(result)
        self.assertNotIn('private', serialized)
        self.assertIn('q=film', serialized)

    def test_hls_download_requires_safe_proxy_and_keeps_remote_url_out_of_ffmpeg_input(self):
        job = {'cancel': threading.Event(), 'bytes': 0}
        self.features.context['media_proxy'] = lambda url, ref: 'http://127.0.0.1:8766/api/media?url=opaque'
        fake = type('FakeProcess', (), {'stdout': iter(['total_size=12\n', 'out_time_us=1000000\n']),
                                      'wait': lambda self, timeout: 0})()
        class Stream:
            def __iter__(self):
                return iter(['total_size=12\n', 'out_time_us=1000000\n'])
            def close(self):
                pass
        fake.stdout = Stream()
        with patch.object(self.features, '_ffmpeg_path', return_value='ffmpeg.exe'), patch('features.subprocess.Popen', return_value=fake) as popen:
            self.features._download_hls(job, 'https://cdn.example/master.m3u8?token=not-logged', 'https://v.vidxgo.co', self.root / 'part.mp4')
        args = popen.call_args.args[0]
        self.assertEqual(args[args.index('-i') + 1], 'http://127.0.0.1:8766/api/media?url=opaque')
        self.assertNotIn('file', args[args.index('-protocol_whitelist') + 1].split(','))
        self.assertIn('Sec-Fetch-Dest: empty', args[args.index('-headers') + 1])
        self.assertEqual(job['seconds'], 1)

    def test_library_does_not_expose_arbitrary_path_or_symlink_target(self):
        folder = self.root / 'video'
        folder.mkdir()
        (folder / 'Un film.mp4').write_bytes(b'fixture')
        (folder / 'segreto.txt').write_text('non-video')
        result = self.features.dispatch('POST', '/api/library', {'path': str(folder)})
        self.assertEqual(len(result['items']), 1)
        item = result['items'][0]
        self.assertTrue(item['url'].startswith('/api/local/file?id='))
        self.assertEqual(self.features.lookup_local(item['id']), folder / 'Un film.mp4')
        self.assertIsNone(self.features.lookup_local(str(folder / 'segreto.txt')))
        with self.assertRaises(ValueError):
            self.features.dispatch('POST', '/api/library', {'path': folder.anchor})

    def test_download_stream_and_collision_preserve_existing_file(self):
        destination = self.root / 'downloads'
        destination.mkdir()
        original = destination / 'Titolo.mp4'
        original.write_bytes(b'existing')
        self.features.dispatch('POST', '/api/settings', {'download_dir': str(destination)})
        result = self.features.dispatch('POST', '/api/downloads', {'url': 'https://cdn.example/video.mp4', 'title': 'Titolo'})
        job = self.features.jobs[result['job']['id']]
        job['thread'].join(timeout=5)
        self.assertEqual(job['status'], 'completed')
        self.assertEqual(original.read_bytes(), b'existing')
        self.assertEqual((destination / 'Titolo (1).mp4').read_bytes(), b'video-fixture')
        public = self.features.dispatch('GET', '/api/downloads')['items'][0]
        self.assertNotIn('url', public)
        self.assertNotIn('cancel', public)

    def test_download_html_error_is_not_reported_as_saved_video(self):
        self.features.request = lambda *a, **k: FakeResponse([b'<html>no</html>'], 'text/html')
        self.features.dispatch('POST', '/api/settings', {'download_dir': str(self.root / 'downloads')})
        result = self.features.dispatch('POST', '/api/downloads', {'url': 'https://cdn.example/video.mp4', 'title': 'No'})
        job = self.features.jobs[result['job']['id']]
        job['thread'].join(timeout=5)
        self.assertEqual(job['status'], 'error')
        self.assertIn('pagina', job['error'])
        self.assertEqual(list((self.root / 'downloads').iterdir()), [])

    def test_filename_is_not_a_path_or_reserved_windows_name(self):
        self.assertNotIn('/', _filename('../cartella/film'))
        self.assertEqual(_filename('CON'), '_CON')

    def test_history_mark_and_remove_also_clears_progress(self):
        self.features.dispatch('POST', '/api/history', {'media': self.media, 'watched': True})
        self.state['progress'][self.media['url']] = {'position': 10, 'duration': 100}
        self.features.dispatch('DELETE', '/api/history', {'url': self.media['url']})
        self.assertEqual(self.state['history'], [])
        self.assertNotIn(self.media['url'], self.state['progress'])

    def test_profiles_migrate_main_without_losing_current_data(self):
        self.features.close()
        state = {'channels': copy.deepcopy(self.state['channels']), 'favorites': [self.media],
                 'progress': {self.media['url']: {'position': 10, 'duration': 100}},
                 'settings': {'show_url': True}, 'watchlists': [], 'history': []}
        context = dict(self.features.context, state=state)
        feature = Features(context)
        try:
            info = feature.dispatch('GET', '/api/profiles')
            self.assertEqual(info['profiles'][0]['name'], 'Principale')
            self.assertEqual(state['favorites'], [self.media])
            self.assertEqual(state['profiles'][0]['data']['progress'], state['progress'])
        finally:
            feature.close()

    def test_profiles_isolate_favorites_progress_history_watchlists_settings(self):
        main = self.state['active_profile']
        self.state['favorites'] = [copy.deepcopy(self.media)]
        self.state['progress'] = {self.media['url']: {'position': 10, 'duration': 100}}
        self.features.dispatch('POST', '/api/history', {'media': self.media, 'watched': True})
        self.features.dispatch('POST', '/api/watchlists', {'name': 'Principale lista'})
        self.features.dispatch('POST', '/api/settings', {'show_url': True})
        original = self.features._profile_snapshot()
        channels = copy.deepcopy(self.state['channels'])
        created = self.features.dispatch('POST', '/api/profiles', {'action': 'create', 'name': 'Secondo'})
        other = next(p['id'] for p in created['profiles'] if p['name'] == 'Secondo')
        self.assertEqual(created['active_profile'], main)
        self.features.dispatch('POST', '/api/profiles', {'action': 'switch', 'id': other})
        for field in ('favorites', 'history', 'watchlists'):
            self.assertEqual(self.state[field], [])
        self.assertEqual(self.state['progress'], {})
        self.assertFalse(self.features.settings()['show_url'])
        self.assertEqual(self.state['channels'], channels)
        second_media = dict(self.media, url='https://one.example/film/2', title='Secondo film')
        self.state['favorites'] = [second_media]
        self.features.dispatch('POST', '/api/profiles', {'action': 'switch', 'id': main})
        self.assertEqual(self.features._profile_snapshot(), original)
        self.features.dispatch('POST', '/api/profiles', {'action': 'switch', 'id': other})
        self.assertEqual(self.state['favorites'], [second_media])

    def test_profiles_reject_active_deletion_last_and_duplicate_name(self):
        main = self.state['active_profile']
        with self.assertRaises(ValueError):
            self.features.dispatch('DELETE', '/api/profiles', {'id': main})
        with self.assertRaises(ValueError):
            self.features.dispatch('POST', '/api/profiles', {'action': 'create', 'name': 'Principale', 'id': main})
        result = self.features.dispatch('POST', '/api/profiles', {'action': 'create', 'name': 'Altro'})
        other = next(p['id'] for p in result['profiles'] if p['id'] != main)
        self.features.dispatch('DELETE', '/api/profiles', {'id': other})
        self.assertEqual(len(self.state['profiles']), 1)

    def test_profile_switch_rolls_back_if_persistence_fails(self):
        result = self.features.dispatch('POST', '/api/profiles', {'action': 'create', 'name': 'Altro'})
        other = next(p['id'] for p in result['profiles'] if p['name'] == 'Altro')
        self.state['favorites'] = [copy.deepcopy(self.media)]
        original = copy.deepcopy(self.state)
        with patch.object(self.features, 'save', side_effect=OSError('fixture disk full')):
            with self.assertRaises(OSError):
                self.features.dispatch('POST', '/api/profiles', {'action': 'switch', 'id': other})
        self.assertEqual(self.state, original)

    def test_backup_includes_fresh_active_snapshot_and_preserves_other_profiles_on_merge(self):
        main = self.state['active_profile']
        self.state['favorites'] = [copy.deepcopy(self.media)]
        backup = self.features.dispatch('GET', '/api/backup')
        active = next(p for p in backup['state']['profiles'] if p['id'] == main)
        self.assertEqual(active['data']['favorites'], [self.media])
        created = self.features.dispatch('POST', '/api/profiles', {'action': 'create', 'name': 'Non perdere'})
        other = next(p['id'] for p in created['profiles'] if p['name'] == 'Non perdere')
        self.features.dispatch('POST', '/api/profiles', {'action': 'switch', 'id': other})
        self.state['favorites'] = [dict(self.media, url='https://one.example/film/secondo')]
        self.features.dispatch('POST', '/api/backup', backup)
        self.assertEqual(len(self.state['profiles']), 2)
        self.assertEqual(self.state['active_profile'], other)
        self.assertEqual(len(self.state['favorites']), 1)
        self.assertTrue(self.state['favorites'][0]['url'].endswith('/secondo'))
        self.features.dispatch('POST', '/api/profiles', {'action': 'switch', 'id': main})
        self.assertEqual([item['url'] for item in self.state['favorites']], [self.media['url']])
        self.assertEqual(self.state['favorites'][0]['title'], self.media['title'])

    def test_backup_profile_replace_restores_active_and_data_atomically(self):
        main = self.state['active_profile']
        self.state['favorites'] = [copy.deepcopy(self.media)]
        backup = self.features.dispatch('GET', '/api/backup')
        self.features.dispatch('POST', '/api/profiles', {'action': 'create', 'name': 'Temporaneo'})
        self.features.dispatch('POST', '/api/backup', {'backup': backup, 'mode': 'replace'})
        self.assertEqual(self.state['active_profile'], main)
        self.assertEqual([item['url'] for item in self.state['favorites']], [self.media['url']])
        self.assertEqual(self.state['favorites'][0]['title'], self.media['title'])
        self.assertEqual(len(self.state['profiles']), 1)

    def test_history_keeps_episode_and_series_for_resume(self):
        media = dict(self.media, url='https://host.example/series/1/2', series_url=self.media['url'],
                     episode={'label': 'S1 E2', 'url': 'https://host.example/series/1/2', 'kind': 'embed', 'season': 1, 'number': 2})
        self.features.dispatch('POST', '/api/history', {'media': media})
        restored = self.features.dispatch('GET', '/api/history')['items'][0]['media']
        self.assertEqual(restored['series_url'], self.media['url'])
        self.assertEqual(restored['episode']['number'], 2)


if __name__ == '__main__':
    unittest.main()
