"""Radarr owns monitoring; comedian modes only decide automatic additions."""

import copy
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
from unittest.mock import patch

from load_app import loadApp

app = loadApp('hecklarr_test_monitoring')
from hecklarr import clients  # noqa: E402


class FakeRadarr:
    def __init__(self, movie=None):
        self.movie = copy.deepcopy(movie)
        self.calls = []
        self.add_failure = None
        self.put_failure = None
        self.search_failure = False
        self.delete_failure = None
        self.replace_on_put = False
        self.replace_on_delete = False

    def __call__(self, path, settings, body=None, method=None):
        self.calls.append((path, copy.deepcopy(body), method))
        if path == 'movie?tmdbId=100':
            return [copy.deepcopy(self.movie)] if self.movie else []
        if path == 'movie/lookup/tmdb?tmdbId=100':
            return {'tmdbId': 100, 'title': 'Test special'}
        if path == 'movie' and body:
            if self.add_failure != 'before':
                self.movie = {**body, 'id': 10, 'path': '/comedy/Test special', 'hasFile': False}
                if self.add_failure == 'concurrent':
                    self.movie['monitored'] = False
            if self.add_failure:
                raise ValueError('Add failed or response lost')
            return copy.deepcopy(self.movie)
        if path == 'movie/10' and method == 'PUT':
            if self.put_failure != 'before':
                self.movie = copy.deepcopy(body)
                if self.replace_on_put:
                    self.movie['movieFileId'] = 502
            if self.put_failure:
                raise ValueError('Update failed or response lost')
            return copy.deepcopy(self.movie)
        if path == 'moviefile/501' and method == 'DELETE':
            if self.delete_failure != 'before':
                self.movie.update(hasFile=self.replace_on_delete, movieFileId=502 if self.replace_on_delete else 0)
            if self.delete_failure:
                raise ValueError('Delete failed or response lost')
            return None
        if path == 'command':
            if self.search_failure:
                raise ValueError('Search response lost')
            return {'id': 9}
        raise AssertionError('Unexpected Radarr request: ' + path)


class MonitoringTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.settings = {'comedians': [{'id': 1, 'monitorMode': 'manual', 'includeIds': [], 'excludeIds': []}],
                         'radarrUrl': 'http://radarr', 'radarrApiKey': 'key', 'tmdbApiKey': 'key',
                         'rootFolderPath': '/comedy', 'qualityProfileId': 4, 'radarrListId': 1,
                         'feedBaseUrl': 'http://hecklarr', 'feedKey': 'feed'}
        self.snapshot = {'updatedAt': app.now(), 'items': [
            {'tmdbId': 100 + i, 'personIds': [1], 'title': f'Special {i}', 'releaseDate': '2020-01-01'}
            for i in range(15)]}
        self.patches = [patch.object(app, 'STATE_DIR', Path(self.directory.name)),
                        patch.object(app, 'SETTINGS', copy.deepcopy(self.settings)),
                        patch.object(app, 'SNAPSHOT', copy.deepcopy(self.snapshot)),
                        patch.object(app, 'DOWNLOAD_MOVIES', app.MovieListCache()),
                        patch.object(app, 'DOWNLOAD_REFRESH', threading.Event()),
                        patch.object(app, 'DOWNLOAD_STATUSES', {'items': {}, 'movies': {}, 'lastError': None, 'updatedAt': None})]
        for item in self.patches:
            item.start()
        self.handler = app.Handler.__new__(app.Handler)
        self.handler.reply = lambda status, body: (status, body)
        self.movie = {'id': 10, 'tmdbId': 100, 'monitored': False, 'path': '/existing/special',
                      'qualityProfileId': 8, 'tags': [3], 'hasFile': True}

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def test_manual_catalog_of_fifteen_specials_has_an_empty_feed(self):
        self.assertEqual([], app.automaticMovies(app.SETTINGS, app.SNAPSHOT))
        self.assertEqual((200, []), self.handler.movieFeed({'key': ['feed']}))
        self.assertEqual(15, len(app.SNAPSHOT['items']))

    def test_monitoring_one_manual_special_adds_only_it_and_searches(self):
        radarr = FakeRadarr()
        before = copy.deepcopy(app.SETTINGS)
        with patch.object(app, 'radarr', side_effect=radarr):
            result = app.monitorSpecial(100, True)
        self.assertEqual({'inRadarr': True, 'radarrId': 10, 'monitored': True, 'movieFileId': None}, result['movie'])
        additions = [body for path, body, _ in radarr.calls if path == 'movie']
        self.assertEqual(1, len(additions))
        self.assertEqual(100, additions[0]['tmdbId'])
        self.assertEqual('/comedy', additions[0]['rootFolderPath'])
        self.assertEqual(4, additions[0]['qualityProfileId'])
        self.assertTrue(additions[0]['addOptions']['searchForMovie'])
        self.assertEqual(before, app.SETTINGS)
        self.assertEqual([], app.automaticMovies(app.SETTINGS, app.SNAPSHOT))

    def test_existing_movie_monitoring_preserves_settings_and_files_and_searches(self):
        radarr = FakeRadarr(self.movie)
        with patch.object(app, 'radarr', side_effect=radarr):
            app.monitorSpecial(100, True)
        self.assertEqual({**self.movie, 'monitored': True}, radarr.movie)
        self.assertEqual([{'name': 'MoviesSearch', 'movieIds': [10]}],
                         [body for path, body, _ in radarr.calls if path == 'command'])

    def test_unmonitoring_keeps_movie_files_queue_and_catalog(self):
        radarr = FakeRadarr({**self.movie, 'monitored': True})
        with patch.object(app, 'radarr', side_effect=radarr):
            result = app.monitorSpecial(100, False)
        self.assertFalse(result['movie']['monitored'])
        self.assertTrue(radarr.movie['hasFile'])
        self.assertEqual(15, len(app.SNAPSHOT['items']))
        self.assertFalse(any(path == 'command' or method == 'DELETE' for path, _, method in radarr.calls))

    def test_unmonitoring_an_absent_movie_does_not_create_it(self):
        radarr = FakeRadarr()
        with patch.object(app, 'radarr', side_effect=radarr):
            result = app.monitorSpecial(100, False)
        self.assertEqual({'inRadarr': False, 'radarrId': None, 'monitored': False, 'movieFileId': None}, result['movie'])
        self.assertEqual(1, len(radarr.calls))

    def test_repeated_and_concurrent_monitor_requests_do_not_duplicate_additions_or_searches(self):
        radarr = FakeRadarr()
        errors = []
        def monitor():
            try:
                app.monitorSpecial(100, True)
            except Exception as error:
                errors.append(error)
        with patch.object(app, 'radarr', side_effect=radarr):
            threads = [threading.Thread(target=monitor) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
            app.monitorSpecial(100, True)
        self.assertEqual([], errors)
        self.assertEqual(1, sum(path == 'movie' for path, _, _ in radarr.calls))
        self.assertFalse(any(path == 'command' for path, _, _ in radarr.calls))

    def test_add_response_loss_is_reconciled_without_reposting(self):
        radarr = FakeRadarr()
        radarr.add_failure = 'after'
        with patch.object(app, 'radarr', side_effect=radarr):
            result = app.monitorSpecial(100, True)
        self.assertTrue(result['movie']['monitored'])
        self.assertIsNotNone(result['warning'])
        self.assertEqual(1, sum(path == 'movie' for path, _, _ in radarr.calls))

    def test_concurrent_external_add_is_monitored_and_searched(self):
        radarr = FakeRadarr()
        radarr.add_failure = 'concurrent'
        with patch.object(app, 'radarr', side_effect=radarr):
            result = app.monitorSpecial(100, True)
        self.assertTrue(result['movie']['monitored'])
        self.assertTrue(any(path == 'command' for path, _, _ in radarr.calls))

    def test_failed_add_and_failed_put_do_not_claim_success(self):
        for existing, failure in [(None, 'add_failure'), (self.movie, 'put_failure')]:
            radarr = FakeRadarr(existing)
            setattr(radarr, failure, 'before')
            with self.subTest(failure=failure), patch.object(app, 'radarr', side_effect=radarr), self.assertRaises(ValueError):
                app.monitorSpecial(100, True)
        self.assertEqual({}, app.DOWNLOAD_STATUSES['movies'])

    def test_put_response_loss_is_reconciled_before_starting_search(self):
        radarr = FakeRadarr(self.movie)
        radarr.put_failure = 'after'
        with patch.object(app, 'radarr', side_effect=radarr):
            result = app.monitorSpecial(100, True)
        self.assertTrue(result['movie']['monitored'])
        self.assertIsNone(result['warning'])

    def test_search_failure_returns_confirmed_monitoring_with_warning(self):
        radarr = FakeRadarr(self.movie)
        radarr.search_failure = True
        with patch.object(app, 'radarr', side_effect=radarr):
            result = app.monitorSpecial(100, True)
        self.assertTrue(result['movie']['monitored'])
        self.assertIsNotNone(result['warning'])
        self.assertTrue(app.cachedDownloadStatuses()['movies']['100']['monitored'])

    def test_unknown_catalog_id_and_invalid_monitor_values_are_rejected(self):
        with patch.object(app, 'radarr') as radarr, self.assertRaises(ValueError):
            app.monitorSpecial(999, True)
        radarr.assert_not_called()
        for value in ['true', 1, None, []]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.handler.monitorSpecialRequest({'movieId': 100, 'monitored': value})

    def test_monitoring_does_not_wait_for_a_running_refresh(self):
        radarr = FakeRadarr(self.movie)
        results = []
        with patch.object(app, 'radarr', side_effect=radarr), app.REFRESH_LOCK:
            thread = threading.Thread(target=lambda: results.append(app.monitorSpecial(100, True)), daemon=True)
            thread.start()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
        self.assertTrue(results[0]['movie']['monitored'])

    def test_external_monitoring_changes_are_read_within_sixty_seconds_independently_of_download_status(self):
        clock = [0]
        app.DOWNLOAD_MOVIES = app.MovieListCache(clock=lambda: clock[0])
        radarr_movie = {**self.movie, 'monitored': True}
        def fetch(path, settings):
            return [copy.deepcopy(radarr_movie)] if path == 'movie' else {'totalRecords': 0, 'records': []}
        with patch.object(app, 'radarr', side_effect=fetch):
            app.updateDownloadStatuses()
            self.assertTrue(app.DOWNLOAD_STATUSES['movies']['100']['monitored'])
            radarr_movie['monitored'] = False
            clock[0] = 60
            app.updateDownloadStatuses()
        self.assertFalse(app.DOWNLOAD_STATUSES['movies']['100']['monitored'])
        self.assertEqual('downloaded', app.DOWNLOAD_STATUSES['items']['100'])
        self.assertEqual(self.settings, app.SETTINGS)

    def test_poll_outage_preserves_last_monitoring_and_marks_it_stale(self):
        app.DOWNLOAD_STATUSES['movies'] = {'100': {'inRadarr': True, 'radarrId': 10, 'monitored': True}}
        with patch.object(app, 'radarr', side_effect=ValueError('Unavailable')):
            app.updateDownloadStatuses()
        self.assertTrue(app.DOWNLOAD_STATUSES['movies']['100']['monitored'])
        self.assertIsNotNone(app.DOWNLOAD_STATUSES['lastError'])

    def test_badge_remains_pending_after_monitor_write_until_a_successful_poll(self):
        radarr = FakeRadarr(self.movie)
        app.DOWNLOAD_STATUSES['items'] = {'100': 'unmonitored'}
        with patch.object(app, 'radarr', side_effect=radarr):
            app.monitorSpecial(100, True)
        cached = app.cachedDownloadStatuses()
        self.assertTrue(cached['movies']['100']['monitored'])
        self.assertEqual('unmonitored', cached['items']['100'])
        self.assertEqual([100], cached['pendingMovieIds'])
        with patch.object(app, 'fetchDownloadStatuses', return_value={'100': 'downloading'}):
            app.updateDownloadStatuses()
        self.assertEqual([], app.cachedDownloadStatuses()['pendingMovieIds'])
        self.assertEqual('downloading', app.cachedDownloadStatuses()['items']['100'])

    def test_failed_poll_keeps_pending_badge_marked_with_an_error(self):
        app.DOWNLOAD_STATUSES['pendingMovieIds'] = [100]
        with patch.object(app, 'radarr', side_effect=ValueError('Unavailable')):
            app.updateDownloadStatuses()
        cached = app.cachedDownloadStatuses()
        self.assertEqual([100], cached['pendingMovieIds'])
        self.assertIsNotNone(cached['lastError'])

    def test_pending_badges_for_removed_titles_are_not_returned(self):
        app.DOWNLOAD_STATUSES['pendingMovieIds'] = [100, 999]
        self.assertEqual([100], app.cachedDownloadStatuses()['pendingMovieIds'])

    def test_file_deletion_keeps_movie_and_catalog_and_respects_monitoring_choice(self):
        for unmonitor in [False, True]:
            radarr = FakeRadarr({**self.movie, 'monitored': True, 'movieFileId': 501})
            with self.subTest(unmonitor=unmonitor), patch.object(app, 'radarr', side_effect=radarr):
                result = app.deleteSpecialFile(100, 501, unmonitor)
            self.assertTrue(result['fileDeleted'])
            self.assertTrue(result['movie']['inRadarr'])
            self.assertIsNone(result['movie']['movieFileId'])
            self.assertEqual(not unmonitor, result['movie']['monitored'])
            self.assertEqual([('moviefile/501', None, 'DELETE')],
                             [call for call in radarr.calls if call[2] == 'DELETE'])
            self.assertFalse(any(path == 'command' for path, _, _ in radarr.calls))
            self.assertEqual(15, len(app.SNAPSHOT['items']))
            self.assertEqual([100], app.cachedDownloadStatuses()['pendingMovieIds'])
            if unmonitor:
                self.assertLess(next(i for i, call in enumerate(radarr.calls) if call[2] == 'PUT'),
                                next(i for i, call in enumerate(radarr.calls) if call[2] == 'DELETE'))

    def test_file_deletion_rejects_missing_replaced_or_unavailable_files_without_mutation(self):
        for movie in [None, self.movie, {**self.movie, 'movieFileId': 502},
                      {**self.movie, 'movieFileId': 501, 'hasFile': False}]:
            radarr = FakeRadarr(movie)
            with self.subTest(movie=movie), patch.object(app, 'radarr', side_effect=radarr), self.assertRaises(ValueError):
                app.deleteSpecialFile(100, 501, True)
            self.assertTrue(all(body is None and method is None for _, body, method in radarr.calls))
        with patch.object(app, 'radarr') as radarr, self.assertRaises(ValueError):
            app.deleteSpecialFile(999, 501, True)
        radarr.assert_not_called()

    def test_file_replaced_while_unmonitoring_is_never_deleted(self):
        radarr = FakeRadarr({**self.movie, 'monitored': True, 'movieFileId': 501})
        radarr.replace_on_put = True
        with patch.object(app, 'radarr', side_effect=radarr), self.assertRaisesRegex(ValueError, 'No file was deleted'):
            app.deleteSpecialFile(100, 501, True)
        self.assertFalse(radarr.movie['monitored'])
        self.assertEqual(502, radarr.movie['movieFileId'])
        self.assertFalse(any(method == 'DELETE' for _, _, method in radarr.calls))

    def test_lost_file_deletion_response_is_reconciled_without_deleting_replacement(self):
        for replacement in [False, True]:
            radarr = FakeRadarr({**self.movie, 'movieFileId': 501})
            radarr.delete_failure = 'after'
            radarr.replace_on_delete = replacement
            with self.subTest(replacement=replacement), patch.object(app, 'radarr', side_effect=radarr):
                result = app.deleteSpecialFile(100, 501, False)
            self.assertTrue(result['fileDeleted'])
            self.assertEqual(replacement, result['warning'] is not None)
            self.assertEqual(1, sum(method == 'DELETE' for _, _, method in radarr.calls))
            self.assertEqual(502 if replacement else None, result['movie']['movieFileId'])

    def test_failed_deletion_reports_partial_unmonitor_and_invalidates_cache(self):
        radarr = FakeRadarr({**self.movie, 'monitored': True, 'movieFileId': 501})
        radarr.delete_failure = 'before'
        with patch.object(app, 'radarr', side_effect=radarr), patch.object(app, 'invalidateDownloadCache') as invalidate, \
                self.assertRaisesRegex(ValueError, 'unmonitored, but Radarr did not confirm file deletion'):
            app.deleteSpecialFile(100, 501, True)
        self.assertFalse(radarr.movie['monitored'])
        self.assertEqual(501, radarr.movie['movieFileId'])
        invalidate.assert_called_once()

    def test_file_deletion_endpoint_rejects_invalid_ids_and_monitoring_options(self):
        valid = {'movieId': 100, 'movieFileId': 501, 'unmonitor': True}
        for key, values in [('movieId', [None, True, '100', 0, -1]),
                            ('movieFileId', [None, True, '501', 0, -1]), ('unmonitor', [None, 1, 'false'])]:
            for value in values:
                with self.subTest(key=key, value=value), patch.object(app, 'deleteSpecialFile') as delete, self.assertRaises(ValueError):
                    self.handler.deleteSpecialFileRequest({**valid, key: value})
                delete.assert_not_called()

    def test_movie_file_id_requires_a_present_file_and_positive_integer(self):
        from hecklarr.monitoring import movieMonitoring
        for value in [None, True, False, 0, -1, '501']:
            with self.subTest(value=value):
                self.assertIsNone(movieMonitoring({**self.movie, 'movieFileId': value})['movieFileId'])
        self.assertEqual(501, movieMonitoring({**self.movie, 'movieFileId': 501})['movieFileId'])
        self.assertIsNone(movieMonitoring({**self.movie, 'hasFile': False, 'movieFileId': 501})['movieFileId'])

    def test_new_comedian_requires_an_explicit_valid_mode(self):
        for mode in [None, '', 'invalid', [], True]:
            with self.subTest(mode=mode), patch.object(app, 'tmdb') as tmdb, self.assertRaises(ValueError):
                self.handler.addComedian({'id': 2, 'monitorMode': mode})
            tmdb.assert_not_called()

    def test_future_cutoff_is_local_and_stable_across_saves_and_restart(self):
        stamp = dt.datetime(2026, 10, 21, 23, 30, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
        with patch.dict(app.os.environ, {'TZ': 'America/Detroit'}), patch.object(app.dt, 'datetime') as clock, \
                patch.object(app, 'tmdb', return_value={'name': 'Dave Chappelle'}), patch.object(app, 'radarr'):
            clock.now.return_value = stamp
            self.handler.addComedian({'id': 2, 'monitorMode': 'future'})
            self.assertTrue(any(getattr(call.args[0], 'key', None) == 'America/Detroit'
                                for call in clock.now.call_args_list))
            clock.now.return_value = stamp + dt.timedelta(days=7)
            self.handler.updateComedianMode({'id': 2, 'monitorMode': 'future'})
        person = next(row for row in app.loadSettings()['comedians'] if row['id'] == 2)
        self.assertEqual('2026-10-21', person['monitorAfter'])
        self.assertEqual('future', person['monitorMode'])

    def test_mode_changes_apply_to_feed_without_changing_existing_radarr_movies(self):
        with patch.object(app, 'radarr') as radarr:
            self.handler.updateComedianMode({'id': 1, 'monitorMode': 'all'})
            self.assertEqual(15, len(app.automaticMovies(app.SETTINGS, app.SNAPSHOT)))
            self.handler.updateComedianMode({'id': 1, 'monitorMode': 'manual'})
            self.assertEqual([], app.automaticMovies(app.SETTINGS, app.SNAPSHOT))
        self.assertTrue(all(call.args[0] == 'command' for call in radarr.call_args_list))

    def test_empty_feed_setup_only_acknowledges_the_specific_warning(self):
        warning = {'errorMessage': 'No results were returned from your import list, please check your settings and the log for details.', 'isWarning': True}
        for failures, allowed in [([warning], True), ([{**warning, 'isWarning': False}], False),
                                  ([warning, {'errorMessage': 'Connection failed', 'isWarning': False}], False),
                                  ([], False), ({'message': 'Invalid settings'}, False)]:
            calls = []
            def radarr(path, settings, body=None, method=None, calls=calls, failures=failures):
                calls.append(path)
                if path == 'rootfolder':
                    return [{'path': '/comedy'}]
                if path == 'config/importlist':
                    return {'listSyncLevel': 'disabled'}
                if path == 'importlist':
                    return [{'id': 1, 'fields': [{'name': 'url'}]}]
                if path == 'importlist/1':
                    raise app.RadarrValidationError(failures)
                if path == 'importlist/1?forceSave=true':
                    return {**body, 'id': 1}
                if path == 'command':
                    return {'id': 2}
                raise AssertionError(path)
            with self.subTest(failures=failures), patch.object(app, 'radarr', side_effect=radarr):
                if allowed:
                    self.assertEqual(1, app.syncRadarr()['id'])
                else:
                    with self.assertRaises(app.RadarrValidationError):
                        app.syncRadarr()
            self.assertEqual(allowed, 'importlist/1?forceSave=true' in calls)

    def test_initial_setup_connects_before_adding_any_comedians(self):
        app.SNAPSHOT = {}
        app.SETTINGS['comedians'] = []
        def radarr(path, settings, body=None, method=None):
            if path == 'rootfolder':
                return [{'path': '/comedy'}]
            if path == 'config/importlist':
                return {'listSyncLevel': 'disabled'}
            if path == 'importlist':
                return [{'id': 1, 'fields': [{'name': 'url'}]}]
            if path == 'importlist/1':
                return {**body, 'id': 1}
            if path == 'command':
                return {'id': 2}
            raise AssertionError(path)
        with patch.object(app, 'radarr', side_effect=radarr), patch.object(app, 'tmdb') as tmdb:
            status, result = self.handler.authenticatedPost('/api/sync', {})
        self.assertEqual(200, status)
        self.assertEqual(1, result['id'])
        tmdb.assert_not_called()
        self.assertEqual([], app.SNAPSHOT['items'])
        self.assertEqual((200, []), self.handler.movieFeed({'key': ['feed']}))


class AutomaticFeedTest(unittest.TestCase):
    def test_future_only_uses_release_dates_and_not_discovery_dates(self):
        settings = {'comedians': [{'id': 1, 'monitorMode': 'future', 'monitorAfter': '2026-10-21'}]}
        dates = ['2020-01-01', '2026-10-21', '2026-10-22', '2027-01-01', '', 'invalid', '2026-02-30', None]
        snapshot = {'items': [{'tmdbId': i, 'personIds': [1], 'releaseDate': date} for i, date in enumerate(dates)]}
        self.assertEqual([2, 3], [row['tmdbId'] for row in app.automaticMovies(settings, snapshot)])
        # Retaining/discovering the old release in another snapshot never approves it.
        self.assertEqual([], app.automaticMovies(settings, {'items': snapshot['items'][:1]}))

    def test_shared_special_is_added_once_if_any_owner_qualifies(self):
        settings = {'comedians': [{'id': 1, 'monitorMode': 'manual'}, {'id': 2, 'monitorMode': 'all'}]}
        movie = {'tmdbId': 100, 'personIds': [1, 2]}
        self.assertEqual([movie], app.automaticMovies(settings, {'items': [movie]}))
        settings['comedians'][0]['monitorMode'] = 'all'
        self.assertEqual([movie], app.automaticMovies(settings, {'items': [movie]}))
        settings['excludedMovieIds'] = [100]
        self.assertEqual([], app.automaticMovies(settings, {'items': [movie]}))

    def test_legacy_modes_and_snapshots_preserve_automation_but_removed_owners_do_not(self):
        movie = {'tmdbId': 100, 'personId': 1}
        self.assertEqual([movie], app.automaticMovies({'comedians': [{'id': 1}]}, {'items': [movie]}))
        self.assertEqual([], app.automaticMovies({'comedians': []}, {'items': [movie]}))

    def test_transport_preserves_radarr_validation_details_without_exposing_them_in_error_message(self):
        failures = [{'errorMessage': 'private URL', 'isWarning': False}]
        error = urllib.error.HTTPError('http://radarr', 400, 'Bad request', {}, io.BytesIO(json.dumps(failures).encode()))
        opener = unittest.mock.Mock()
        opener.open.side_effect = error
        with self.assertRaises(clients.RadarrValidationError) as caught:
            clients.requestJson('http://radarr', 'key', {}, opener=opener)
        self.assertEqual(failures, caught.exception.failures)
        self.assertNotIn('private URL', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
