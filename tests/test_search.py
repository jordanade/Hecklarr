import copy
import unittest
from unittest.mock import patch

from load_app import loadApp

app = loadApp('hecklarr_test_search')


class SearchRankingTest(unittest.TestCase):
    def setUp(self):
        self.handler = app.Handler.__new__(app.Handler)
        self.handler.reply = lambda status, body: (status, body)

    def test_partial_name_prefers_relevant_popular_results_over_reversed_names(self):
        rows = [{'id': 1, 'name': 'Tom Taylor', 'popularity': 100},
                {'id': 2, 'name': 'Taylor Towery', 'popularity': 0.6},
                {'id': 3, 'name': 'Taylor Tomlinson', 'popularity': 0.85},
                {'id': 4, 'name': 'Taylor Tomlinson', 'popularity': 0.38}]
        original = copy.deepcopy(rows)
        self.assertEqual([3, 2, 4, 1], [row['id'] for row in app.rankPeople(rows, 'Taylor To')])
        self.assertEqual(original, rows)

    def test_exact_name_wins_and_equal_relevance_uses_popularity(self):
        rows = [{'id': 1, 'name': 'Chris Rock Jr.', 'popularity': 100},
                {'id': 2, 'name': 'Chris Rock', 'popularity': 1},
                {'id': 3, 'name': 'Chris Rockwell', 'popularity': 200}]
        self.assertEqual([2, 3, 1], [row['id'] for row in app.rankPeople(rows, 'Chris Rock')])

    def test_case_punctuation_and_accents_do_not_weaken_exact_name_matches(self):
        for name, term in [('Louis C.K.', 'louis ck'), ('Jérémy Ferrari', 'Jeremy Ferrari')]:
            rows = [{'id': 1, 'name': name + ' Jr.', 'popularity': 100}, {'id': 2, 'name': name}]
            with self.subTest(name=name):
                self.assertEqual(2, app.rankPeople(rows, term)[0]['id'])

    def test_original_names_work_and_missing_popularity_keeps_stable_order(self):
        rows = [{'id': 1, 'name': 'A translated name', 'original_name': '张三'},
                {'id': 2, 'name': '张三', 'popularity': None},
                {'id': 3, 'name': '张三', 'popularity': 'invalid'},
                {'id': 4, 'name': '张三', 'popularity': float('nan')}]
        self.assertEqual([1, 2, 3, 4], [row['id'] for row in app.rankPeople(rows, '张三')])

    def test_search_uses_one_tmdb_request_and_returns_ranked_existing_fields(self):
        rows = [{'id': 1, 'name': 'Tom Taylor', 'popularity': 10},
                {'id': 2, 'name': 'Taylor Tomlinson', 'popularity': 1,
                 'known_for': [{'title': 'Look at You'}, {'name': 'After Midnight'}]}]
        with patch.object(app, 'tmdb', return_value={'results': rows}) as tmdb:
            status, results = self.handler.searchPeople({'q': [' Taylor To ']}, {})
        self.assertEqual(200, status)
        self.assertEqual({'id': 2, 'name': 'Taylor Tomlinson', 'knownFor': 'Look at You, After Midnight'}, results[0])
        tmdb.assert_called_once_with('search/person?query=Taylor+To', {})

    def test_short_query_does_not_request_tmdb(self):
        with patch.object(app, 'tmdb') as tmdb, self.assertRaises(ValueError):
            self.handler.searchPeople({'q': ['T']}, {})
        tmdb.assert_not_called()
