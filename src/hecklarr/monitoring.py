"""Automatic feed eligibility and direct, Radarr-owned movie monitoring."""

import datetime as dt


MONITOR_MODES = {'manual', 'future', 'all'}


def automaticMovies(settings, snapshot):
    """Modes control additions, never the monitoring value of existing Radarr movies."""
    people = {person['id']: person for person in settings.get('comedians', [])}
    excluded = set(settings.get('excludedMovieIds', []))
    result = []
    for movie in snapshot.get('items', []):
        if movie['tmdbId'] in excluded:
            continue
        owners = movie.get('personIds', [movie['personId']] if 'personId' in movie else [])
        for owner in owners:
            person = people.get(owner)
            if person is None or movie['tmdbId'] in person.get('excludeIds', []):
                continue
            mode = person.get('monitorMode', 'all')
            if mode == 'all':
                result.append(movie)
                break
            if mode == 'future':
                try:
                    release = dt.date.fromisoformat(movie.get('releaseDate', ''))
                    cutoff = dt.date.fromisoformat(person.get('monitorAfter', ''))
                except (TypeError, ValueError):
                    continue
                if release > cutoff:
                    result.append(movie)
                    break
    return result


def movieMonitoring(movie):
    file_id = movie.get('movieFileId') if movie and movie.get('hasFile') else None
    if not isinstance(file_id, int) or isinstance(file_id, bool) or file_id <= 0:
        file_id = None
    return {'inRadarr': movie is not None, 'radarrId': movie['id'] if movie else None,
            'monitored': movie.get('monitored') if movie else False, 'movieFileId': file_id}


def findMovie(settings, movie_id, fetch):
    movies = fetch(f'movie?tmdbId={movie_id}', settings)
    if not isinstance(movies, list):
        raise ValueError('Invalid Radarr movie response')
    matches = [movie for movie in movies if movie.get('tmdbId') == movie_id]
    if len(matches) > 1 or any(not movie.get('id') or not isinstance(movie.get('monitored'), bool)
                               for movie in matches):
        raise ValueError('Invalid Radarr monitoring response')
    return matches[0] if matches else None


def setMovieMonitoring(settings, movie_id, monitored, fetch):
    """Write to Radarr directly; no durable local movie monitoring state exists.

    POSTs are not retried: a timeout may follow a successful add or search. A
    fresh lookup reconciles additions and updates without creating duplicates.
    """
    movie = findMovie(settings, movie_id, fetch)
    warning = None
    search_requested = False
    if movie is None and monitored:
        root = settings.get('rootFolderPath', '')
        profile = int(settings.get('qualityProfileId', 0))
        if not root.startswith('/') or profile <= 0:
            raise ValueError('Choose a Radarr destination and quality profile in Library settings first')
        lookup = fetch(f'movie/lookup/tmdb?tmdbId={movie_id}', settings)
        if not isinstance(lookup, dict) or lookup.get('tmdbId') != movie_id:
            raise ValueError('Radarr could not find that special')
        body = {**lookup, 'rootFolderPath': root, 'qualityProfileId': profile,
                'monitored': True, 'minimumAvailability': 'released',
                'addOptions': {'searchForMovie': True, 'monitor': 'movieOnly'}}
        try:
            fetch('movie', settings, body)
        except ValueError:
            movie = findMovie(settings, movie_id, fetch)
            if movie is None:
                raise ValueError('Radarr did not confirm the addition. Try again.') from None
            if movie['monitored']:
                warning = 'Monitoring is on, but Radarr did not confirm the search. Check or start the search in Radarr.'
        else:
            movie = findMovie(settings, movie_id, fetch)
            if movie is None:
                raise ValueError('Radarr did not confirm the addition. Refresh its status before trying again.')
            if movie['monitored']:
                return {'movieId': movie_id, 'movie': movieMonitoring(movie), 'warning': None, 'searchRequested': True}
    if movie is not None and movie['monitored'] != monitored:
        try:
            fetch(f'movie/{movie["id"]}', settings, {**movie, 'monitored': monitored}, 'PUT')
        except ValueError:
            # A successful write can lose its response; verify rather than
            # reverting the UI or writing a conflicting local preference.
            current = findMovie(settings, movie_id, fetch)
            if current is None or current['monitored'] != monitored:
                raise ValueError('Radarr did not confirm the monitoring change. Refresh and try again.') from None
            movie = current
        else:
            movie = findMovie(settings, movie_id, fetch)
            if movie is None or movie['monitored'] != monitored:
                raise ValueError('Radarr did not confirm the monitoring change. Refresh and try again.')
        if monitored:
            try:
                fetch('command', settings, {'name': 'MoviesSearch', 'movieIds': [movie['id']]})
                search_requested = True
            except ValueError:
                warning = 'Monitoring is on, but Radarr did not confirm the search. Check or start the search in Radarr.'
    return {'movieId': movie_id, 'movie': movieMonitoring(movie), 'warning': warning, 'searchRequested': search_requested}


def deleteMovieFile(settings, movie_id, file_id, unmonitor, fetch):
    """Delete only the file shown at confirmation, leaving its Radarr movie intact.

    Import/upgrade activity can replace a cached file while the dialog is open.
    Check the live file ID before deletion, and reconcile lost DELETE responses
    without ever deleting a replacement file or the movie entry itself.
    """
    movie = findMovie(settings, movie_id, fetch)
    if movieMonitoring(movie)['movieFileId'] != file_id:
        raise ValueError('The downloaded file changed or is no longer present. Refresh its status and try again.')
    if unmonitor and movie['monitored']:
        setMovieMonitoring(settings, movie_id, False, fetch)
        movie = findMovie(settings, movie_id, fetch)
        if movieMonitoring(movie)['movieFileId'] != file_id:
            raise ValueError('The special was unmonitored, but its downloaded file changed. No file was deleted. Refresh and try again.')
    try:
        fetch(f'moviefile/{file_id}', settings, method='DELETE')
    except ValueError:
        movie = findMovie(settings, movie_id, fetch)
        if movieMonitoring(movie)['movieFileId'] == file_id or (movie and movie.get('hasFile') and not movieMonitoring(movie)['movieFileId']):
            prefix = 'The special was unmonitored, but ' if unmonitor else ''
            raise ValueError(prefix + 'Radarr did not confirm file deletion. Refresh its status before trying again.') from None
    else:
        movie = findMovie(settings, movie_id, fetch)
        if movieMonitoring(movie)['movieFileId'] == file_id or (movie and movie.get('hasFile') and not movieMonitoring(movie)['movieFileId']):
            raise ValueError('Radarr did not confirm file deletion. Refresh its status before trying again.')
    warning = ('The requested file was deleted, but Radarr now has a different downloaded file.'
               if movie and movie.get('hasFile') else None)
    return {'movieId': movie_id, 'movie': movieMonitoring(movie), 'warning': warning, 'fileDeleted': True}
