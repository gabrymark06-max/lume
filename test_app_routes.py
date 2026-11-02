"""Integrazione HTTP reale su loopback e dati temporanei, senza sorgenti esterne."""
import copy
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import server as app


class AppRouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / 'data'
        self.state = {'channels': [{'id': 'fixture', 'name': 'Canale fixture', 'url': 'https://catalog.example/'}],
                      'favorites': [], 'progress': {}, 'list_url': 'https://lists.example/', 'last_refresh': None}
        self.globals = patch.multiple(app, STATE=self.state, DATA=self.data_dir,
                                      STATE_FILE=self.data_dir / 'state.json', FEATURES=None,
                                      CATALOG_FEATURES=None, CACHE={}, HTTP_PORT=0)
        self.globals.start()
        self.no_remote = patch.object(app, 'request_url', side_effect=AssertionError('Il test non può contattare sorgenti esterne.'))
        self.remote = self.no_remote.start()
        self.httpd = app.AppServer(('127.0.0.1', 0), app.Handler)
        app.HTTP_PORT = self.httpd.server_port
        self.base = 'http://127.0.0.1:' + str(self.httpd.server_port)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.media = {'url': 'https://catalog.example/title/film', 'title': 'Un film di prova',
                      'kind': 'movie', 'channel_id': 'fixture', 'channel_name': 'Canale fixture'}

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)
        if app.FEATURES is not None:
            app.FEATURES.close()
        self.no_remote.stop()
        self.globals.stop()
        self.tmp.cleanup()

    def request(self, method, path, data=None, headers=None, *, raw=False):
        connection = http.client.HTTPConnection('127.0.0.1', self.httpd.server_port, timeout=5)
        request_headers = {'Origin': self.base}
        if headers:
            request_headers.update(headers)
        payload = None
        if data is not None:
            payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
            request_headers.setdefault('Content-Type', 'application/json')
        try:
            connection.request(method, path, body=payload, headers=request_headers)
            response = connection.getresponse()
            body = response.read()
            response_headers = dict(response.getheaders())
            if not raw and 'application/json' in response_headers.get('Content-Type', ''):
                body = json.loads(body)
            return response.status, body, response_headers
        finally:
            connection.close()

    def test_settings_post_get_persist_and_invalid_update_is_atomic(self):
        status, result, _ = self.request('GET', '/api/settings')
        self.assertEqual(status, 200)
        self.assertEqual(result['settings']['default_player'], 'integrated')
        status, result, _ = self.request('POST', '/api/settings', {'settings': {'show_url': True, 'poster_size': 'large'}})
        self.assertEqual(status, 200)
        self.assertTrue(result['settings']['show_url'])
        status, _, _ = self.request('POST', '/api/settings', {'settings': {'show_url': False, 'buffer_minutes': -1}})
        self.assertEqual(status, 422)
        status, result, _ = self.request('GET', '/api/settings')
        self.assertTrue(result['settings']['show_url'])
        self.assertEqual(json.loads((self.data_dir / 'state.json').read_text(encoding='utf-8'))['settings']['poster_size'], 'large')
        self.remote.assert_not_called()

    def test_watchlists_http_create_rename_add_deduplicate_remove_delete(self):
        status, result, _ = self.request('POST', '/api/watchlists', {'name': 'Da vedere'})
        self.assertEqual(status, 200)
        list_id = result['watchlists'][0]['id']
        for _ in range(2):
            status, result, _ = self.request('POST', '/api/watchlists', {'id': list_id, 'media': self.media})
            self.assertEqual(status, 200)
        self.assertEqual(len(result['watchlists'][0]['items']), 1)
        self.request('POST', '/api/watchlists', {'id': list_id, 'name': 'Cinema'})
        status, result, _ = self.request('GET', '/api/watchlists')
        self.assertEqual(result['watchlists'][0]['name'], 'Cinema')
        self.request('DELETE', '/api/watchlists', {'id': list_id, 'url': self.media['url']})
        status, result, _ = self.request('DELETE', '/api/watchlists', {'id': list_id})
        self.assertEqual(status, 200)
        self.assertEqual(result['watchlists'], [])

    def test_invalid_backup_has_no_side_effect_and_valid_import_keeps_previous_copy(self):
        self.request('POST', '/api/settings', {'show_url': True})
        _, before, _ = self.request('GET', '/api/state')
        status, result, _ = self.request('POST', '/api/backup', {'state': {'channels': [{'url': 'file:///private'}]}})
        self.assertEqual(status, 422)
        _, after, _ = self.request('GET', '/api/state')
        self.assertEqual(after, before)
        self.assertFalse((self.data_dir / 'backups').exists())
        status, result, _ = self.request('POST', '/api/backup', {'state': {'favorites': [self.media]}})
        self.assertEqual(status, 200)
        backup = self.data_dir / 'backups' / result['previous_backup']
        self.assertTrue(backup.is_file())
        saved = json.loads(backup.read_text(encoding='utf-8'))
        self.assertEqual(saved['state']['favorites'], [])
        self.assertTrue(saved['state']['settings']['show_url'])
        self.assertEqual(len(self.state['channels']), 1)
        status, exported, _ = self.request('GET', '/api/backup')
        self.assertEqual(exported['format'], 'lume-backup')
        self.assertEqual(exported['state']['favorites'][0]['title'], self.media['title'])

    def test_profiles_isolate_favorites_and_settings_while_channels_remain_shared(self):
        _, original, _ = self.request('GET', '/api/profiles')
        main = original['active_profile']
        self.request('POST', '/api/favorite', {'media': self.media, 'enabled': True})
        self.request('POST', '/api/settings', {'show_url': True})
        status, profiles, _ = self.request('POST', '/api/profiles', {'action': 'create', 'name': 'Ospite locale'})
        self.assertEqual(status, 200)
        other = next(p['id'] for p in profiles['profiles'] if p['name'] == 'Ospite locale')
        self.request('POST', '/api/profiles', {'action': 'switch', 'id': other})
        _, state, _ = self.request('GET', '/api/state')
        _, settings, _ = self.request('GET', '/api/settings')
        self.assertEqual(state['favorites'], [])
        self.assertFalse(settings['settings']['show_url'])
        self.assertEqual(len(state['channels']), 1)
        self.request('POST', '/api/profiles', {'action': 'switch', 'id': main})
        _, state, _ = self.request('GET', '/api/state')
        self.assertEqual(state['favorites'][0]['url'], self.media['url'])
        status, _, _ = self.request('DELETE', '/api/profiles', {'id': main})
        self.assertEqual(status, 422)

    def test_progress_history_retains_episode_resume_information(self):
        series = 'https://catalog.example/title/series'
        episode = {'url': 'https://player.example/series/1/2', 'label': 'S1 · E2', 'kind': 'embed', 'season': 1, 'number': 2}
        media = dict(self.media, kind='series', url=episode['url'], series_url=series)
        status, result, _ = self.request('POST', '/api/progress', {'url': episode['url'], 'position': 120,
                                                               'duration': 600, 'media': media, 'episode': episode})
        self.assertEqual(status, 200)
        self.assertTrue(result['ok'])
        _, history, _ = self.request('GET', '/api/history')
        item = history['items'][0]
        self.assertEqual(item['media']['series_url'], series)
        self.assertEqual(item['media']['episode']['url'], episode['url'])
        self.assertEqual(history['progress'][episode['url']]['position'], 120)
        self.assertFalse(item['watched'])
        self.request('DELETE', '/api/history', {'url': episode['url']})
        _, history, _ = self.request('GET', '/api/history')
        self.assertEqual(history['items'], [])
        self.assertNotIn(episode['url'], history['progress'])

    def test_registered_local_file_uses_range_and_unknown_ids_are_denied(self):
        folder = Path(self.tmp.name) / 'video'
        folder.mkdir()
        fixture = b'0123456789video-fixture'
        (folder / 'Un video.mp4').write_bytes(fixture)
        (folder / 'non-video.txt').write_text('private-fixture')
        status, library, _ = self.request('POST', '/api/library', {'path': str(folder)})
        self.assertEqual(status, 200)
        self.assertEqual(len(library['items']), 1)
        url = library['items'][0]['url']
        status, body, headers = self.request('GET', url, headers={'Range': 'bytes=2-7'}, raw=True)
        self.assertEqual(status, 206)
        self.assertEqual(body, fixture[2:8])
        self.assertEqual(headers['Content-Range'], f'bytes 2-7/{len(fixture)}')
        self.assertEqual(headers['Accept-Ranges'], 'bytes')
        status, body, _ = self.request('GET', url, headers={'Range': 'bytes=-7'}, raw=True)
        self.assertEqual(status, 206)
        self.assertEqual(body, fixture[-7:])
        status, _, _ = self.request('GET', url, headers={'Range': 'bytes=9999-'}, raw=True)
        self.assertEqual(status, 416)
        status, _, _ = self.request('GET', '/api/local/file?id=not-registered')
        self.assertEqual(status, 422)
        self.remote.assert_not_called()

    def test_mutation_rejects_cross_origin_and_non_json_before_changing_state(self):
        self.request('GET', '/api/state')
        before = copy.deepcopy(self.state)
        status, _, _ = self.request('POST', '/api/settings', {'show_url': True}, headers={'Origin': 'https://other.example'})
        self.assertEqual(status, 403)
        status, _, _ = self.request('POST', '/api/settings', {'show_url': True}, headers={'Content-Type': 'text/plain'})
        self.assertEqual(status, 403)
        self.assertEqual(self.state, before)


if __name__ == '__main__':
    unittest.main()
