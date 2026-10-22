import copy
import threading
import unittest
from unittest.mock import Mock, patch

from load_app import loadApp

app = loadApp('hecklarr_test_search')
from hecklarr.search import isComedian  # noqa: E402 - loadApp adds the src layout


class SearchRankingTest(unittest.TestCase):
    def setUp(self):
        self.handler = app.Handler.__new__(app.Handler)
        self.handler.reply = lambda status, body: (status, body)
        self.cache = app.ComedianSearchCache()
        self.addCleanup(self.cache.executor.shutdown)
        self.cache_patch = patch.object(app, 'SEARCH_COMEDIANS', self.cache)
        self.cache_patch.start()
        self.addCleanup(self.cache_patch.stop)

    def test_partial_name_prefers_relevant_popular_results_over_reversed_names(self):
        rows = [{'id': 1, 'name': 'Tom Taylor', 'popularity': 100},
                {'id': 2, 'name': 'Taylor Towery', 'popularity': 0.6},
                {'id': 3, 'name': 'Taylor Tomlinson', 'popularity': 0.85},
                {'id': 4, 'name': 'Taylor Tomlinson', 'popularity': 0.38}]
        original = copy.deepcopy(rows)
        self.assertEqual([3, 2, 4, 1], [row['id'] for row in app.rankPeople(rows, 'Taylor To')])
        self.assertEqual(original, rows)

    def test_popularity_wins_regardless_of_exact_prefix_or_later_name_match(self):
        rows = [{'id': 1, 'name': 'Rock', 'popularity': 0.4},
                {'id': 2, 'name': 'Rock Hudson', 'popularity': 2.2},
                {'id': 3, 'name': 'Chris Rock', 'popularity': 4.0},
                {'id': 4, 'name': 'Kid Rock', 'popularity': 2.0}]
        self.assertEqual([3, 2, 4, 1], [row['id'] for row in app.rankPeople(rows, 'rock')])

    def test_case_punctuation_and_accents_do_not_weaken_name_matches(self):
        for name, term in [('Louis C.K.', 'louis ck'), ('Jérémy Ferrari', 'Jeremy Ferrari')]:
            rows = [{'id': 1, 'name': 'An unrelated person', 'popularity': 100}, {'id': 2, 'name': name}]
            with self.subTest(name=name):
                self.assertEqual(2, app.rankPeople(rows, term)[0]['id'])

    def test_original_names_work_and_missing_popularity_keeps_stable_order(self):
        rows = [{'id': 1, 'name': 'A translated name', 'original_name': '张三'},
                {'id': 2, 'name': '张三', 'popularity': None},
                {'id': 3, 'name': '张三', 'popularity': 'invalid'},
                {'id': 4, 'name': '张三', 'popularity': float('nan')}]
        self.assertEqual([1, 2, 3, 4], [row['id'] for row in app.rankPeople(rows, '张三')])

    def test_comedians_precede_more_popular_actors_without_reintroducing_prefix_priority(self):
        rows = [{'id': 1, 'name': 'Rock Hudson', 'popularity': 20},
                {'id': 2, 'name': 'Tony Rock', 'popularity': 1},
                {'id': 3, 'name': 'Chris Rock', 'popularity': 4},
                {'id': 4, 'name': 'Crissy Rock', 'popularity': 2},
                {'id': 5, 'name': 'Rock', 'popularity': 3}]
        self.assertEqual([3, 4, 2, 1, 5], [row['id'] for row in app.rankPeople(rows, 'rock', {2, 3, 4})])

    def test_search_uses_biographies_but_preserves_response_fields_and_keeps_unknown_people(self):
        rows = [{'id': 1, 'name': 'Tom Taylor', 'popularity': 10},
                {'id': 2, 'name': 'Taylor Tomlinson', 'popularity': 1,
                 'known_for': [{'title': 'Look at You'}, {'name': 'After Midnight'}]},
                {'id': 3, 'name': 'Taylor Actor', 'popularity': 100}]
        def fetch(path, settings):
            return {'search/person?query=Taylor+To': {'results': rows},
                    'person/1': {}, 'person/2': {'biography': 'Taylor Tomlinson is an American comedian.'},
                    'person/3': {'biography': 'Taylor Actor is an actor.'}}[path]
        with patch.object(app, 'tmdb', side_effect=fetch) as tmdb:
            status, results = self.handler.searchPeople({'q': [' Taylor To ']}, {})
        self.assertEqual(200, status)
        self.assertEqual({'id': 2, 'name': 'Taylor Tomlinson', 'knownFor': 'Look at You, After Midnight'}, results[0])
        self.assertEqual({1, 2, 3}, {row['id'] for row in results})
        self.assertEqual(4, tmdb.call_count)

    def test_existing_catalog_specials_provide_evidence_when_biographies_are_missing(self):
        rows = [{'id': 1, 'name': 'Rock Hudson', 'popularity': 10},
                {'id': 2, 'name': 'Chris Rock', 'popularity': 1}]
        with patch.object(app, 'tmdb', side_effect=lambda path, settings: {'results': rows} if path.startswith('search/') else {}), \
                patch.object(app, 'SNAPSHOT', {'items': [{'personIds': [2]}]}):
            _, results = self.handler.searchPeople({'q': ['rock']}, {})
        self.assertEqual([2, 1], [row['id'] for row in results])

    def test_short_query_does_not_request_tmdb(self):
        with patch.object(app, 'tmdb') as tmdb, self.assertRaises(ValueError):
            self.handler.searchPeople({'q': ['T']}, {})
        tmdb.assert_not_called()


class ComedianEvidenceTest(unittest.TestCase):
    def test_explicit_occupations_identify_comedians(self):
        for biography in ['Chris Rock is an American comedian, actor, and filmmaker.',
                          'Crissy Rock is an English actress, stand-up comedian and author.',
                          'Tony Rock is an American actor and stand-up comedian. He is the brother of comedian Chris Rock.',
                          'From Wikipedia, the free encyclopedia\n\nSomeone was a British stand-up comic.',
                          'Comedian and actor.']:
            with self.subTest(biography=biography):
                self.assertTrue(isComedian({'biography': biography}))

    def test_comedy_roles_relatives_and_later_mentions_are_not_occupation_evidence(self):
        for biography in ['', 'Rock Hudson was an American actor.', 'Musician / Actor / Artist.',
                          'Someone is the son of a famous comedian.',
                          'Someone is an actor known for working with a comedian.',
                          'Someone is an actor playing a comedian.',
                          'Someone is an actor.\n\nHe was a comedian in a film.',
                          'Someone stars in popular comedy films.']:
            with self.subTest(biography=biography):
                self.assertFalse(isComedian({'biography': biography}))


class ComedianSearchCacheTest(unittest.TestCase):
    def makeCache(self, **kwargs):
        cache = app.ComedianSearchCache(**kwargs)
        self.addCleanup(cache.executor.shutdown)
        return cache

    def test_checks_are_shared_across_queries_expire_and_are_scoped_to_the_tmdb_credential(self):
        now = [0]
        cache = self.makeCache(clock=lambda: now[0], max_age=10)
        fetch = Mock(return_value={'biography': 'Someone is an American comedian.'})
        rows = [{'id': 1}]
        self.assertEqual({1}, cache.comedianIds(rows, {'tmdbApiKey': 'first'}, fetch))
        self.assertEqual({1}, cache.comedianIds(rows, {'tmdbApiKey': 'first'}, fetch))
        self.assertEqual(1, fetch.call_count)
        cache.comedianIds(rows, {'tmdbApiKey': 'second'}, fetch)
        self.assertEqual(2, fetch.call_count)
        now[0] = 10
        cache.comedianIds(rows, {'tmdbApiKey': 'first'}, fetch)
        self.assertEqual(3, fetch.call_count)

    def test_profile_failure_falls_back_without_caching_a_negative_result(self):
        cache = self.makeCache()
        fetch = Mock(side_effect=[ValueError('TMDB unavailable'), {'biography': 'Someone is a comedian.'}])
        self.assertEqual(set(), cache.comedianIds([{'id': 1}], {}, fetch))
        self.assertEqual({1}, cache.comedianIds([{'id': 1}], {}, fetch))

    def test_slow_checks_are_bounded_coalesced_and_warm_the_cache_after_timeout(self):
        cache = self.makeCache(wait_seconds=0.01, max_pending=1)
        release = threading.Event()
        # Release the worker before the executor cleanup, even if an assertion fails.
        self.addCleanup(release.set)
        def slow(path, settings):
            release.wait(2)
            return {'biography': 'Someone is a comedian.'}
        fetch = Mock(side_effect=slow)
        rows = [{'id': 1}, {'id': 2}]
        self.assertEqual(set(), cache.comedianIds(rows, {}, fetch))
        self.assertEqual(set(), cache.comedianIds(rows, {}, fetch))
        self.assertEqual(1, fetch.call_count)
        release.set()
        cache.executor.shutdown()
        self.assertEqual({1}, cache.comedianIds([{'id': 1}], {}, fetch))

    def test_cache_retention_is_bounded(self):
        cache = self.makeCache(capacity=1)
        fetch = Mock(return_value={'biography': ''})
        cache.comedianIds([{'id': 1}], {}, fetch)
        cache.comedianIds([{'id': 2}], {}, fetch)
        self.assertEqual(1, len(cache.cache))
