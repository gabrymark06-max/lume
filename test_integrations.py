import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import integrations as mod


class UserError(Exception):
    pass


class Response:
    def __init__(self, value, status=200):
        self.value, self.status_code, self.closed = value, status, False

    def json(self):
        return self.value

    def close(self):
        self.closed = True


def unit_cipher(value, decrypt=False):
    # Codec di test soltanto; non è accessibile dal prodotto come fallback DPAPI.
    return bytes(x ^ 0xA7 for x in value)


PUBLIC_DNS = [(2, 1, 6, '', ('93.184.216.34', 443))]


class IntegrationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.request = Mock()
        self.protection = patch.object(mod, '_dpapi', side_effect=unit_cipher)
        self.protection.start()
        self.addCleanup(self.protection.stop)
        self.app = mod.Integrations({'data_dir': Path(self.temp.name), 'Error': UserError, 'request': self.request})

    def connect_rd(self):
        self.request.return_value = Response({'id': 42, 'username': 'Lettore', 'type': 'premium'})
        return self.app.connect('rd', {'token': 'fixture-token-not-real'})

    def test_initial_status_never_contacts_network(self):
        status = self.app.dispatch('GET', '/api/integrations')
        self.assertEqual(len(status['services']), 3)
        self.assertTrue(all(not s['connected'] for s in status['services']))
        self.request.assert_not_called()

    def test_validated_token_is_protected_and_not_returned(self):
        result = self.connect_rd()
        self.assertTrue(result['service']['connected'])
        self.assertNotIn('fixture-token-not-real', json.dumps(result))
        self.assertNotIn(b'fixture-token-not-real', self.app.path.read_bytes())
        self.assertEqual(self.app._read()['rd']['token'], 'fixture-token-not-real')
        method, url = self.request.call_args.args
        self.assertEqual((method, url), ('GET', mod.BASE['rd'] + '/user'))
        self.assertFalse(self.request.call_args.kwargs['allow_redirects'])

    def test_invalid_token_is_not_saved_or_echoed(self):
        token = 'fixture-invalid-token'
        self.request.return_value = Response({'error': token}, 401)
        with self.assertRaises(UserError) as caught:
            self.app.connect('rd', {'token': token})
        self.assertNotIn(token, str(caught.exception))
        self.assertFalse(self.app.path.exists())

    def test_redirect_does_not_forward_bearer_to_other_host(self):
        self.request.return_value = Response({'location': 'https://other.example/'}, 302)
        with self.assertRaises(UserError):
            self.app.connect('rd', {'token': 'fixture-token'})
        self.assertEqual(self.request.call_count, 1)
        self.assertFalse(self.app.path.exists())

    def test_trakt_requires_own_client_id_before_network(self):
        with self.assertRaises(UserError):
            self.app.connect('trakt', {'token': 'fixture-oauth-token'})
        self.request.assert_not_called()

    def test_trakt_read_only_validation_then_explicit_pause(self):
        self.request.return_value = Response({'user': {'username': 'utente'}})
        self.app.connect('trakt', {'token': 'fixture-oauth-token', 'client_id': 'fixture-own-client'})
        self.assertEqual(self.request.call_args.args[:2], ('GET', mod.BASE['trakt'] + '/users/settings'))
        self.app.status()
        self.assertEqual(self.request.call_count, 1)
        self.request.return_value = Response({'action': 'pause', 'progress': 25})
        result = self.app.sync_trakt({'imdb': 'tt0133093', 'kind': 'movie'}, 25, 100)
        self.assertEqual(result['progress'], 25)
        self.assertEqual(self.request.call_args.args[:2], ('POST', mod.BASE['trakt'] + '/scrobble/pause'))
        body = self.request.call_args.kwargs['json']
        self.assertEqual(body['movie']['ids']['imdb'], 'tt0133093')
        self.assertNotIn('sharing', body)
        self.assertNotIn('message', body)

    def test_real_debrid_resolve_is_explicit_and_returns_only_direct_source(self):
        self.connect_rd()
        self.request.return_value = Response({'download': 'https://cdn.example/movie.mp4', 'filename': 'Film.mp4'})
        with patch.object(mod.socket, 'getaddrinfo', return_value=PUBLIC_DNS):
            result = self.app.resolve('rd', 'https://host.example/file')
        self.assertEqual(result['sources'][0]['kind'], 'video')
        self.assertEqual(self.request.call_args.args[:2], ('POST', mod.BASE['rd'] + '/unrestrict/link'))
        self.assertEqual(self.request.call_args.kwargs['data'], {'link': 'https://host.example/file'})
        self.assertNotIn('token', json.dumps(result))

    def test_private_or_credential_url_never_leaves_client(self):
        for url in ['http://127.0.0.1/test', 'https://name:password@example.com/file', 'file:///C:/test.mp4']:
            with self.subTest(url=url), self.assertRaises(UserError):
                self.app.resolve('rd', url)
        self.request.assert_not_called()

    def test_service_cannot_return_api_token_as_player_url(self):
        self.connect_rd()
        self.request.return_value = Response({'download': 'https://cdn.example/movie.mp4?token=fixture-token-not-real', 'filename': 'Film.mp4'})
        with patch.object(mod.socket, 'getaddrinfo', return_value=PUBLIC_DNS), self.assertRaises(UserError) as caught:
            self.app.resolve('rd', 'https://host.example/file')
        self.assertNotIn('fixture-token-not-real', str(caught.exception))

    def test_torbox_uses_cache_only_and_returns_video_file(self):
        self.request.return_value = Response({'success': True, 'data': {'id': 1, 'email': 'account@example.com'}})
        self.app.connect('torbox', {'token': 'fixture-torbox-token'})
        self.request.side_effect = [
            Response({'success': True, 'data': {'webdownload_id': 123}}),
            Response({'success': True, 'data': [{'id': 123, 'download_finished': True, 'files': [{'id': 0, 'name': 'Film.mp4'}]}]}),
            Response({'success': True, 'data': 'https://cdn.example/film.mp4'}),
        ]
        with patch.object(mod.socket, 'getaddrinfo', return_value=PUBLIC_DNS):
            result = self.app.resolve('torbox', 'https://host.example/file')
        self.assertEqual(len(result['sources']), 1)
        create = self.request.call_args_list[-3]
        self.assertEqual(create.kwargs['data']['add_only_if_cached'], 'true')
        self.assertEqual(self.request.call_args.args[:2], ('GET', mod.BASE['torbox'] + '/webdl/requestdl'))
        self.assertNotIn('fixture-torbox-token', json.dumps(result))

    def test_torbox_not_cached_is_not_reported_as_playable(self):
        self.request.return_value = Response({'success': True, 'data': {'id': 1}})
        self.app.connect('torbox', {'token': 'fixture-torbox-token'})
        self.request.return_value = Response({'success': False, 'error': 'NOT_CACHED'})
        with patch.object(mod.socket, 'getaddrinfo', return_value=PUBLIC_DNS), self.assertRaises(UserError):
            self.app.resolve('torbox', 'https://host.example/file')

    def test_disconnect_has_no_remote_side_effect(self):
        self.connect_rd()
        self.request.reset_mock()
        result = self.app.dispatch('DELETE', '/api/integrations/rd')
        self.assertFalse(result['service']['connected'])
        self.request.assert_not_called()

    def test_protection_failure_has_no_plaintext_fallback(self):
        self.request.return_value = Response({'id': 1, 'username': 'utente'})
        with patch.object(mod, '_dpapi', side_effect=RuntimeError('unavailable')), self.assertRaises(UserError):
            self.app.connect('rd', {'token': 'fixture-secret'})
        self.assertFalse(self.app.path.exists())

    def test_storage_inside_repo_is_rejected(self):
        with self.assertRaises(UserError):
            mod.Integrations({'data_dir': Path(__file__).parent / 'tokens', 'Error': UserError})


class WindowsProtectionTests(unittest.TestCase):
    @unittest.skipUnless(os.name == 'nt', 'DPAPI disponibile solo su Windows')
    def test_dpapi_actual_roundtrip_of_synthetic_secret(self):
        raw = b'{"fixture":"not-a-real-token"}'
        encrypted = mod._dpapi(raw)
        self.assertNotIn(raw, encrypted)
        self.assertEqual(mod._dpapi(encrypted, decrypt=True), raw)


if __name__ == '__main__':
    unittest.main()
