"""Pruebas del cintillo con fuentes simuladas, sin publicar ni consumir APIs."""
import datetime
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('news', Path(__file__).with_name('sync_live_news.py'))
news = importlib.util.module_from_spec(spec)
spec.loader.exec_module(news)
NOW = datetime.datetime(2026, 11, 16, 12, tzinfo=datetime.timezone.utc)


def candidate():
    return {
        'id': 1, 'title': 'La universidad inaugura un laboratorio de investigación solar',
        'origin': 'TECNOLOGÍA', 'source': 'Medio de prueba', 'lang': 'es',
        'publishedAt': NOW.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'age_hours': 0, 'link': 'https://example.org/noticia', 'summary': '',
    }


class NewsPipelineTests(unittest.TestCase):
    def setUp(self):
        cache = patch.object(news, 'write_ticker_cache')
        self.cache_writer = cache.start()
        self.addCleanup(cache.stop)


    def test_rest_transport_publishes_only_the_news_node(self):
        source = candidate()
        items, _ = news.build_fallback_items([source], [])
        with patch.dict(os.environ, NEWS_PUBLISH_TRANSPORT='rest'), \
                patch.object(news.urllib.request, 'urlopen', return_value=io.BytesIO(b'{}')) as request, \
                patch.object(news.subprocess, 'run') as admin:
            news.upload_to_firebase(items)
            sent = request.call_args.args[0]
            self.assertTrue(sent.full_url.endswith('/radio_state/news.json'))
            payload = json.loads(sent.data)
            self.assertEqual(payload['items'][0]['url'], source['link'])
            self.assertGreater(payload['updatedAt'], 0)
            admin.assert_not_called()

    def test_gaming_has_its_own_feeds_and_reclassifies_legacy_titles(self):
        for feed in news.FEEDS:
            if feed[1] in {'Eurogamer.es', 'Gamereactor.es'}:
                self.assertEqual(feed[0], 'GAMING')
        self.assertEqual(news.classify_news_category(
            'CULTURA & MÚSICA', 'Halo: Campaign Evolved añade un modo Firefight'),
            'GAMING')
        self.assertEqual(news.classify_news_category(
            'CULTURA & MÚSICA', 'Beyoncé interpreta Halo en su concierto', 'Jenesaispop'),
            'CULTURA & MÚSICA')

    def test_gaming_category_survives_gemini_and_rss_fallback(self):
        source = {**candidate(), 'origin': 'CULTURA & MÚSICA',
                  'source': 'Gamereactor.es',
                  'title': 'Halo: Campaign Evolved añade el modo Firefight gratuito para cuatro jugadores este invierno'}
        items, _ = news.validate_gemini_items(
            {'news': [{'source_id': 1, 'category': 'CULTURA & MÚSICA'}]}, [source], [])
        fallback, _ = news.build_fallback_items([source], [])
        self.assertEqual(items[0]['category'], 'GAMING')
        self.assertEqual(fallback[0]['category'], 'GAMING')
        self.assertEqual(items[0]['title'], source['title'])

    def test_gemini_cannot_insert_facts_or_change_the_original_category(self):
        source = candidate()
        items, _ = news.validate_gemini_items({
            'news': [{'source_id': 1, 'category': 'DEPORTES',
                      'title': 'La universidad invierte 500 millones en Caracas'}],
            'efemerides': None,
        }, [source], [])
        self.assertEqual(items[0]['title'], source['title'])
        self.assertEqual(items[0]['category'], source['origin'])
        self.assertEqual(items[0]['url'], source['link'])
        self.assertEqual(items[0]['expiresAt'], '2026-11-18T06:00:00Z')
        self.assertEqual(news.validate_gemini_items({'news': None}, [], []), ([], []))

    def test_efemerides_keep_original_text_and_expire_at_local_midnight(self):
        efem = {'eid': 'E1', 'year': 2004, 'text': 'En 2004, Valve lanzó Half-Life 2 para PC'}
        _, items = news.validate_gemini_items({'efemerides': [
            {'source_id': 'E1', 'title': 'En 2004, Valve vendió mil millones de juegos'}
        ]}, [], [efem])
        self.assertEqual(items[0]['title'], efem['text'])
        self.assertEqual(news.efemeride_expiry(NOW.date()), '2026-11-17T04:00:00Z')

    def test_new_titles_take_priority_and_current_news_remains_available(self):
        source = candidate()
        source['pub_dt'] = NOW
        feed = ('TECNOLOGÍA', 'Prueba', 'https://example.org/feed', 42, 'es')
        with patch.object(news, 'FEEDS', [feed]), patch.object(news, 'fetch_single_feed', return_value=[source]):
            self.assertEqual(len(news.collect_candidates(NOW, {news.article_id(source): NOW.timestamp()})), 1)
            self.assertEqual(len(news.collect_candidates(NOW, {})), 1)
        fresh = {**source, 'title': 'El instituto estrena una biblioteca científica para estudiantes'}
        with patch.object(news, 'FEEDS', [feed]), patch.object(news, 'fetch_single_feed', return_value=[source, fresh]):
            result = news.collect_candidates(NOW, {news.article_id(source): NOW.timestamp()})
            self.assertEqual(result[0]['title'], fresh['title'])


    def test_history_keeps_only_the_last_six_hours(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, NEWS_STATE_DIR=folder):
            news.save_news_state('history.json', {
                'new': NOW.timestamp() - 100, 'old': NOW.timestamp() - 7 * 3600,
            })
            self.assertEqual(news.load_news_history(NOW), {'new': NOW.timestamp() - 100})

    def test_feed_health_reports_accepted_items_and_failures(self):
        feed = ('TECNOLOGÍA', 'Prueba', 'https://example.org/feed', 42, 'es')
        raw = f'<rss><channel><item><title>{candidate()["title"]}</title><pubDate>Mon, 16 Nov 2026 12:00:00 GMT</pubDate><link>https://example.org/noticia</link></item></channel></rss>'
        health = {}
        with patch.object(news.urllib.request, 'urlopen', return_value=io.BytesIO(raw.encode())):
            self.assertEqual(len(news.fetch_single_feed(feed, NOW, health)), 1)
        self.assertEqual(health['Prueba']['accepted'], 1)
        with patch.object(news.urllib.request, 'urlopen', side_effect=OSError('caído')):
            self.assertEqual(news.fetch_single_feed(feed, NOW, health), [])
        self.assertFalse(health['Prueba']['ok'])

    def test_failed_publication_does_not_mark_unpublished_news_as_seen(self):
        item = {**candidate(), **news.news_metadata(candidate()), 'category': 'TECNOLOGÍA'}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, NEWS_STATE_DIR=folder), \
                patch.object(news, 'fetch_fresh_ticker', return_value=[item]), \
                patch.object(news, 'upload_to_firebase', side_effect=OSError('sin conexión')):
            with self.assertRaises(OSError):
                news.run_once()
            self.assertFalse(Path(folder, 'history.json').exists())

    def test_empty_batch_clears_stale_server_data_and_dry_run_never_writes(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, NEWS_STATE_DIR=folder), \
                patch.object(news, 'fetch_fresh_ticker', return_value=[]), \
                patch.object(news, 'upload_to_firebase') as upload:
            news.run_once(dry_run=True)
            upload.assert_not_called()
            self.assertEqual(list(Path(folder).iterdir()), [])
            news.run_once()
            upload.assert_called_once_with([])
            self.assertEqual(json.loads(Path(folder, 'history.json').read_text()), {})


if __name__ == '__main__':
    unittest.main()
