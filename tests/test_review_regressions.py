"""Regression tests for the October 2026 code review findings."""

import base64
import copy
import email.message
import hashlib
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

from load_app import loadApp


app = loadApp('hecklarr_test_review_regressions')
# loadApp puts src/ on the path, so the shared client module imports afterwards.
from hecklarr import clients  # noqa: E402

SHARED_MOVIE = {
    'id': 500, 'title': 'Alpha and Beta Live', 'runtime': 60, 'release_date': '2024-05-01',
    'genres': [{'id': 35}], 'keywords': {'keywords': [{'id': 9716}]},
    'credits': {'cast': [{'id': 1, 'character': 'Self', 'order': 0},
                         {'id': 2, 'character': 'Self', 'order': 0}], 'crew': []},
}


def sharedFetch(calls):
    def fetch(path, settings):
        calls.append(path)
        if path in ['person/1', 'person/2']:
            return {'name': 'Alpha' if path == 'person/1' else 'Beta'}
        if path.endswith('/movie_credits'):
            return {'cast': [{'id': 500}]}
        if path.startswith('movie/500'):
            return SHARED_MOVIE
        raise AssertionError('Unexpected TMDB path: ' + path)
    return fetch


class SharedSpecialTest(unittest.TestCase):
    def setUp(self):
        self.saved = (app.SETTINGS, app.SNAPSHOT, app.STATE_DIR)
        self.directory = tempfile.TemporaryDirectory()
        app.STATE_DIR = Path(self.directory.name)
        self.settings = {'comedians': [{'id': 1, 'includeIds': [], 'excludeIds': []},
                                       {'id': 2, 'includeIds': [], 'excludeIds': []}],
                         'excludedMovieIds': []}
        self.calls = []
        app.SETTINGS = {**self.settings, 'radarrUrl': 'http://radarr', 'radarrApiKey': 'key'}
        app.SNAPSHOT = app.buildSnapshot(self.settings, {}, sharedFetch(self.calls))

    def tearDown(self):
        app.SETTINGS, app.SNAPSHOT, app.STATE_DIR = self.saved
        self.directory.cleanup()

    def test_special_qualifying_for_two_comedians_is_owned_by_both_and_fetched_once(self):
        self.assertEqual([[1, 2]], [row['personIds'] for row in app.SNAPSHOT['items']])
        self.assertEqual([['Alpha', 'Beta']], [row['comedians'] for row in app.SNAPSHOT['items']])
        self.assertEqual(1, sum(path.startswith('movie/500') for path in self.calls))
        self.assertEqual([1, 2], sorted(row['personId'] for row in app.SNAPSHOT['reviewed']))

    def test_removing_one_owner_keeps_shared_special_in_feed_and_radarr(self):
        calls = []
        def fake_radarr(path, settings, body=None, method=None):
            calls.append((path, method))
            if path == 'movie':
                return [{'id': 9, 'tmdbId': 500, 'hasFile': True}]
        with patch.object(app, 'radarr', side_effect=fake_radarr):
            result = app.removeComedian(2, True)
        self.assertEqual({'removedFromRadarr': 0, 'hadFiles': 0, 'trackedCount': 0, 'sharedCount': 1}, result)
        self.assertNotIn(('movie/9?deleteFiles=true', 'DELETE'), calls)
        self.assertEqual([([1], ['Alpha'])],
                         [(row['personIds'], row['comedians']) for row in app.SNAPSHOT['items']])

    def test_removing_the_last_owner_deletes_the_special(self):
        app.SNAPSHOT['items'][0] = app.withoutOwner(app.SNAPSHOT['items'][0], 2)
        calls = []
        def fake_radarr(path, settings, body=None, method=None):
            calls.append((path, method))
            if path == 'movie':
                return [{'id': 9, 'tmdbId': 500, 'hasFile': True}]
        with patch.object(app, 'radarr', side_effect=fake_radarr):
            result = app.removeComedian(1, True)
        self.assertEqual(1, result['removedFromRadarr'])
        self.assertIn(('movie/9?deleteFiles=true', 'DELETE'), calls)
        self.assertEqual([], app.SNAPSHOT['items'])

    def test_retention_applies_to_every_owner(self):
        previous = {'items': [{'tmdbId': 500, 'personIds': [1, 2], 'comedians': ['Alpha', 'Beta'],
                               'title': 'Alpha and Beta Live', 'year': '2024'}]}
        settings = {'comedians': [{'id': 2, 'includeIds': [], 'excludeIds': []}]}
        def fetch(path, settings):
            if path == 'person/2':
                return {'name': 'Beta'}
            if path == 'person/2/movie_credits':
                return {'cast': []}
            return {**SHARED_MOVIE, 'credits': {'cast': [], 'crew': []}}
        result = app.buildSnapshot(settings, previous, fetch)
        self.assertEqual([[2]], [row['personIds'] for row in result['items']])
        self.assertIn('Retained', result['items'][0]['reason'])

    def test_legacy_single_owner_snapshot_is_migrated(self):
        legacy = {'items': [{'tmdbId': 7, 'personId': 3, 'comedian': 'Gamma', 'title': 'Old'}]}
        app.migrateSnapshot(legacy)
        self.assertEqual([{'tmdbId': 7, 'personIds': [3], 'comedians': ['Gamma'], 'title': 'Old'}], legacy['items'])

    def test_public_settings_name_every_owner(self):
        app.SNAPSHOT['people'] = []
        names = {row['id']: row['name'] for row in app.publicSettings()['comedians']}
        self.assertEqual({1: 'Alpha', 2: 'Beta'}, names)


class ClientRetryTest(unittest.TestCase):
    def error(self, url, code, retry_after=None):
        headers = email.message.Message()
        if retry_after is not None:
            headers['Retry-After'] = retry_after
        return urllib.error.HTTPError(url, code, 'Test error', headers, None)

    def opener(self, responses):
        calls = []
        class Opener:
            def open(self, request, timeout):
                calls.append(request.get_method())
                response = responses.pop(0)
                if isinstance(response, Exception):
                    raise response
                class Body:
                    def __enter__(self): return self
                    def __exit__(self, *args): return False
                    def read(self): return response
                return Body()
        return Opener(), calls

    def test_retry_after_date_or_negative_value_falls_back_to_default_delay(self):
        self.assertEqual(2, clients.retryDelay('Wed, 21 Oct 2026 07:28:00 GMT'))
        self.assertEqual(0, clients.retryDelay('-5'))
        self.assertEqual(10, clients.retryDelay('3600'))
        self.assertEqual(2, clients.retryDelay(None))

    def test_get_with_http_date_retry_after_is_retried(self):
        opener, calls = self.opener([self.error('http://radarr/x', 503, 'Wed, 21 Oct 2026 07:28:00 GMT'), b'{"ok": true}'])
        with patch.object(clients.time, 'sleep') as sleep:
            self.assertEqual({'ok': True}, clients.requestJson('http://radarr/x', 'key', opener=opener))
        self.assertEqual(['GET', 'GET'], calls)
        sleep.assert_called_once_with(2)

    def test_post_is_not_retried_after_a_server_error_or_timeout(self):
        for failure in [self.error('http://radarr/importlist', 503), TimeoutError()]:
            with self.subTest(failure=type(failure).__name__):
                opener, calls = self.opener([failure, b'{}'])
                with patch.object(clients.time, 'sleep'), self.assertRaises(ValueError):
                    clients.requestJson('http://radarr/importlist', 'key', {'name': 'list'}, opener=opener)
                self.assertEqual(['POST'], calls)

    def test_put_and_delete_are_still_retried(self):
        for method in ['PUT', 'DELETE']:
            with self.subTest(method=method):
                opener, calls = self.opener([self.error('http://radarr/x', 500), b''])
                with patch.object(clients.time, 'sleep'):
                    clients.requestJson('http://radarr/x', 'key', {} if method == 'PUT' else None, method, opener=opener)
                self.assertEqual([method, method], calls)


class ProxyAndLockoutTest(unittest.TestCase):
    def handler(self, peer, forwarded=None):
        handler = app.Handler.__new__(app.Handler)
        handler.client_address = (peer, 12345)
        handler.headers = {'X-Forwarded-For': forwarded} if forwarded else {}
        return handler

    def test_forwarded_for_is_ignored_unless_peer_is_a_trusted_proxy(self):
        with patch.object(app, 'TRUSTED_PROXIES', []):
            self.assertEqual('10.0.0.2', self.handler('10.0.0.2', '203.0.113.9').clientAddress())
        with patch.object(app, 'TRUSTED_PROXIES', app.parseNetworks('10.0.0.0/24')):
            self.assertEqual('203.0.113.9', self.handler('10.0.0.2', '203.0.113.9').clientAddress())
            # A client cannot spoof its address by sending its own X-Forwarded-For entry.
            self.assertEqual('203.0.113.9', self.handler('10.0.0.2', '198.51.100.1, 203.0.113.9, 10.0.0.3').clientAddress())
            self.assertEqual('10.0.0.2', self.handler('10.0.0.2').clientAddress())

    def test_invalid_trusted_proxy_setting_fails_loudly(self):
        with self.assertRaisesRegex(ValueError, 'TRUSTED_PROXIES'):
            app.parseNetworks('10.0.0.0/24, not-an-address')

    def test_many_failing_addresses_cannot_lock_out_a_new_address(self):
        stamp = time.time()
        failures = {f'192.0.2.{index % 250}.{index}': [stamp + index] for index in range(app.MAX_TRACKED_ADDRESSES)}
        with patch.object(app, 'FAILURES', failures):
            self.assertTrue(self.handler('127.0.0.1').reserveLoginAttempt('198.51.100.7'))
            self.assertIn('198.51.100.7', app.FAILURES)
            self.assertNotIn('192.0.2.0.0', app.FAILURES)
            self.assertEqual(app.MAX_TRACKED_ADDRESSES, len(app.FAILURES))


class HardeningHttpTest(unittest.TestCase):
    def setUp(self):
        self.saved = (app.SETTINGS, app.SNAPSHOT, app.STATE_DIR, app.SESSIONS, app.LAST_ERROR, app.FAILURES,
                      app.SETUP_CODE)
        self.directory = tempfile.TemporaryDirectory()
        app.STATE_DIR = Path(self.directory.name)
        salt = b'regression-salt'
        hashed = hashlib.scrypt(b'test-password', salt=salt, n=16384, r=8, p=1, dklen=64)
        app.SETTINGS = {'apiKey': 'private-api-key', 'feedKey': 'private-feed-key', 'authUser': 'tester',
                        'authHash': 'scrypt$16384$8$1$' + base64.b64encode(salt).decode() + '$'
                                    + base64.b64encode(hashed).decode(),
                        'tmdbApiKey': 'private-tmdb-key', 'comedians': []}
        app.SNAPSHOT = {}
        app.SESSIONS = {}
        app.FAILURES = {}
        app.LAST_ERROR = 'Radarr returned HTTP 401'
        app.SETUP_CODE = 'right-code'
        self.server = app.LimitedThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()
        (app.SETTINGS, app.SNAPSHOT, app.STATE_DIR, app.SESSIONS, app.LAST_ERROR, app.FAILURES,
         app.SETUP_CODE) = self.saved

    def request(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, headers=headers or {})
        return urllib.request.urlopen(request, timeout=10)

    def status(self, path, body=None, headers=None):
        try:
            with self.request(path, body, headers) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_first_account_requires_the_logged_setup_code(self):
        app.SETTINGS.update({'authUser': '', 'authHash': ''})
        account = {'username': 'owner', 'password': 'long-password', 'passwordConfirmation': 'long-password'}
        for code in [None, '', 'wrong-code']:
            with self.subTest(code=code):
                body = account if code is None else {**account, 'setupCode': code}
                self.assertEqual(401, self.status('/api/setup', body, {'X-Hecklarr': '1'})[0])
        self.assertEqual('', app.SETTINGS['authHash'])
        self.assertEqual(201, self.status('/api/setup', {**account, 'setupCode': 'right-code'}, {'X-Hecklarr': '1'})[0])
        self.assertIsNone(app.SETUP_CODE)

    def test_setup_code_attempts_are_rate_limited(self):
        app.SETTINGS.update({'authUser': '', 'authHash': ''})
        body = {'username': 'owner', 'password': 'long-password', 'passwordConfirmation': 'long-password',
                'setupCode': 'wrong-code'}
        codes = [self.status('/api/setup', body, {'X-Hecklarr': '1'})[0] for _ in range(9)]
        self.assertEqual([401] * 8 + [429], codes)

    def test_setup_code_is_created_only_while_no_account_exists(self):
        app.SETUP_CODE = None
        with patch('builtins.print'):
            self.assertIsNone(app.ensureSetupCode())
            app.SETTINGS['authHash'] = ''
            code = app.ensureSetupCode()
        self.assertEqual(12, len(code))
        self.assertEqual(code, app.ensureSetupCode())

    def test_unauthenticated_auth_and_health_do_not_leak_username_or_errors(self):
        status, auth = self.status('/api/auth')
        self.assertEqual(200, status)
        self.assertNotIn('username', auth)
        status, health = self.status('/api/health')
        self.assertEqual(200, status)
        self.assertFalse(health['ready'])
        self.assertNotIn('lastError', health)
        status, health = self.status('/api/health', headers={'X-Api-Key': 'private-api-key'})
        self.assertEqual('Radarr returned HTTP 401', health['lastError'])
        status, auth = self.status('/api/auth', headers={'X-Api-Key': 'private-api-key'})
        self.assertEqual('tester', auth['username'])

    def test_unexpected_errors_return_a_generic_500(self):
        headers = {'X-Api-Key': 'private-api-key', 'X-Hecklarr': '1'}
        with patch.object(app, 'publicSettings', side_effect=RuntimeError('secret detail')), patch('builtins.print') as log:
            status, body = self.status('/api/settings', headers=headers)
        self.assertEqual(500, status)
        self.assertNotIn('secret detail', json.dumps(body))
        self.assertNotIn('secret detail', str(log.call_args))
        with patch.object(app, 'syncRadarr', side_effect=AttributeError('boom')), patch('builtins.print'):
            app.SNAPSHOT = {'updatedAt': app.now(), 'items': [{'tmdbId': 1}]}
            self.assertEqual(500, self.status('/api/sync', {}, headers)[0])

    def test_wrongly_typed_input_is_a_400(self):
        headers = {'X-Api-Key': 'private-api-key', 'X-Hecklarr': '1'}
        status, body = self.status('/api/comedians', {'id': None}, headers)
        self.assertEqual((400, 'Invalid request'), (status, body['error']))

    def test_adding_a_comedian_does_not_wait_for_a_running_refresh(self):
        headers = {'X-Api-Key': 'private-api-key', 'X-Hecklarr': '1'}
        with patch.object(app, 'tmdb', return_value={'name': 'New comedian'}), app.REFRESH_LOCK:
            self.assertEqual(200, self.status('/api/comedians', {'id': 42, 'monitorMode': 'manual'}, headers)[0])
        self.assertEqual([42], [person['id'] for person in app.SETTINGS['comedians']])

    def test_settings_report_the_server_time_zone(self):
        with patch.dict(app.os.environ, {'TZ': 'Europe/Amsterdam'}):
            self.assertEqual('Europe/Amsterdam', app.publicSettings()['timeZone'])


class DownloadPollingTest(unittest.TestCase):
    def setUp(self):
        self.saved = (app.LAST_STATUS_REQUEST, app.DOWNLOAD_REFRESH)
        app.DOWNLOAD_REFRESH = threading.Event()

    def tearDown(self):
        app.LAST_STATUS_REQUEST, app.DOWNLOAD_REFRESH = self.saved

    def test_radarr_is_not_polled_while_nobody_is_watching(self):
        app.LAST_STATUS_REQUEST = 0.0
        with patch.object(app, 'updateDownloadStatuses') as update:
            self.assertFalse(app.downloadStatusTick())
        update.assert_not_called()

    def test_first_status_request_after_idle_wakes_the_poller(self):
        app.LAST_STATUS_REQUEST = 0.0
        app.noteStatusRequest()
        self.assertTrue(app.DOWNLOAD_REFRESH.is_set())
        app.DOWNLOAD_REFRESH.clear()
        app.noteStatusRequest()
        self.assertFalse(app.DOWNLOAD_REFRESH.is_set())
        with patch.object(app, 'updateDownloadStatuses') as update:
            self.assertTrue(app.downloadStatusTick())
        update.assert_called_once()

    def test_unexpected_poll_failure_does_not_escape_the_thread(self):
        app.LAST_STATUS_REQUEST = time.time()
        with patch.object(app, 'updateDownloadStatuses', side_effect=KeyError('tmdbId')), patch('builtins.print'):
            self.assertTrue(app.downloadStatusTick())

    def test_metadata_expiry_failure_does_not_end_maintenance_thread(self):
        calls = []
        def expire():
            calls.append(1)
            if len(calls) == 1:
                raise OSError('read-only file system')
            raise SystemExit
        with patch.object(app, 'expireMetadata', side_effect=expire), patch.object(app.time, 'sleep'), \
                patch('builtins.print'), self.assertRaises(SystemExit):
            app.maintainMetadata()
        self.assertEqual(2, len(calls))


class MovieListCacheTest(unittest.TestCase):
    """The full Radarr movie list is re-read only when a cached state could be wrong."""

    def setUp(self):
        self.now = 1000.0
        self.cache = app.MovieListCache(max_age=1800, missing_retry=300, clock=lambda: self.now)
        self.queue = [{'movieId': 10, 'status': 'downloading'}]
        self.movies = [{'id': 10, 'tmdbId': 100, 'hasFile': False, 'monitored': True, 'status': 'released'},
                       {'id': 11, 'tmdbId': 101, 'hasFile': True}]
        self.calls = []

    def fetch(self, path, settings):
        self.calls.append(path)
        if path == 'movie':
            return copy.deepcopy(self.movies)
        if path.startswith('movie/'):
            movie = next((row for row in self.movies if path == f"movie/{row['id']}"), None)
            if movie is None:
                raise ValueError('Radarr returned HTTP 404')
            return copy.deepcopy(movie)
        return {'totalRecords': len(self.queue), 'records': copy.deepcopy(self.queue)}

    def poll(self, movie_ids=frozenset({100, 101})):
        self.calls.clear()
        return app.fetchDownloadStatuses({}, set(movie_ids), fetch=self.fetch, cache=self.cache)

    def test_steady_polls_read_only_the_queue(self):
        self.assertEqual({'100': 'downloading', '101': 'downloaded'}, self.poll())
        self.assertIn('movie', self.calls)
        self.now += 60
        self.assertEqual({'100': 'downloading', '101': 'downloaded'}, self.poll())
        self.assertNotIn('movie', self.calls)

    def test_monitoring_changes_are_read_per_movie_without_the_full_list(self):
        self.poll()
        self.movies[0]['monitored'] = False
        self.now += 60
        self.poll()
        self.assertNotIn('movie', self.calls)
        self.assertEqual(['movie/10', 'movie/11'], sorted(path for path in self.calls if path.startswith('movie/')))
        self.assertFalse(self.cache.movies[100]['monitored'])

    def test_movie_deleted_in_radarr_falls_back_to_the_full_list(self):
        self.poll()
        del self.movies[1]
        self.now += 60
        self.assertEqual('not-in-radarr', self.poll()['101'])
        self.assertIn('movie', self.calls)

    def test_warning_messages_refresh_without_refetching_movies_and_clear_when_resolved(self):
        self.queue = [{'movieId': 10, 'status': 'warning', 'errorMessage': 'The download is stalled with no connections'}]
        self.assertEqual('warning', self.poll()['100'])
        self.assertEqual({'100': ['The download is stalled with no connections']}, self.cache.messages)
        self.queue[0]['errorMessage'] = 'Download client needs attention'
        self.now += 10
        self.poll()
        self.assertEqual({'100': ['Download client needs attention']}, self.cache.messages)
        self.assertNotIn('movie', self.calls)
        self.queue = [{'movieId': 10, 'status': 'downloading'}]
        self.now += 10
        self.assertEqual('downloading', self.poll()['100'])
        self.assertEqual({}, self.cache.messages)

    def test_finished_download_rereads_movies_so_it_shows_as_downloaded(self):
        self.poll()
        self.queue = []
        self.movies[0]['hasFile'] = True
        self.now += 60
        self.assertEqual('downloaded', self.poll()['100'])
        self.assertIn('movie', self.calls)

    def test_tracked_set_change_age_and_invalidation_reread_movies(self):
        self.poll()
        self.now += 60
        self.poll({100})
        self.assertIn('movie', self.calls)
        self.now += 1800
        self.poll({100})
        self.assertIn('movie', self.calls)
        self.cache.invalidate()
        self.poll({100})
        self.assertIn('movie', self.calls)

    def test_special_not_yet_in_radarr_is_rechecked_every_few_minutes(self):
        self.assertEqual('not-in-radarr', self.poll({100, 102})['102'])
        self.now += 60
        self.poll({100, 102})
        self.assertNotIn('movie', self.calls)
        self.movies.append({'id': 12, 'tmdbId': 102, 'hasFile': False, 'monitored': True, 'status': 'released'})
        self.now += 300
        self.assertEqual('missing', self.poll({100, 102})['102'])
        self.assertIn('movie', self.calls)

    def test_hecklarr_changes_to_radarr_invalidate_the_cache(self):
        saved = (app.DOWNLOAD_MOVIES, app.DOWNLOAD_REFRESH)
        app.DOWNLOAD_MOVIES, app.DOWNLOAD_REFRESH = self.cache, threading.Event()
        try:
            self.poll()
            app.invalidateDownloadCache()
            self.assertIsNone(self.cache.movies)
            self.assertTrue(app.DOWNLOAD_REFRESH.is_set())
        finally:
            app.DOWNLOAD_MOVIES, app.DOWNLOAD_REFRESH = saved


if __name__ == '__main__':
    unittest.main()
