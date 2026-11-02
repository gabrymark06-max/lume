import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import server as app


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.channel = {'id': 'sc', 'name': 'Canale', 'url': 'https://cinema.example/'}

    def test_article_import_excludes_affiliate_and_related_links(self):
        article = '''<h2>Come navigare</h2><a>https://vpn.example/</a>
        <h2>Lista Canali Veezie</h2><ul><li>https://film.example/</li><li>https://serie.example/</li></ul>
        <h2>Come aggiungere</h2><a>https://store.example/</a>'''
        self.assertEqual(app.list_candidates(article, app.LIST_URL), ['https://film.example/', 'https://serie.example/'])

    def test_cards_remain_channel_media_and_are_deduplicated(self):
        markup = '''<a href="/titles/42-film"><img src="/logo.svg" alt="Logo"></a>
        <a href="/titles/42-film" data-title="Il film" data-year="2026"><img src="/cover.jpg"></a>
        <a href="/titles/42-film" data-title="Il film"><img src="/other.jpg"></a>
        <a href="https://ads.example/titles/1-ad" data-title="Annuncio"><img src="/ad.jpg"></a>'''
        items, _ = app.parse_cards(markup, self.channel['url'], self.channel)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['title'], 'Il film')
        self.assertEqual(items[0]['poster'], 'https://cinema.example/cover.jpg')

    def test_hydration_is_decoded_as_data_not_executed(self):
        value = '7:{"seasons":[{"number":1,"episodes":[{"number":2,"title":"Il ritorno"}]}]}'
        script = '<script>self.__next_f.push([1,' + json.dumps(value) + '])</script>'
        decoded = app.hydration(script)
        self.assertEqual(app.js_property(decoded, 'seasons')[0]['episodes'][0]['number'], 2)

    def test_player_literal_is_decoded_without_eval(self):
        import base64
        key = b'test'
        source = b'video.currentSrc="https://cdn.example/master.m3u8?token=fixture";'
        encoded = base64.b64encode(bytes(v ^ key[i % len(key)] for i, v in enumerate(source))).decode()
        markup = "<script>var z='test', d=atob('" + encoded + "');</script>"
        links = app.parse_vidxgo(markup)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]['url'], 'https://cdn.example/master.m3u8?token=fixture')
        self.assertEqual(links[0]['kind'], 'hls')

    def test_trailer_not_returned_as_the_film(self):
        markup = '<iframe src="https://host.example/42?content=trailer"></iframe><iframe src="https://host.example/42"></iframe>'
        self.assertEqual([x['url'] for x in app.extract_sources(markup, self.channel['url'])], ['https://host.example/42'])

    def test_private_network_is_rejected(self):
        for url in ['http://127.0.0.1/', 'http://169.254.169.254/latest/', 'file:///C:/Windows/win.ini', 'https://user:password@example.com/']:
            with self.subTest(url=url), self.assertRaises(app.SourceError):
                app.public_url(url)

    def test_search_url_and_no_unrelated_home_results(self):
        channel = {'id': 'html', 'name': 'Catalogo HTML', 'url': 'https://altadefinizionex.example/'}
        markup = '<a href="/titles/1-matrix" data-title="Matrix"><img src="/p.jpg"></a><a href="/titles/2-other" data-title="Altro"><img src="/q.jpg"></a>'
        with patch.object(app, 'fetch', return_value=(markup, channel['url'], 'text/html')) as fetch:
            result = app.catalog(channel, query='Matrix')
        self.assertIn('search=Matrix', fetch.call_args.args[0])
        self.assertEqual([x['title'] for x in result['items']], ['Matrix'])

    def test_forbidden_embed_is_reported_not_assumed_playable(self):
        with patch.object(app, 'public_url', return_value='https://host.example/embed'), patch.object(app, 'fetch', side_effect=app.SourceError('HTTP 403')):
            with self.assertRaisesRegex(app.SourceError, '403'):
                app.resolve('https://host.example/embed')

    def test_atomic_save_preserves_unicode_and_state(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'DATA', Path(tmp)), patch.object(app, 'STATE_FILE', Path(tmp) / 'state.json'), patch.object(app, 'STATE', {'channels': [], 'favorites': [{'title': 'Città'}], 'progress': {}}):
            app.save_state()
            self.assertEqual(app.load_state()['favorites'][0]['title'], 'Città')
            self.assertFalse((Path(tmp) / 'state.tmp').exists())

    def test_hls_relative_playlist_segment_and_key_use_local_proxy(self):
        from urllib.parse import parse_qs, urlsplit
        manifest = '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="keys/key.bin"\n#EXTINF:6,\nsegment01.ts?sig=a%2Bb\n'
        result = app.rewrite_hls(manifest, 'https://cdn.example/video/master.m3u8', 'https://player.example/')
        self.assertIn('URI="/api/media?', result)
        segment = result.splitlines()[-1]
        args = parse_qs(urlsplit(segment).query)
        self.assertEqual(args['url'], ['https://cdn.example/video/segment01.ts?sig=a%2Bb'])
        self.assertEqual(args['referer'], ['https://player.example/'])


if __name__ == '__main__':
    unittest.main()
