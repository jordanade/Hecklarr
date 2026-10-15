import copy
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('hecklarr_discovery', Path(__file__).parents[1] / 'app.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)
REFERENCE = json.loads((Path(__file__).parent / 'fixtures' / 'standup-reference.json').read_text())['specials']


class DiscoveryRegressionTest(unittest.TestCase):
    def test_all_eight_verified_performances_match_without_user_overrides(self):
        for entry in REFERENCE:
            with self.subTest(title=entry['movie']['title']):
                self.assertTrue(app.classify(entry['movie'], entry['person'])[0])

    def test_fresh_snapshot_discovers_reference_specials_from_cast_credits(self):
        people = {entry['person']['id']: entry['person'] for entry in REFERENCE}
        movies = {entry['movie']['id']: entry['movie'] for entry in REFERENCE}

        def fetch(path, settings):
            parts = path.split('/')
            if parts[0] == 'person':
                person_id = int(parts[1])
                if len(parts) == 2:
                    return people[person_id]
                return {'cast': [{'id': entry['movie']['id']} for entry in REFERENCE
                                 if entry['person']['id'] == person_id]}
            return movies[int(parts[1].split('?')[0])]

        with patch.object(app, 'radarr') as radarr:
            result = app.buildSnapshot({'comedians': list(people.values())}, {}, fetch)
            excluded = app.buildSnapshot({'comedians': list(people.values()),
                                          'excludedMovieIds': [455601]}, result, fetch)
        self.assertEqual(set(movies), {row['tmdbId'] for row in result['items']})
        self.assertTrue(all(row['included'] for row in result['reviewed']))
        self.assertEqual(set(movies) - {455601}, {row['tmdbId'] for row in excluded['items']})
        radarr.assert_not_called()

    def test_missing_role_accepts_explicit_special_description_with_named_billing(self):
        entry = next(entry for entry in REFERENCE if entry['movie']['id'] == 396109)
        for phrase in ['standup', 'stand up', 'stand-up', 'comedy special']:
            with self.subTest(phrase=phrase):
                movie = copy.deepcopy(entry['movie'])
                movie['overview'] = f'Gary Gulman performs {phrase} in New York.'
                self.assertTrue(app.classify(movie, entry['person'])[0])
        for restriction in ['documentary', 'acting', 'archive', 'uncredited', 'supporting',
                            'unknown_runtime', 'short', 'non_comedy', 'no_billing', 'live_only', 'no_evidence']:
            with self.subTest(restriction=restriction):
                movie = copy.deepcopy(entry['movie'])
                performer = movie['credits']['cast'][0]
                if restriction == 'documentary':
                    movie['genres'].append({'id': 99})
                elif restriction in ['acting', 'archive', 'uncredited']:
                    performer['character'] = {'acting': 'A character', 'archive': 'Self (archive footage)',
                                              'uncredited': 'Self (uncredited)'}[restriction]
                elif restriction == 'supporting':
                    performer['order'] = 1
                elif restriction == 'unknown_runtime':
                    movie['runtime'] = None
                elif restriction == 'short':
                    movie['runtime'] = 5
                elif restriction == 'non_comedy':
                    movie['genres'] = []
                elif restriction == 'no_billing':
                    movie['title'] = 'A film about Gary Gulman'
                elif restriction == 'live_only':
                    movie['overview'] = 'Gary Gulman recorded live in New York.'
                else:
                    movie['overview'] = 'Gary Gulman discusses his life.'
                self.assertFalse(app.classify(movie, entry['person'])[0])

    def test_written_self_performances_accept_screenplay_and_special_title_forms(self):
        for movie_id in [355177, 55882]:
            entry = next(entry for entry in REFERENCE if entry['movie']['id'] == movie_id)
            self.assertTrue(app.classify(entry['movie'], entry['person'])[0])
            movie = copy.deepcopy(entry['movie'])
            movie['credits']['crew'] = []
            self.assertFalse(app.classify(movie, entry['person'])[0])

    def test_standup_title_needs_writing_self_cast_and_non_documentary_evidence(self):
        entry = next(entry for entry in REFERENCE if entry['movie']['id'] == 1394888)
        for phrase in ['Standup Comedy', 'Stand Up Comedy', 'Stand-Up Comedy']:
            with self.subTest(phrase=phrase):
                movie = copy.deepcopy(entry['movie'])
                movie['title'] = f'Freshman Fifteen: A {phrase} Film'
                self.assertTrue(app.classify(movie, entry['person'])[0])
        for restriction in ['no_writer', 'other_writer', 'acting_cast', 'unknown_cast', 'archive_cast',
                            'documentary', 'no_evidence', 'partial_word']:
            with self.subTest(restriction=restriction):
                movie = copy.deepcopy(entry['movie'])
                if restriction == 'no_writer':
                    movie['credits']['crew'] = []
                elif restriction == 'other_writer':
                    movie['credits']['crew'] = [{'id': 999, 'job': 'Writer'}]
                elif restriction in ['acting_cast', 'unknown_cast', 'archive_cast']:
                    movie['credits']['cast'][1]['character'] = {
                        'acting_cast': 'A character', 'unknown_cast': '',
                        'archive_cast': 'Self (archive footage)'}[restriction]
                elif restriction == 'documentary':
                    movie['genres'].append({'id': 99})
                elif restriction == 'no_evidence':
                    movie['title'] = 'Freshman Fifteen'
                else:
                    movie['title'] = 'Grandstandup Comedy'
                self.assertFalse(app.classify(movie, entry['person'])[0])

    def test_verified_catalog_is_specific_to_movie_and_headliner(self):
        for entry in REFERENCE:
            if (entry['movie']['id'], entry['person']['id']) not in app.VERIFIED_SPECIALS:
                continue
            with self.subTest(title=entry['movie']['title']):
                movie = copy.deepcopy(entry['movie'])
                movie['id'] = 9999999
                self.assertFalse(app.classify(movie, entry['person'])[0])
                for guest in entry['movie']['credits']['cast'][1:]:
                    person = {'id': guest['id'], 'name': 'Guest'}
                    self.assertFalse(app.classify(entry['movie'], person)[0])

    def test_verified_catalog_honors_exclusions_and_minimum_performer_checks(self):
        for entry in REFERENCE:
            if (entry['movie']['id'], entry['person']['id']) not in app.VERIFIED_SPECIALS:
                continue
            with self.subTest(title=entry['movie']['title']):
                person = {**entry['person'], 'excludeIds': [entry['movie']['id']],
                          'includeIds': [entry['movie']['id']]}
                self.assertFalse(app.classify(entry['movie'], person)[0])
                for restriction in ['no_cast', 'acting', 'archive', 'uncredited', 'supporting',
                                    'unknown_runtime', 'short', 'non_comedy']:
                    with self.subTest(restriction=restriction):
                        movie = copy.deepcopy(entry['movie'])
                        performer = movie['credits']['cast'][0]
                        if restriction == 'no_cast':
                            movie['credits']['cast'] = []
                        elif restriction in ['acting', 'archive', 'uncredited']:
                            performer['character'] = {'acting': 'A character', 'archive': 'Self (archive footage)',
                                                      'uncredited': 'Self (uncredited)'}[restriction]
                        elif restriction == 'supporting':
                            performer['order'] = 1
                        elif restriction == 'unknown_runtime':
                            movie['runtime'] = None
                        elif restriction == 'short':
                            movie['runtime'] = 5
                        else:
                            movie['genres'] = []
                        self.assertFalse(app.classify(movie, entry['person'])[0])

    def test_self_led_documentary_and_fictional_role_do_not_become_specials(self):
        person = {'id': 123, 'name': 'Example Comedian'}
        movie = {'id': 999, 'title': 'Example Comedian: A Life in Comedy', 'runtime': 70,
                 'overview': 'An intimate portrait of an artist.', 'genres': [{'id': 35}, {'id': 99}],
                 'credits': {'cast': [{'id': 123, 'order': 0, 'character': 'Self'}],
                             'crew': [{'id': 123, 'job': 'Screenplay'}]}}
        self.assertFalse(app.classify(movie, person)[0])
        movie['genres'] = [{'id': 35}]
        movie['credits']['cast'][0]['character'] = 'A fictional comedian'
        movie['overview'] = 'A comedy special about a standup performer.'
        self.assertFalse(app.classify(movie, person)[0])


if __name__ == '__main__':
    unittest.main()
