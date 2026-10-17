"""Pure Radarr download-state calculations.

Network access and cache mutation stay in ``server.py``. Keeping the response
interpretation here makes Radarr API changes testable without server state.
"""


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


def fetchDownloadStatuses(settings, movie_ids, fetch):
    """Fetch every Radarr queue page and return states keyed by TMDB movie ID."""
    if not movie_ids:
        return {}
    movies = fetch('movie', settings)
    if not isinstance(movies, list):
        raise ValueError('Invalid Radarr movie response')
    by_tmdb = {row['tmdbId']: row for row in movies if row.get('tmdbId') in movie_ids}
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
            break
        # A non-advancing or implausibly long result prevents an infinite request loop.
        if not records or page >= 100:
            raise ValueError('Radarr queue could not be read completely')
        page += 1
    return {
        str(movie_id): movieDownloadState(
            by_tmdb.get(movie_id),
            queued.get(by_tmdb.get(movie_id, {}).get('id'), []),
        )
        for movie_id in movie_ids
    }
