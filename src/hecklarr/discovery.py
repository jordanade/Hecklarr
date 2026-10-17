"""Pure TMDB catalog classification and snapshot construction."""

import re


def normalize(value):
    return re.sub(r'[^a-z0-9]', '', value.lower())


def classify(movie, comedian):
    """Decide whether a TMDB movie is a stand-up special for one comedian.

    The rules deliberately require several independent signals when TMDB lacks
    its stand-up keyword. Ambiguous credits remain reviewable instead of being
    silently added to Radarr.
    """
    movie_id = movie['id']
    if movie_id in comedian.get('excludeIds', []):
        return False, 'Explicitly excluded'
    if movie_id in comedian.get('includeIds', []):
        return True, 'Confirmed special'
    cast = [entry for entry in movie.get('credits', {}).get('cast', []) if entry['id'] == comedian['id']]
    if not cast:
        return False, 'No performer credit'
    performer = cast[0]
    role = (performer.get('character') or '').strip().lower()
    if 'archive' in role or 'uncredited' in role:
        return False, 'Archive footage or cameo'
    if role and not re.search(r'\b(self|himself|herself|themselves)\b', role):
        return False, 'Acting role'
    if performer.get('order') != 0:
        return False, 'Not the lead performer'
    if (movie.get('runtime') or 0) < 20:
        return False, 'Shorter than 20 minutes or runtime unknown'
    if 35 not in [genre['id'] for genre in movie.get('genres', [])]:
        return False, 'Not classified as comedy'
    if 9716 in [keyword['id'] for keyword in movie.get('keywords', {}).get('keywords', [])]:
        return True, 'Lead performer and stand-up keyword'

    title = movie.get('title', '')
    description = movie.get('overview', '').lower()
    performer_names = {normalize(name) for name in [comedian['name'], *comedian.get('also_known_as', [])]}
    performer_names.discard('')
    title_prefix, separator, subtitle = title.partition(':')
    by_performer = re.search(r'\bby\s+(.+)$', title, re.IGNORECASE)
    titled_performer = bool(separator and subtitle.strip() and normalize(title_prefix) in performer_names)
    special_title = any(normalize(title) in {name + 'special', 'a' + name + 'special'}
                        for name in performer_names)
    billed_performer = (titled_performer or special_title or
                        bool(by_performer and normalize(by_performer[1]) in performer_names))
    named = any(name in normalize(title) for name in performer_names)

    # A synopsis can identify a documentary; the broad Documentary genre cannot.
    documentary_story = re.search(
        r'\b(?:documentary|biograph(?:y|ical)|portrait|interviews? with|behind[ -]the[ -]scenes|making[ -]of)\b',
        description)
    explicit_special = re.search(r'\b(?:comedy|stand[ -]?up) special\b', description)
    if documentary_story and not explicit_special:
        return False, 'Described as a documentary or biography; review metadata'

    standup_description = re.search(r'\bstand[ -]?up\b|\bcomedy special\b', description)
    if named and (standup_description or (role and re.search(r'\brecorded live\b|\bfilmed live\b', description))):
        if role or billed_performer:
            return True, 'Named performer and live-special description'
    wrote_performance = any(
        entry.get('id') == comedian['id'] and entry.get('job') in {'Writer', 'Screenplay'}
        for entry in movie.get('credits', {}).get('crew', [])
    )
    if billed_performer and wrote_performance:
        return True, 'Performer billing and writing credit'
    if role and wrote_performance and re.search(r'\bstand[ -]?up comedy\b', title, re.IGNORECASE):
        return True, 'Lead self-performance and stand-up title'
    staged_performance = re.search(
        r'\b(?:performs?|performing|delivers?|delivering|takes?(?: to)? the stage|returns? to (?:the|a) (?:stage|club))\b',
        description)
    comedy_material = re.search(r'\b(?:jokes|routines?|stand[ -]?up|comedy set|monologue)\b', description)
    if role and wrote_performance and staged_performance and comedy_material:
        return True, 'Lead self-performance and comedy performance description'
    if not role:
        return False, 'Performer role unspecified and no clear stand-up evidence'
    return False, 'No clear stand-up classification; review metadata or add an inclusion'


def buildSnapshot(settings, previous, fetch, timestamp, not_found_error):
    """Build a complete immutable catalog candidate from current TMDB metadata."""
    accepted = {}
    reviewed = []
    people = []
    selected = {person['id']: person for person in settings['comedians']}
    for selection in selected.values():
        try:
            profile = fetch(f'person/{selection["id"]}', settings)
            person = {**selection, 'name': profile['name'], 'also_known_as': profile.get('also_known_as') or []}
            credits = fetch(f'person/{person["id"]}/movie_credits', settings)
        except not_found_error:
            continue
        people.append({'id': person['id'], 'name': person['name']})
        globally_excluded = set(settings.get('excludedMovieIds', []))
        retained_ids = {
            row['tmdbId'] for row in previous.get('items', []) if row['personId'] == person['id']
        } - set(person.get('excludeIds', [])) - globally_excluded
        credit_ids = {entry['id'] for entry in credits['cast']}
        candidates = set(credit_ids)
        candidates.update(person.get('includeIds', []))
        candidates.update(retained_ids)
        candidates.update(globally_excluded & (credit_ids | set(person.get('includeIds', []))))
        for movie_id in sorted(candidates):
            try:
                movie = fetch(f'movie/{movie_id}?append_to_response=keywords,credits', settings)
            except not_found_error:
                continue
            classifier_person = {
                **person,
                'excludeIds': set(person.get('excludeIds', [])) | globally_excluded,
            }
            include, reason = classify(movie, classifier_person)
            # Retention protects a confirmed feed item from transient TMDB credit edits.
            if not include and movie_id in retained_ids:
                include, reason = True, 'Retained special; metadata refreshed'
            release_date = movie.get('release_date') or ''
            row = {
                'tmdbId': movie_id,
                'title': movie['title'],
                'year': release_date[:4],
                'releaseDate': release_date,
                'personId': person['id'],
                'comedian': person['name'],
                'reason': reason,
            }
            reviewed.append({**row, 'included': include})
            if include:
                accepted[movie_id] = row
    return {
        'updatedAt': timestamp(),
        'items': sorted(accepted.values(), key=lambda row: (row['year'], row['title'])),
        'reviewed': reviewed,
        'people': people,
    }
