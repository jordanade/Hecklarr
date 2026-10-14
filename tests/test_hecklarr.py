import copy
import base64
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import urllib.error
import urllib.request
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('hecklarr', Path(__file__).parents[1] / 'app.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class ClassificationTest(unittest.TestCase):
    def setUp(self):
        self.person = {'id': 52849, 'name': 'Louis C.K.', 'includeIds': [1595885], 'excludeIds': [1156641]}
        self.movie = {'id': 689643, 'title': 'Sincerely Louis C.K.', 'video': True,
                      'runtime': 60, 'genres': [{'id': 35}], 'release_date': '2020-04-04',
                      'keywords': {'keywords': [{'id': 9716}]},
                      'credits': {'cast': [{'id': 52849, 'character': 'Self', 'order': 0}]}}

    def test_video_special_is_included(self):
        self.assertTrue(app.classify(self.movie, self.person)[0])

    def test_missing_role_accepts_lead_standup_special_without_override(self):
        self.person = {'id': 109708, 'name': 'Bill Burr', 'includeIds': [], 'excludeIds': []}
        self.movie.update({'id': 991115, 'title': 'Bill Burr: Live at Red Rocks', 'runtime': 82})
        for role in ['', None, '   ', 'missing']:
            with self.subTest(role=role):
                performer = {'id': 109708, 'order': 0}
                if role != 'missing':
                    performer['character'] = role
                self.movie['credits']['cast'] = [performer]
                self.assertTrue(app.classify(self.movie, self.person)[0])

    def test_missing_role_requires_keyword_even_with_live_special_description(self):
        self.movie['credits']['cast'][0]['character'] = ''
        self.movie['keywords']['keywords'] = []
        self.movie['overview'] = 'Louis C.K. recorded live at Madison Square Garden.'
        self.assertFalse(app.classify(self.movie, self.person)[0])

    def test_missing_role_preserves_lead_runtime_and_genre_requirements(self):
        self.movie['credits']['cast'][0]['character'] = ''
        original = copy.deepcopy(self.movie)
        for restriction in ['supporting', 'short', 'unknown_runtime', 'non_comedy']:
            with self.subTest(restriction=restriction):
                self.movie = copy.deepcopy(original)
                if restriction == 'supporting':
                    self.movie['credits']['cast'][0]['order'] = 4
                elif restriction == 'short':
                    self.movie['runtime'] = 5
                elif restriction == 'unknown_runtime':
                    self.movie['runtime'] = None
                else:
                    self.movie['genres'] = [{'id': 99}]
                self.assertFalse(app.classify(self.movie, self.person)[0])

    def test_thanks_and_director_credits_do_not_qualify(self):
        self.movie['credits'] = {'cast': [], 'crew': [{'id': 52849, 'job': 'Thanks'}]}
        self.assertFalse(app.classify(self.movie, self.person)[0])

    def test_short_sketch_is_excluded(self):
        self.movie['runtime'] = 5
        self.assertFalse(app.classify(self.movie, self.person)[0])

    def test_acting_role_and_archive_footage_are_excluded(self):
        for role in ['Max (voice)', 'Self (archive footage)', 'Self (uncredited)']:
            with self.subTest(role=role):
                self.movie['credits']['cast'][0]['character'] = role
                self.assertFalse(app.classify(self.movie, self.person)[0])

    def test_cameo_is_excluded(self):
        self.movie['credits']['cast'][0]['order'] = 4
        self.assertFalse(app.classify(self.movie, self.person)[0])

    def test_confirmed_special_does_not_require_keywords(self):
        self.movie['id'] = 1595885
        self.movie['keywords']['keywords'] = []
        self.assertTrue(app.classify(self.movie, self.person)[0])

    def test_explicit_exclusion_wins(self):
        self.person['excludeIds'].append(1595885)
        self.movie['id'] = 1595885
        self.assertFalse(app.classify(self.movie, self.person)[0])

    def test_named_special_can_match_without_keyword(self):
        self.movie['keywords']['keywords'] = []
        self.movie['overview'] = 'Louis C.K. recorded live at Madison Square Garden.'
        self.assertTrue(app.classify(self.movie, self.person)[0])

    def test_ambiguous_named_comedy_is_left_for_review(self):
        self.movie['keywords']['keywords'] = []
        self.movie['overview'] = 'A film about Louis C.K.'
        self.assertFalse(app.classify(self.movie, self.person)[0])

    def test_refresh_failure_does_not_modify_previous_snapshot(self):
        previous = {'items': [{'tmdbId': 689643, 'personId': 52849, 'year': '2020', 'title': 'Sincerely', 'comedian': 'Louis C.K.'}]}
        original = copy.deepcopy(previous)
        def failed(path, settings):
            raise ValueError('TMDB unavailable')
        with self.assertRaises(ValueError):
            app.buildSnapshot({'comedians': [self.person]}, previous, failed)
        self.assertEqual(original, previous)

    def test_retention_honors_removed_comedians_and_exclusions(self):
        previous = {'items': [{'tmdbId': 1156641, 'personId': 52849, 'year': '2024', 'title': 'Sorry/Not Sorry', 'comedian': 'Louis C.K.'},
                              {'tmdbId': 999, 'personId': 99, 'year': '2020', 'title': 'Other', 'comedian': 'Other'}]}
        self.person['includeIds'] = []
        result = app.buildSnapshot({'comedians': [self.person]}, previous, lambda path, settings: {'name': 'Louis C.K.'} if path == 'person/52849' else {'cast': []})
        self.assertEqual([], result['items'])

    def test_retained_special_fetches_current_metadata_even_when_credit_disappears(self):
        previous = {'items': [{'tmdbId': 689643, 'personId': 52849, 'year': '1999',
                               'title': 'Old title', 'comedian': 'Old name'}]}
        self.person['includeIds'] = []
        current = copy.deepcopy(self.movie)
        current.update({'title': 'Updated title', 'release_date': '2026-01-01', 'credits': {'cast': []}})
        def fetch(path, settings):
            if path == 'person/52849':
                return {'name': 'Current name'}
            if path == 'person/52849/movie_credits':
                return {'cast': []}
            self.assertEqual('movie/689643?append_to_response=keywords,credits', path)
            return current
        result = app.buildSnapshot({'comedians': [self.person]}, previous, fetch)
        self.assertEqual('Updated title', result['items'][0]['title'])
        self.assertEqual('2026', result['items'][0]['year'])
        self.assertEqual('Current name', result['items'][0]['comedian'])
        self.assertIn('metadata refreshed', result['items'][0]['reason'])
        self.assertEqual([{'id': 52849, 'name': 'Current name'}], result['people'])

    def test_removed_tmdb_movie_is_not_retained_or_republished(self):
        previous = {'items': [{'tmdbId': 689643, 'personId': 52849, 'title': 'Removed title'}]}
        self.person['includeIds'] = []
        def fetch(path, settings):
            if path == 'person/52849':
                return {'name': 'Current name'}
            if path == 'person/52849/movie_credits':
                return {'cast': []}
            raise app.TmdbNotFound('Removed')
        result = app.buildSnapshot({'comedians': [self.person]}, previous, fetch)
        self.assertEqual([], result['items'])
        self.assertEqual([], result['reviewed'])


class HttpContractTest(unittest.TestCase):
    def setUp(self):
        self.saved = (app.SETTINGS, app.SNAPSHOT, app.STATE_DIR, app.SESSIONS, app.LAST_ERROR)
        self.directory = tempfile.TemporaryDirectory()
        app.STATE_DIR = Path(self.directory.name)
        salt = b'contract-test-salt'
        hashed = hashlib.scrypt(b'test-password', salt=salt, n=16384, r=8, p=1, dklen=64)
        encoded = 'scrypt$16384$8$1$' + base64.b64encode(salt).decode() + '$' + base64.b64encode(hashed).decode()
        app.SETTINGS = {'apiKey': 'private-api-key', 'feedKey': 'private-feed-key', 'authUser': 'tester',
                        'authHash': encoded, 'radarrApiKey': 'private-radarr-key', 'tmdbApiKey': 'private-tmdb-key',
                        'comedians': [], 'rootFolderPath': '/data/comedy', 'qualityProfileId': 4}
        app.SNAPSHOT = {'updatedAt': app.now(), 'items': [{'tmdbId': 689643, 'title': 'Sincerely Louis C.K.', 'year': '2020'}]}
        app.SESSIONS = {}
        app.LAST_ERROR = None
        self.server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.directory.cleanup()
        app.SETTINGS, app.SNAPSHOT, app.STATE_DIR, app.SESSIONS, app.LAST_ERROR = self.saved

    def request(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers or {})
        return urllib.request.urlopen(req)

    def test_feed_uses_radarr_custom_list_id_contract(self):
        with self.request('/feed/movies.json?key=private-feed-key') as response:
            self.assertEqual([{'id': 689643, 'title': 'Sincerely Louis C.K.'}], json.load(response))

    def test_feed_and_settings_require_authentication(self):
        for path in ['/feed/movies.json', '/api/settings']:
            with self.subTest(path=path), self.assertRaises(urllib.error.HTTPError) as context:
                self.request(path)
            self.assertEqual(401, context.exception.code)
            context.exception.close()

    def test_public_settings_do_not_expose_credentials(self):
        with self.request('/api/settings', headers={'X-Api-Key': 'private-api-key'}) as response:
            data = response.read().decode()
        self.assertNotIn('private-', data)
        self.assertNotIn('authHash', data)

    def test_first_run_creates_account_then_requires_login(self):
        app.SETTINGS.update({'authUser': '', 'authHash': '', 'radarrListId': None})
        with self.request('/api/auth') as response:
            self.assertTrue(json.load(response)['setupRequired'])
        account = {'username': 'new-user', 'password': 'new-password', 'passwordConfirmation': 'new-password'}
        with self.request('/api/setup', account, {'X-Hecklarr': '1'}) as response:
            self.assertEqual(201, response.status)
            self.assertIsNone(response.headers.get('Set-Cookie'))
        saved = json.loads((app.STATE_DIR / 'settings.json').read_text())
        self.assertEqual('new-user', saved['authUser'])
        self.assertTrue(app.checkPassword('new-password', saved['authHash']))
        self.assertNotIn('new-password', json.dumps(saved))
        self.assertEqual(0o600, (app.STATE_DIR / 'settings.json').stat().st_mode & 0o777)
        with self.request('/api/login', account, {'X-Hecklarr': '1'}) as response:
            cookie = response.headers['Set-Cookie'].split(';')[0]
        with self.request('/api/settings', headers={'Cookie': cookie}) as response:
            self.assertIsNone(json.load(response)['radarrListId'])
        with self.request('/api/auth') as response:
            self.assertFalse(json.load(response)['setupRequired'])

    def test_setup_cannot_replace_existing_account(self):
        old_hash = app.SETTINGS['authHash']
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request('/api/setup', {'username': 'other', 'password': 'replacement',
                                       'passwordConfirmation': 'replacement'}, {'X-Hecklarr': '1'})
        self.assertEqual(409, context.exception.code)
        context.exception.close()
        self.assertEqual(old_hash, app.SETTINGS['authHash'])

    def test_first_run_account_supports_unicode_username(self):
        app.SETTINGS.update({'authUser': '', 'authHash': ''})
        account = {'username': 'Jörg', 'password': 'long-password', 'passwordConfirmation': 'long-password'}
        with self.request('/api/setup', account, {'X-Hecklarr': '1'}) as response:
            self.assertEqual(201, response.status)
        with self.request('/api/login', account, {'X-Hecklarr': '1'}) as response:
            self.assertIsNotNone(response.headers.get('Set-Cookie'))

    def test_unicode_feed_key_is_rejected_cleanly(self):
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request('/feed/movies.json?key=%C3%A9')
        self.assertEqual(401, context.exception.code)
        context.exception.close()

    def test_negative_request_size_is_rejected_without_reading_body(self):
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request('/api/login', {}, {'X-Hecklarr': '1', 'Content-Length': '-1'})
        self.assertEqual(400, context.exception.code)
        context.exception.close()

    def test_setup_validates_credentials_and_requires_csrf_header(self):
        app.SETTINGS.update({'authUser': '', 'authHash': ''})
        for account, headers, status in [
            ({'username': '', 'password': 'long-password', 'passwordConfirmation': 'long-password'}, {'X-Hecklarr': '1'}, 400),
            ({'username': 'user', 'password': 'short', 'passwordConfirmation': 'short'}, {'X-Hecklarr': '1'}, 400),
            ({'username': 'user', 'password': 'long-password', 'passwordConfirmation': 'mismatch'}, {'X-Hecklarr': '1'}, 400),
            ({'username': 'user', 'password': 'long-password', 'passwordConfirmation': 'long-password'}, {}, 403),
        ]:
            with self.subTest(account=account, status=status), self.assertRaises(urllib.error.HTTPError) as context:
                self.request('/api/setup', account, headers)
            self.assertEqual(status, context.exception.code)
            context.exception.close()
        self.assertEqual('', app.SETTINGS['authHash'])

    def test_empty_state_initializes_and_persists_generated_keys(self):
        settings = app.loadSettings()
        self.assertEqual('', settings['authHash'])
        self.assertEqual([], settings['comedians'])
        self.assertIsNone(settings['radarrListId'])
        self.assertEqual(48, len(settings['apiKey']))
        self.assertEqual(48, len(settings['feedKey']))
        self.assertNotEqual(settings['apiKey'], settings['feedKey'])
        self.assertEqual(settings, app.loadSettings())

    def test_loading_existing_settings_preserves_account_and_connection(self):
        app.saveJson(app.STATE_DIR / 'settings.json', app.SETTINGS)
        saved = app.loadSettings()
        for key, value in app.SETTINGS.items():
            self.assertEqual(value, saved[key])

    def test_settings_migration_removes_tmdb_names_but_preserves_watchlist(self):
        app.SETTINGS['comedians'] = [{'id': 123, 'name': 'Old cached name', 'includeIds': [456], 'excludeIds': [789]}]
        app.saveJson(app.STATE_DIR / 'settings.json', app.SETTINGS)
        loaded = app.loadSettings()
        self.assertEqual([{'id': 123, 'includeIds': [456], 'excludeIds': [789]}], loaded['comedians'])
        self.assertNotIn('Old cached name', (app.STATE_DIR / 'settings.json').read_text())

    def test_expired_cache_is_purged_from_disk_and_not_served(self):
        app.SNAPSHOT['updatedAt'] = (app.dt.datetime.now(app.dt.timezone.utc) - app.CACHE_MAX_AGE).isoformat()
        app.SNAPSHOT['people'] = [{'id': 123, 'name': 'Expired name'}]
        app.SETTINGS['comedians'] = [{'id': 123, 'includeIds': [], 'excludeIds': []}]
        app.saveJson(app.STATE_DIR / 'snapshot.json', app.SNAPSHOT)
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request('/feed/movies.json?key=private-feed-key')
        self.assertEqual(503, context.exception.code)
        context.exception.close()
        self.assertEqual({}, json.loads((app.STATE_DIR / 'snapshot.json').read_text()))
        with self.request('/api/settings', headers={'X-Api-Key': 'private-api-key'}) as response:
            self.assertEqual('TMDB person 123', json.load(response)['comedians'][0]['name'])
        self.assertEqual(123, app.SETTINGS['comedians'][0]['id'])

    def test_invalid_or_missing_cache_age_is_not_trusted(self):
        for timestamp in [None, 'invalid', '2026-01-01',
                          (app.dt.datetime.now(app.dt.timezone.utc) + app.dt.timedelta(days=1)).isoformat()]:
            with self.subTest(timestamp=timestamp):
                app.SNAPSHOT = {'items': [{'title': 'Stale'}]}
                if timestamp is not None:
                    app.SNAPSHOT['updatedAt'] = timestamp
                app.expireMetadata()
                self.assertEqual({}, app.SNAPSHOT)

    def test_interrupted_snapshot_write_is_removed(self):
        temporary = app.STATE_DIR / 'snapshot.tmp'
        temporary.write_text('{"items": ["Old cached data"]}')
        app.expireMetadata()
        self.assertFalse(temporary.exists())

    def test_tmdb_request_identifies_app_and_classifies_access_errors(self):
        for code, error_type in [(404, app.TmdbNotFound), (401, app.TmdbAccessDenied), (403, app.TmdbAccessDenied)]:
            error = urllib.error.HTTPError('https://api.themoviedb.org/3/person/123', code, 'Test error', {}, None)
            with self.subTest(code=code), patch.object(app.urllib.request, 'urlopen', side_effect=error) as request:
                with self.assertRaises(error_type):
                    app.requestJson('https://api.themoviedb.org/3/person/123', 'test-api-key', tmdb=True)
                self.assertEqual('Hecklarr/0.1', request.call_args.args[0].get_header('User-agent'))

    def test_failed_refresh_preserves_valid_cache_without_extending_age(self):
        original = copy.deepcopy(app.SNAPSHOT)
        with patch.object(app, 'buildSnapshot', side_effect=ValueError('Temporary outage')):
            with self.assertRaisesRegex(ValueError, 'Temporary outage'):
                app.refresh()
        self.assertEqual(original, app.SNAPSHOT)

    def test_denied_tmdb_access_purges_cached_data(self):
        with patch.object(app, 'buildSnapshot', side_effect=app.TmdbAccessDenied('Denied')):
            with self.assertRaisesRegex(ValueError, 'Denied'):
                app.refresh()
        self.assertEqual({}, app.SNAPSHOT)
        self.assertEqual({}, json.loads((app.STATE_DIR / 'snapshot.json').read_text()))

    def test_denied_tmdb_search_also_purges_cached_data(self):
        with patch.object(app, 'tmdb', side_effect=app.TmdbAccessDenied('Denied')):
            with self.assertRaises(urllib.error.HTTPError) as context:
                self.request('/api/search?q=test', headers={'X-Api-Key': 'private-api-key'})
        self.assertEqual(400, context.exception.code)
        context.exception.close()
        self.assertEqual({}, app.SNAPSHOT)

    def test_radarr_setup_requires_tmdb_key(self):
        app.SETTINGS['tmdbApiKey'] = ''
        with patch.object(app, 'radarr') as radarr, self.assertRaisesRegex(ValueError, 'TMDB'):
            app.syncRadarr()
        radarr.assert_not_called()

    def test_radarr_setup_explains_empty_catalog_before_calling_radarr(self):
        app.SNAPSHOT = {'updatedAt': 'now', 'items': []}
        with patch.object(app, 'radarr') as radarr, self.assertRaisesRegex(ValueError, 'catalog has no specials'):
            app.syncRadarr()
        radarr.assert_not_called()

    def test_saving_blank_keys_preserves_existing_credentials(self):
        with self.request('/api/settings', {'radarrApiKey': '', 'tmdbApiKey': ''},
                          {'X-Api-Key': 'private-api-key', 'X-Hecklarr': '1'}) as response:
            self.assertEqual(200, response.status)
        self.assertEqual('private-radarr-key', app.SETTINGS['radarrApiKey'])
        self.assertEqual('private-tmdb-key', app.SETTINGS['tmdbApiKey'])

    def test_mutation_requires_csrf_header(self):
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request('/api/settings', {'rootFolderPath': '/data/movies'}, {'X-Api-Key': 'private-api-key'})
        self.assertEqual(403, context.exception.code)
        context.exception.close()
        self.assertEqual('/data/comedy', app.SETTINGS['rootFolderPath'])

    def test_courarr_password_format_and_persistent_session(self):
        with self.request('/api/login', {'username': 'tester', 'password': 'test-password'},
                          {'X-Hecklarr': '1'}) as response:
            cookie = response.headers['Set-Cookie'].split(';')[0]
        persisted = json.loads((app.STATE_DIR / 'sessions.json').read_text())
        self.assertEqual(persisted, app.SESSIONS)
        self.assertNotIn(cookie.split('=', 1)[1], persisted)
        app.SESSIONS = persisted
        with self.request('/api/settings', headers={'Cookie': cookie}) as response:
            self.assertEqual(200, response.status)
        with self.request('/api/logout', {}, {'Cookie': cookie, 'X-Hecklarr': '1'}):
            pass
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request('/api/settings', headers={'Cookie': cookie})
        self.assertEqual(401, context.exception.code)
        context.exception.close()

    def test_legacy_session_survives_rename_and_logs_out(self):
        with self.request('/api/login', {'username': 'tester', 'password': 'test-password'},
                          {'X-Hecklarr': '1'}) as response:
            cookie = response.headers['Set-Cookie'].split(';')[0].replace('hecklarr_session=', 'standuparr_session=')
        with self.request('/api/settings', headers={'Cookie': cookie}) as response:
            self.assertEqual(200, response.status)
        with self.request('/api/logout', {}, {'Cookie': cookie, 'X-Hecklarr': '1'}):
            pass
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request('/api/settings', headers={'Cookie': cookie})
        self.assertEqual(401, context.exception.code)
        context.exception.close()

    def test_rename_updates_existing_radarr_list_by_id(self):
        app.SETTINGS.update({'radarrListId': 1, 'feedBaseUrl': 'http://hecklarr:6162'})
        app.SNAPSHOT = {'items': [{'tmdbId': 52849}]}
        def respond(path, settings, body=None, method=None):
            if path == 'rootfolder':
                return [{'path': '/data/comedy'}]
            if path == 'config/importlist':
                return {'listSyncLevel': 'disabled'}
            if path == 'importlist':
                return [{'id': 1, 'name': 'Standuparr - Comedy', 'fields': [{'name': 'url'}]}]
            if path == 'importlist/1':
                self.assertEqual('PUT', method)
                self.assertEqual('Hecklarr - Comedy', body['name'])
                self.assertTrue(body['fields'][0]['value'].startswith('http://hecklarr:6162/'))
                return body
            if path == 'command':
                return {'id': 2}
            self.fail('Unexpected Radarr operation: ' + path)
        with patch.object(app, 'radarr', side_effect=respond):
            self.assertEqual(1, app.syncRadarr()['id'])


if __name__ == '__main__':
    unittest.main()
