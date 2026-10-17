import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from load_app import loadApp


app = loadApp('hecklarr_test_discovery')
REFERENCE_DATA = json.loads((Path(__file__).parent / 'fixtures' / 'standup-reference.json').read_text())
REFERENCE = REFERENCE_DATA['specials']


class DiscoveryRegressionTest(unittest.TestCase):
    def test_all_reference_performances_match_without_user_overrides(self):
        for entry in REFERENCE:
            with self.subTest(title=entry['movie']['title']):
                self.assertTrue(app.classify(entry['movie'], entry['person'])[0])

    def test_matching_does_not_depend_on_known_ids_or_artist_names(self):
        for entry in REFERENCE:
            with self.subTest(title=entry['movie']['title']):
                movie = copy.deepcopy(entry['movie'])
                movie['id'] += 100000000
                names = [entry['person']['name'], *entry['person'].get('also_known_as', [])]
                for name in sorted(names, key=len, reverse=True):
                    movie['title'] = movie['title'].replace(name, 'New Performer')
                    movie['overview'] = movie['overview'].replace(name, 'New Performer')
                person = {'id': entry['person']['id'] + 100000000, 'name': 'New Performer'}
                for credit in movie['credits']['cast'] + movie['credits']['crew']:
                    if credit['id'] == entry['person']['id']:
                        credit['id'] = person['id']
                self.assertTrue(app.classify(movie, person)[0])

    def test_documentaries_and_non_performance_films_remain_excluded(self):
        for entry in REFERENCE_DATA['nonSpecials']:
            with self.subTest(title=entry['movie']['title']):
                self.assertFalse(app.classify(entry['movie'], entry['person'])[0])

    def test_stage_name_aliases_keep_older_billing_discoverable(self):
        entry = next(entry for entry in REFERENCE if entry['movie']['id'] == 13587)
        self.assertTrue(app.classify(entry['movie'], entry['person'])[0])
        person = {**entry['person'], 'also_known_as': []}
        self.assertFalse(app.classify(entry['movie'], person)[0])

    def test_performance_descriptions_need_both_comedy_material_and_stage_action(self):
        entry = next(entry for entry in REFERENCE if entry['movie']['id'] == 473812)
        for description in ['Jerry Seinfeld returns to the club to deliver jokes.',
                            'Jerry Seinfeld performs his routines.', 'Jerry Seinfeld takes the stage for a monologue.']:
            with self.subTest(description=description):
                movie = {**entry['movie'], 'overview': description}
                self.assertTrue(app.classify(movie, entry['person'])[0])
        for description in ['Jerry Seinfeld returns to the club where he began.',
                            'Jerry Seinfeld discusses how he writes jokes.',
                            'A documentary about Jerry Seinfeld performing jokes on the road.']:
            with self.subTest(description=description):
                movie = {**entry['movie'], 'overview': description}
                self.assertFalse(app.classify(movie, entry['person'])[0])

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
                movie['credits']['crew'] = []
                movie['overview'] = f'Gary Gulman performs {phrase} in New York.'
                self.assertTrue(app.classify(movie, entry['person'])[0])
        for restriction in ['documentary_description', 'acting', 'archive', 'uncredited', 'supporting',
                            'unknown_runtime', 'short', 'non_comedy', 'no_billing', 'live_only', 'no_evidence']:
            with self.subTest(restriction=restriction):
                movie = copy.deepcopy(entry['movie'])
                movie['credits']['crew'] = []
                performer = movie['credits']['cast'][0]
                if restriction == 'documentary_description':
                    movie['overview'] = 'A documentary portrait of Gary Gulman, a standup comedian.'
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

    def test_standup_title_needs_headliner_self_role_and_writing_evidence(self):
        entry = next(entry for entry in REFERENCE if entry['movie']['id'] == 1394888)
        for phrase in ['Standup Comedy', 'Stand Up Comedy', 'Stand-Up Comedy']:
            with self.subTest(phrase=phrase):
                movie = copy.deepcopy(entry['movie'])
                movie['title'] = f'Freshman Fifteen: A {phrase} Film'
                self.assertTrue(app.classify(movie, entry['person'])[0])
        for restriction in ['no_writer', 'other_writer', 'acting_lead', 'documentary_description',
                            'no_evidence', 'partial_word']:
            with self.subTest(restriction=restriction):
                movie = copy.deepcopy(entry['movie'])
                if restriction == 'no_writer':
                    movie['credits']['crew'] = []
                elif restriction == 'other_writer':
                    movie['credits']['crew'] = [{'id': 999, 'job': 'Writer'}]
                elif restriction == 'acting_lead':
                    movie['credits']['cast'][0]['character'] = 'A fictional comedian'
                elif restriction == 'documentary_description':
                    movie['overview'] = 'Interviews with comedians about their careers.'
                elif restriction == 'no_evidence':
                    movie['title'] = 'Freshman Fifteen'
                else:
                    movie['title'] = 'Grandstandup Comedy'
                self.assertFalse(app.classify(movie, entry['person'])[0])

    def test_documentary_genre_and_supporting_guests_do_not_veto_a_written_performance(self):
        for entry in REFERENCE:
            with self.subTest(title=entry['movie']['title']):
                movie = copy.deepcopy(entry['movie'])
                movie['genres'].append({'id': 99})
                movie['credits']['cast'].extend([
                    {'id': 9991, 'order': 10, 'character': 'Self (uncredited)'},
                    {'id': 9992, 'order': 11, 'character': 'Shoe (voice)'},
                    {'id': 9993, 'order': 12, 'character': ''}])
                self.assertTrue(app.classify(movie, entry['person'])[0])
                for guest in movie['credits']['cast'][1:]:
                    self.assertFalse(app.classify(movie, {'id': guest['id'], 'name': 'Guest'})[0])

    def test_matching_honors_exclusions_and_minimum_performer_checks(self):
        for entry in REFERENCE:
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

    def test_documentary_descriptions_require_review_despite_billing_and_writing_credits(self):
        person = {'id': 123, 'name': 'Example Comedian'}
        movie = {'id': 999, 'title': 'Example Comedian: A Life in Comedy', 'runtime': 70,
                 'genres': [{'id': 35}, {'id': 99}],
                 'credits': {'cast': [{'id': 123, 'order': 0, 'character': 'Self'}],
                             'crew': [{'id': 123, 'job': 'Writer'}]}}
        for description in ['A documentary about a standup comedian.', 'A portrait of a comedian.',
                            'Interviews with standup comedians.', 'A biography of a performer.',
                            'Behind-the-scenes footage of a tour.', 'The making of a performance.']:
            with self.subTest(description=description):
                movie['overview'] = description
                self.assertFalse(app.classify(movie, person)[0])
        movie['overview'] = 'A comedy special with short documentary interludes.'
        self.assertTrue(app.classify(movie, person)[0])


if __name__ == '__main__':
    unittest.main()
