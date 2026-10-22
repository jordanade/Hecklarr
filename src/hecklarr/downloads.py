"""Pure Radarr download-state calculations.

Network access and cache mutation stay in ``server.py``. Keeping the response
interpretation here makes Radarr API changes testable without server state.
"""

import time


QUEUE_STATE_PRIORITY = [
    'import-blocked',
    'failed',
    'client-unavailable',
    'paused',
    'warning',
    'importing',
    'downloading',
    'queued',
    'unknown',
]


def queueItemState(row):
    """Translate one Radarr queue item into Hecklarr's stable UI vocabulary."""
    status = (row.get('status') or '').lower()
    tracked = (row.get('trackedDownloadState') or '').lower()
    if tracked == 'importblocked':
        return 'import-blocked'
    if status == 'failed' or tracked in ['downloadfailed', 'importfailed']:
        return 'failed'
    if status == 'downloadclientunavailable':
        return 'client-unavailable'
    if status == 'paused':
        return 'paused'
    if status == 'warning' or (row.get('trackedDownloadStatus') or '').lower() == 'warning':
        return 'warning'
    if status == 'completed' or tracked in ['importpending', 'importing']:
        return 'importing'
    if status == 'downloading':
        return 'downloading'
    if status in ['queued', 'delay']:
        return 'queued'
    return 'unknown'


def movieDownloadState(movie, queued):
    """Return the most actionable state for a Radarr movie and its queue items."""
    if movie is None:
        return 'not-in-radarr'
    # An imported file is authoritative even if a completed upgrade remains queued.
    if movie.get('hasFile'):
        return 'downloaded'
    states = [queueItemState(row) for row in queued]
    if states:
        return min(states, key=QUEUE_STATE_PRIORITY.index)
    if movie.get('monitored') is False:
        return 'unmonitored'
    if movie.get('status') in ['announced', 'inCinemas']:
        return 'unreleased'
    return 'missing'


def queueMessages(queued, state):
    """Keep Radarr's explanation for the queue state actually shown to the user."""
    messages = []
    for row in queued:
        if queueItemState(row) != state:
            continue
        candidates = [row.get('errorMessage')]
        statuses = row.get('statusMessages')
        for status in statuses if isinstance(statuses, list) else []:
            if isinstance(status, dict):
                candidates.append(status.get('title'))
                if isinstance(status.get('messages'), list):
                    candidates.extend(status['messages'])
        for message in candidates:
            if isinstance(message, str) and message.strip() and message.strip() not in messages:
                messages.append(message.strip())
    return messages


class MovieListCache:
    """Remember Radarr's tracked movies between polls.

    Browser sessions share this cache. Radarr's movie list covers the whole
    library and can be several megabytes, so it is re-read only when a cached
    state could be wrong: a tracked download left the queue (it may have
    imported), the tracked set changed, a tracked special is not in Radarr yet,
    the caller invalidated the cache after changing Radarr, or the cache is old.
    Monitoring changes made in Radarr are picked up sooner by re-reading only
    the tracked movies Radarr already has, one small request each.
    """

    def __init__(self, max_age=1800, missing_retry=300, monitor_age=60, clock=time.monotonic):
        self.max_age = max_age
        self.missing_retry = missing_retry
        self.monitor_age = monitor_age
        self.clock = clock
        self.invalidate()

    def invalidate(self):
        self.movies = None
        self.messages = {}
        self.tracked = frozenset()
        self.queued_ids = set()
        self.fetched_at = 0.0
        self.monitored_at = 0.0

    def needsRefresh(self, movie_ids, queued):
        if self.movies is None or self.tracked != frozenset(movie_ids):
            return True
        age = self.clock() - self.fetched_at
        if age >= self.max_age:
            return True
        if self.queued_ids - set(queued):
            return True
        return age >= self.missing_retry and any(movie_id not in self.movies for movie_id in movie_ids)


def fetchQueue(settings, fetch):
    """Read every Radarr queue page, keyed by Radarr movie ID."""
    queued = {}
    page = 1
    seen = 0
    while True:
        data = fetch(f'queue?page={page}&pageSize=250&includeUnknownMovieItems=false', settings)
        if not isinstance(data, dict):
            raise ValueError('Invalid Radarr queue response')
        records = data.get('records')
        total = data.get('totalRecords')
        if not isinstance(records, list) or not isinstance(total, int) or total < 0:
            raise ValueError('Invalid Radarr queue response')
        for row in records:
            queued.setdefault(row.get('movieId'), []).append(row)
        seen += len(records)
        if seen >= total:
            return queued
        # A non-advancing or implausibly long result prevents an infinite request loop.
        if not records or page >= 100:
            raise ValueError('Radarr queue could not be read completely')
        page += 1


def refreshTrackedMovies(settings, by_tmdb, fetch):
    """Re-read tracked Radarr movies individually; None asks for the full list instead."""
    refreshed = {}
    for tmdb_id, row in by_tmdb.items():
        try:
            current = fetch(f"movie/{row.get('id')}", settings)
        except ValueError:
            # A movie deleted in Radarr returns 404; the full list settles it.
            return None
        if not isinstance(current, dict) or current.get('id') != row.get('id') or current.get('tmdbId') != tmdb_id:
            return None
        refreshed[tmdb_id] = current
    return refreshed


def fetchDownloadStatuses(settings, movie_ids, fetch, cache=None):
    """Return download states keyed by TMDB movie ID, reusing a cached movie list when safe."""
    if not movie_ids:
        if cache is not None:
            cache.messages = {}
        return {}
    queued = fetchQueue(settings, fetch)
    by_tmdb = None
    if cache is not None and not cache.needsRefresh(movie_ids, queued):
        by_tmdb = cache.movies
        if cache.clock() - cache.monitored_at >= cache.monitor_age:
            by_tmdb = refreshTrackedMovies(settings, by_tmdb, fetch)
            if by_tmdb is not None:
                cache.movies = by_tmdb
                cache.monitored_at = cache.clock()
    if by_tmdb is None:
        movies = fetch('movie', settings)
        if not isinstance(movies, list):
            raise ValueError('Invalid Radarr movie response')
        by_tmdb = {row['tmdbId']: row for row in movies if row.get('tmdbId') in movie_ids}
        if cache is not None:
            cache.movies = by_tmdb
            cache.tracked = frozenset(movie_ids)
            cache.fetched_at = cache.monitored_at = cache.clock()
    if cache is not None:
        tracked_radarr_ids = {row.get('id') for row in by_tmdb.values()}
        cache.queued_ids = tracked_radarr_ids & set(queued)
    states = {
        str(movie_id): movieDownloadState(
            by_tmdb.get(movie_id),
            queued.get(by_tmdb.get(movie_id, {}).get('id'), []),
        )
        for movie_id in movie_ids
    }
    if cache is not None:
        # Queue messages change on every poll, independently of the cached movie
        # list. Associate them only with the winning state, never a stale upgrade.
        cache.messages = {}
        for movie_id, state in states.items():
            rows = queued.get(by_tmdb.get(int(movie_id), {}).get('id'), [])
            messages = queueMessages(rows, state)
            if messages:
                cache.messages[movie_id] = messages
    return states
