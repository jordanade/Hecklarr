import copy
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from load_app import loadApp


app = loadApp('hecklarr_test_downloads')


class DownloadStateTest(unittest.TestCase):
    def setUp(self):
        self.movie = {'id': 10, 'tmdbId': 100, 'hasFile': False, 'monitored': True, 'status': 'released'}

    def test_file_availability_wins_over_a_completed_or_upgrade_queue_item(self):
        self.movie['hasFile'] = True
        for status in ['completed', 'downloading', 'warning']:
            self.assertEqual('downloaded', app.movieDownloadState(self.movie, [{'status': status}]))

    def test_not_added_missing_unmonitored_and_unreleased_are_distinct(self):
        self.assertEqual('not-in-radarr', app.movieDownloadState(None, []))
        self.assertEqual('missing', app.movieDownloadState(self.movie, []))
        self.assertEqual('unmonitored', app.movieDownloadState({**self.movie, 'monitored': False}, []))
        for status in ['announced', 'inCinemas']:
            self.assertEqual('unreleased', app.movieDownloadState({**self.movie, 'status': status}, []))

    def test_queue_states_do_not_mistake_a_completed_download_for_an_imported_file(self):
        cases = [({'status': 'downloading'}, 'downloading'),
                 ({'status': 'queued', 'trackedDownloadState': 'downloading'}, 'queued'),
                 ({'status': 'paused'}, 'paused'),
                 ({'status': 'completed'}, 'importing'),
                 ({'status': 'completed', 'trackedDownloadState': 'importBlocked'}, 'import-blocked'),
                 ({'status': 'failed'}, 'failed'),
                 ({'status': 'warning'}, 'warning'),
                 ({'status': 'downloadClientUnavailable'}, 'client-unavailable')]
        for row, expected in cases:
            with self.subTest(row=row):
                self.assertEqual(expected, app.movieDownloadState(self.movie, [row]))

    def test_multiple_queue_items_have_deterministic_precedence(self):
        rows = [{'status': 'queued'}, {'status': 'downloading'}]
        self.assertEqual('downloading', app.movieDownloadState(self.movie, rows))
        self.assertEqual('downloading', app.movieDownloadState(self.movie, list(reversed(rows))))
        rows.append({'status': 'completed', 'trackedDownloadState': 'importBlocked'})
        self.assertEqual('import-blocked', app.movieDownloadState(self.movie, rows))

    def test_batch_fetch_reads_all_queue_pages_and_only_returns_catalog_ids(self):
        calls = []
        def fetch(path, settings):
            calls.append(path)
            if path == 'movie':
                return [self.movie, {'id': 11, 'tmdbId': 101, 'hasFile': True}, {'id': 999, 'tmdbId': 999}]
            if 'page=1&' in path:
                return {'totalRecords': 2, 'records': [{'movieId': 11, 'status': 'completed'}]}
            return {'totalRecords': 2, 'records': [{'movieId': 10, 'status': 'downloading'}]}
        self.assertEqual({'100': 'downloading', '101': 'downloaded', '102': 'not-in-radarr'},
                         app.fetchDownloadStatuses({}, {100, 101, 102}, fetch=fetch))
        self.assertEqual(3, len(calls))
        self.assertIn('page=2&', calls[1])
        self.assertEqual('movie', calls[-1])

    def test_incomplete_queue_is_not_silently_reported_as_missing(self):
        def fetch(path, settings):
            return [self.movie] if path == 'movie' else {'totalRecords': 1, 'records': []}
        with self.assertRaisesRegex(ValueError, 'completely'):
            app.fetchDownloadStatuses({}, {100}, fetch=fetch)

    def test_empty_catalog_does_not_query_radarr(self):
        with patch.object(app, 'radarr') as fetch:
            self.assertEqual({}, app.fetchDownloadStatuses({}, set(), fetch=fetch))
            fetch.assert_not_called()


class StatusCacheTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.old = {'items': {'100': 'downloaded'}, 'updatedAt': '2026-10-14T10:00:00+00:00', 'lastError': None}
        self.patches = [patch.object(app, 'STATE_DIR', Path(self.directory.name)),
                        patch.object(app, 'SETTINGS', {'apiKey': 'cache-key', 'radarrUrl': 'http://radarr:7878',
                                                       'radarrApiKey': 'private-radarr-key', 'comedians': []}),
                        patch.object(app, 'SNAPSHOT', {'updatedAt': app.now(), 'items': [{'tmdbId': 100}]}),
                        patch.object(app, 'DOWNLOAD_STATUSES', copy.deepcopy(self.old)),
                        patch.object(app, 'DOWNLOAD_REFRESH', threading.Event())]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def test_failed_async_update_preserves_last_successful_data_and_timestamp(self):
        with patch.object(app, 'fetchDownloadStatuses', side_effect=ValueError('Radarr returned HTTP 503')):
            app.updateDownloadStatuses()
        self.assertEqual(self.old['items'], app.DOWNLOAD_STATUSES['items'])
        self.assertEqual(self.old['updatedAt'], app.DOWNLOAD_STATUSES['updatedAt'])
        self.assertIsNotNone(app.DOWNLOAD_STATUSES['lastError'])

    def test_async_refresh_does_not_replace_cache_until_it_finishes(self):
        entered = threading.Event()
        release = threading.Event()
        def fetch(settings, movie_ids):
            entered.set()
            release.wait(timeout=5)
            return {'100': 'downloading'}
        with patch.object(app, 'fetchDownloadStatuses', side_effect=fetch):
            thread = threading.Thread(target=app.updateDownloadStatuses)
            thread.start()
            try:
                self.assertTrue(entered.wait(timeout=5))
                self.assertEqual(self.old, app.cachedDownloadStatuses())
            finally:
                release.set()
                thread.join(timeout=5)
        self.assertEqual({'100': 'downloading'}, app.cachedDownloadStatuses()['items'])
        self.assertIsNone(app.cachedDownloadStatuses()['lastError'])

    def test_changing_connection_clears_cache_and_discards_inflight_old_results(self):
        def fetch(settings, movie_ids):
            app.saveSettings({'radarrUrl': 'http://other-radarr:7878'})
            return {'100': 'missing'}
        with patch.object(app, 'fetchDownloadStatuses', side_effect=fetch):
            app.updateDownloadStatuses()
        self.assertEqual({'items': {}, 'updatedAt': None, 'lastError': None}, app.DOWNLOAD_STATUSES)
        self.assertTrue(app.DOWNLOAD_REFRESH.is_set())

    def test_cached_output_omits_removed_titles_and_private_radarr_data(self):
        app.DOWNLOAD_STATUSES['items']['999'] = 'missing'
        result = app.cachedDownloadStatuses()
        self.assertEqual({'100': 'downloaded'}, result['items'])
        self.assertNotIn('private-radarr-key', json.dumps(result))

    def test_status_endpoints_read_cache_without_waiting_on_radarr_and_require_auth(self):
        server = app.LimitedThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = 'http://127.0.0.1:' + str(server.server_port)
        try:
            with patch.object(app, 'fetchDownloadStatuses', side_effect=AssertionError('Must not fetch during GET')):
                for path in ['/api/download-status', '/api/status']:
                    request = urllib.request.Request(base + path, headers={'X-Api-Key': 'cache-key'})
                    with urllib.request.urlopen(request, timeout=2) as response:
                        data = json.load(response)
                    cache = data['downloadStatuses'] if path == '/api/status' else data
                    self.assertEqual(self.old, cache)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(base + '/api/download-status', timeout=2)
                self.assertEqual(401, error.exception.code)
                error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    unittest.main()
