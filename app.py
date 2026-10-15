"""Small, dependency-free TMDB performer watchlist and Radarr Custom List service."""
import base64
import datetime as dt
import hashlib
import hmac
import http.cookies
import io
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

STATE_DIR = Path(os.environ.get('CONFIG_DIR', '/config'))
LOCK = threading.RLock()
REFRESH_LOCK = threading.Lock()
SESSIONS = {}
FAILURES = {}
SETTINGS = {}
SNAPSHOT = {}
LAST_ERROR = None
CACHE_MAX_AGE = dt.timedelta(days=180)
PASSWORD_SLOTS = threading.BoundedSemaphore(2)
DOWNLOAD_STATUSES = {'items': {}, 'updatedAt': None, 'lastError': None}
DOWNLOAD_REFRESH = threading.Event()
DOWNLOAD_POLL_SECONDS = 60


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        def origin(url):
            parsed = urllib.parse.urlsplit(url)
            port = parsed.port
            if port is None:
                port = 443 if parsed.scheme == 'https' else 80
            return (parsed.scheme.lower(), parsed.hostname, port)

        target = urllib.parse.urlsplit(newurl)
        if (target.username is not None or target.password is not None
                or origin(req.full_url) != origin(newurl)):
            raise ValueError('Redirect to a different origin was blocked. Use the final service address.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


HTTP_OPENER = urllib.request.build_opener(SameOriginRedirectHandler())


class RequestReader(io.RawIOBase):
    def __init__(self, connection, timeout):
        super().__init__()
        self.connection = connection
        self.deadline = time.monotonic() + timeout

    def readable(self):
        return True

    def readinto(self, buffer):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Request timed out')
        self.connection.settimeout(remaining)
        return self.connection.recv_into(buffer)


class LimitedThreadingHTTPServer(ThreadingHTTPServer):
    request_queue_size = 32

    def __init__(self, server_address, handler, max_workers=32):
        self.worker_slots = threading.BoundedSemaphore(max_workers)
        super().__init__(server_address, handler)

    def process_request(self, request, client_address):
        if not self.worker_slots.acquire(blocking=False):
            try:
                request.settimeout(1)
                request.sendall(b'HTTP/1.0 503 Service Unavailable\r\n'
                                b'Content-Length: 0\r\nConnection: close\r\n\r\n')
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.worker_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.worker_slots.release()


class TmdbNotFound(ValueError):
    pass


class TmdbAccessDenied(ValueError):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def saveJson(path, data):
    fd, filename = tempfile.mkstemp(prefix=path.stem + '.', suffix='.tmp', dir=path.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(data, indent=2) + '\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def saveSettings(patch):
    global DOWNLOAD_STATUSES
    with LOCK:
        previous_radarr = (SETTINGS.get('radarrUrl'), SETTINGS.get('radarrApiKey'))
        SETTINGS.update(patch)
        # Keep selection/exception IDs as preferences, not cached TMDB names.
        for person in SETTINGS.get('comedians', []):
            person.pop('name', None)
        saveJson(STATE_DIR / 'settings.json', SETTINGS)
        if previous_radarr != (SETTINGS.get('radarrUrl'), SETTINGS.get('radarrApiKey')):
            DOWNLOAD_STATUSES = {'items': {}, 'updatedAt': None, 'lastError': None}
            DOWNLOAD_REFRESH.set()


def loadSettings():
    path = STATE_DIR / 'settings.json'
    settings = json.loads(path.read_text()) if path.exists() else {}
    defaults = {'authUser': '', 'authHash': '', 'tmdbApiKey': '', 'radarrApiKey': '',
                'radarrUrl': '', 'rootFolderPath': '/data/comedy', 'qualityProfileId': 0,
                'feedBaseUrl': '', 'comedians': [], 'radarrListId': None, 'excludedMovieIds': []}
    settings = {**defaults, **settings}
    for person in settings['comedians']:
        person.pop('name', None)
    for key in ['apiKey', 'feedKey']:
        if not settings.get(key):
            settings[key] = secrets.token_hex(24)
    saveJson(path, settings)
    return settings


def requestJson(url, key, body=None, method=None, tmdb=False):
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json', 'User-Agent': 'Hecklarr/0.1'}
    if tmdb:
        if '.' in key:
            headers['Authorization'] = 'Bearer ' + key
        else:
            url += ('&' if '?' in url else '?') + urllib.parse.urlencode({'api_key': key})
    else:
        headers['X-Api-Key'] = key
    payload = json.dumps(body).encode() if body is not None else None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=payload, headers=headers, method=method)
            with HTTP_OPENER.open(req, timeout=30) as response:
                payload = response.read()
                return json.loads(payload) if payload else None
        except urllib.error.HTTPError as error:
            if tmdb and error.code == 404:
                raise TmdbNotFound('TMDB entry no longer available') from None
            if tmdb and error.code in [401, 403]:
                raise TmdbAccessDenied('TMDB access denied; cached metadata cleared') from None
            if (error.code == 429 or error.code >= 500) and attempt < 2:
                time.sleep(min(int(error.headers.get('Retry-After', '2')), 10))
                continue
            raise ValueError(f'{"TMDB" if tmdb else "Radarr"} returned HTTP {error.code}') from None
        except (urllib.error.URLError, TimeoutError):
            if attempt < 2:
                time.sleep(1)
                continue
            raise ValueError(f'{"TMDB" if tmdb else "Radarr"} connection failed') from None


def tmdb(path, settings):
    if not settings.get('tmdbApiKey'):
        raise ValueError('Add a TMDB API key in Settings')
    return requestJson('https://api.themoviedb.org/3/' + path, settings['tmdbApiKey'], tmdb=True)


def radarr(path, settings, body=None, method=None):
    if not settings.get('radarrUrl') or not settings.get('radarrApiKey'):
        raise ValueError('Add the Radarr URL and API key in Settings')
    return requestJson(settings['radarrUrl'].rstrip('/') + '/api/v3/' + path,
                       settings['radarrApiKey'], body, method)


def movieDownloadState(movie, queued):
    if movie is None:
        return 'not-in-radarr'
    if movie.get('hasFile'):
        return 'downloaded'
    states = []
    for row in queued:
        status = (row.get('status') or '').lower()
        tracked = (row.get('trackedDownloadState') or '').lower()
        if tracked == 'importblocked':
            state = 'import-blocked'
        elif status == 'failed' or tracked in ['downloadfailed', 'importfailed']:
            state = 'failed'
        elif status == 'downloadclientunavailable':
            state = 'client-unavailable'
        elif status == 'paused':
            state = 'paused'
        elif status == 'warning' or (row.get('trackedDownloadStatus') or '').lower() == 'warning':
            state = 'warning'
        elif status == 'completed' or tracked in ['importpending', 'importing']:
            state = 'importing'
        elif status == 'downloading':
            state = 'downloading'
        elif status in ['queued', 'delay']:
            state = 'queued'
        else:
            state = 'unknown'
        states.append(state)
    if states:
        priority = ['import-blocked', 'failed', 'client-unavailable', 'paused', 'warning',
                    'importing', 'downloading', 'queued', 'unknown']
        return min(states, key=priority.index)
    if movie.get('monitored') is False:
        return 'unmonitored'
    if movie.get('status') in ['announced', 'inCinemas']:
        return 'unreleased'
    return 'missing'


def fetchDownloadStatuses(settings, movie_ids, fetch=radarr):
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
        if not records or page >= 100:
            raise ValueError('Radarr queue could not be read completely')
        page += 1
    return {str(movie_id): movieDownloadState(by_tmdb.get(movie_id),
                queued.get(by_tmdb.get(movie_id, {}).get('id'), [])) for movie_id in movie_ids}


def updateDownloadStatuses():
    global DOWNLOAD_STATUSES
    with LOCK:
        settings = dict(SETTINGS)
        movie_ids = {row['tmdbId'] for row in SNAPSHOT.get('items', [])}
    if not settings.get('radarrUrl') or not settings.get('radarrApiKey'):
        return
    try:
        items = fetchDownloadStatuses(settings, movie_ids)
        result = {'items': items, 'updatedAt': now(), 'lastError': None}
    except Exception:
        # Keep the last successful result; an outage must not turn downloads into "missing".
        result = None
    with LOCK:
        if ((settings.get('radarrUrl'), settings.get('radarrApiKey'))
                != (SETTINGS.get('radarrUrl'), SETTINGS.get('radarrApiKey'))):
            return
        if result is None:
            DOWNLOAD_STATUSES = {**DOWNLOAD_STATUSES, 'lastError': 'Could not update Radarr download status'}
        else:
            DOWNLOAD_STATUSES = result


def cachedDownloadStatuses():
    with LOCK:
        tracked = {str(row['tmdbId']) for row in SNAPSHOT.get('items', [])}
        return {**DOWNLOAD_STATUSES,
                'items': {key: state for key, state in DOWNLOAD_STATUSES['items'].items() if key in tracked}}


def scheduledDownloadStatuses():
    while True:
        DOWNLOAD_REFRESH.clear()
        updateDownloadStatuses()
        DOWNLOAD_REFRESH.wait(DOWNLOAD_POLL_SECONDS)


def normalize(value):
    return re.sub(r'[^a-z0-9]', '', value.lower())


def classify(movie, comedian):
    movie_id = movie['id']
    if movie_id in comedian.get('excludeIds', []):
        return False, 'Explicitly excluded'
    if movie_id in comedian.get('includeIds', []):
        return True, 'Confirmed special'
    all_cast = movie.get('credits', {}).get('cast', [])
    cast = [entry for entry in all_cast if entry['id'] == comedian['id']]
    if not cast:
        return False, 'No performer credit'
    performer = cast[0]
    role = (performer.get('character') or '').strip().lower()
    standup_keyword = 9716 in [keyword['id'] for keyword in movie.get('keywords', {}).get('keywords', [])]
    if 'archive' in role or 'uncredited' in role:
        return False, 'Archive footage or cameo'
    if role and not re.search(r'\b(self|himself|herself|themselves)\b', role):
        return False, 'Acting role'
    if not role and not standup_keyword:
        return False, 'Performer role unspecified and no stand-up keyword'
    if performer.get('order') != 0:
        return False, 'Not the lead performer'
    if (movie.get('runtime') or 0) < 20:
        return False, 'Shorter than 20 minutes or runtime unknown'
    if 35 not in [genre['id'] for genre in movie.get('genres', [])]:
        return False, 'Not classified as comedy'
    if standup_keyword:
        return True, 'Lead performer and stand-up keyword'
    named = normalize(comedian['name']) in normalize(movie.get('title', ''))
    description = movie.get('overview', '').lower()
    if named and re.search(r'stand[ -]?up|comedy special|recorded live|filmed live', description):
        return True, 'Named performer and live-special description'
    title_prefix, separator, subtitle = movie.get('title', '').partition(':')
    titled_performer = separator and subtitle.strip() and normalize(title_prefix) == normalize(comedian['name'])
    wrote_performance = any(entry.get('id') == comedian['id'] and entry.get('job') == 'Writer'
                            for entry in movie.get('credits', {}).get('crew', []))
    self_cast = all(re.search(r'\b(self|himself|herself|themselves)\b', (entry.get('character') or '').lower())
                    and not re.search(r'archive|uncredited', (entry.get('character') or '').lower())
                    for entry in all_cast)
    documentary = any(genre['id'] == 99 for genre in movie.get('genres', []))
    if titled_performer and wrote_performance and self_cast and not documentary:
        return True, 'Named self-performance and writing credit'
    return False, 'No clear stand-up classification; review metadata or add an inclusion'


def buildSnapshot(settings, previous, fetch=tmdb):
    accepted = {}
    reviewed = []
    people = []
    selected = {person['id']: person for person in settings['comedians']}
    for selection in selected.values():
        try:
            profile = fetch(f'person/{selection["id"]}', settings)
            person = {**selection, 'name': profile['name']}
            credits = fetch(f'person/{person["id"]}/movie_credits', settings)
        except TmdbNotFound:
            continue
        people.append({'id': person['id'], 'name': person['name']})
        globally_excluded = set(settings.get('excludedMovieIds', []))
        retained_ids = {row['tmdbId'] for row in previous.get('items', [])
                        if row['personId'] == person['id']} - set(person.get('excludeIds', [])) - globally_excluded
        credit_ids = {entry['id'] for entry in credits['cast']}
        candidates = set(credit_ids)
        candidates.update(person.get('includeIds', []))
        candidates.update(retained_ids)
        candidates.update(globally_excluded & (credit_ids | set(person.get('includeIds', []))))
        for movie_id in sorted(candidates):
            try:
                movie = fetch(f'movie/{movie_id}?append_to_response=keywords,credits', settings)
            except TmdbNotFound:
                continue
            classifier_person = {**person, 'excludeIds': set(person.get('excludeIds', [])) | globally_excluded}
            include, reason = classify(movie, classifier_person)
            if not include and movie_id in retained_ids:
                include, reason = True, 'Retained special; metadata refreshed'
            release_date = movie.get('release_date') or ''
            row = {'tmdbId': movie_id, 'title': movie['title'],
                   'year': release_date[:4], 'releaseDate': release_date, 'personId': person['id'],
                   'comedian': person['name'], 'reason': reason}
            reviewed.append({**row, 'included': include})
            if include:
                accepted[movie_id] = row
    return {'updatedAt': now(), 'items': sorted(accepted.values(), key=lambda row: (row['year'], row['title'])),
            'reviewed': reviewed, 'people': people}


def clearMetadata():
    global SNAPSHOT
    with LOCK:
        saveJson(STATE_DIR / 'snapshot.json', {})
        SNAPSHOT = {}


def expireMetadata():
    with LOCK:
        # An interrupted atomic write must not leave a second, unbounded cache.
        (STATE_DIR / 'snapshot.tmp').unlink(missing_ok=True)
        for temporary in STATE_DIR.glob('snapshot.*.tmp'):
            temporary.unlink(missing_ok=True)
        if not SNAPSHOT:
            return
        try:
            fetched_at = dt.datetime.fromisoformat(SNAPSHOT['updatedAt'])
            age = dt.datetime.now(dt.timezone.utc) - fetched_at
            valid = dt.timedelta(0) <= age < CACHE_MAX_AGE
        except (KeyError, ValueError, TypeError):
            valid = False
        if not valid:
            clearMetadata()


def maintainMetadata():
    while True:
        expireMetadata()
        time.sleep(3600)


def refresh(sync=False):
    global SNAPSHOT, LAST_ERROR
    with REFRESH_LOCK:
        expireMetadata()
        try:
            with LOCK:
                settings = json.loads(json.dumps(SETTINGS))
                previous = SNAPSHOT
            snapshot = buildSnapshot(settings, previous)
            with LOCK:
                saveJson(STATE_DIR / 'snapshot.json', snapshot)
                SNAPSHOT = snapshot
                LAST_ERROR = None
            DOWNLOAD_REFRESH.set()
            print(f'{now()} Refreshed {len(snapshot["items"])} specials', flush=True)
            if sync and settings.get('radarrListId'):
                radarr('command', settings, {'name': 'ImportListSync', 'definitionId': settings['radarrListId']})
            return snapshot
        except Exception as error:
            if isinstance(error, TmdbAccessDenied):
                clearMetadata()
            LAST_ERROR = str(error) if isinstance(error, ValueError) else type(error).__name__
            action = 'keeping valid previous feed' if SNAPSHOT else 'no cached feed available'
            print(f'{now()} Refresh failed: {LAST_ERROR}; {action}', flush=True)
            raise ValueError(LAST_ERROR) from None


def syncRadarr():
    with LOCK:
        settings = dict(SETTINGS)
    if not settings.get('tmdbApiKey'):
        raise ValueError('Add a TMDB API key or Read Access Token before applying settings')
    if not SNAPSHOT.get('items'):
        raise ValueError('The catalog has no specials yet. Add a comedian or include a special, then refresh before applying this list to Radarr')
    root = settings.get('rootFolderPath', '')
    if not root.startswith('/'):
        raise ValueError('Enter an absolute folder path as seen inside Radarr')
    roots = radarr('rootfolder', settings)
    if root not in [entry['path'] for entry in roots]:
        radarr('rootfolder', settings, {'path': root})
    cleanup = radarr('config/importlist', settings)
    if cleanup['listSyncLevel'] != 'disabled':
        raise ValueError('Disable Radarr import-list cleanup before connecting this feed')
    lists = radarr('importlist', settings)
    existing = next((entry for entry in lists if entry['id'] == settings.get('radarrListId')), None)
    if existing is None:
        existing = next((entry for entry in lists if entry['name'] in ['Hecklarr - Comedy', 'Standuparr - Comedy']), None)
    body = existing or next(entry for entry in radarr('importlist/schema', settings)
                            if entry['implementation'] == 'RadarrListImport')
    body.update({'name': 'Hecklarr - Comedy', 'rootFolderPath': root,
                 'qualityProfileId': int(settings['qualityProfileId']), 'enabled': True,
                 'enableAuto': True, 'monitor': 'movieOnly', 'minimumAvailability': 'released',
                 'searchOnAdd': True})
    feed_url = settings['feedBaseUrl'].rstrip('/') + '/feed/movies.json?key=' + settings['feedKey']
    for field in body['fields']:
        if field['name'] == 'url':
            field['value'] = feed_url
    path = f'importlist/{existing["id"]}' if existing else 'importlist'
    saved = radarr(path, settings, body, 'PUT' if existing else 'POST')
    saveSettings({'radarrListId': saved['id']})
    radarr('command', settings, {'name': 'ImportListSync', 'definitionId': saved['id']})
    return {'id': saved['id'], 'rootFolderPath': root, 'name': saved['name']}


def excludeSpecial(movie_id, delete_from_radarr):
    global SNAPSHOT
    with REFRESH_LOCK:
        with LOCK:
            settings = json.loads(json.dumps(SETTINGS))
            snapshot = json.loads(json.dumps(SNAPSHOT))
        movie = next((row for row in snapshot.get('items', []) if row['tmdbId'] == movie_id), None)
        if movie is None:
            movie = next((row for row in snapshot.get('reviewed', []) if row['tmdbId'] == movie_id), None)
        if movie is None and movie_id not in settings.get('excludedMovieIds', []):
            raise ValueError('That special is no longer in the catalog. Refresh and try again.')
        matches = []
        if delete_from_radarr:
            matches = [row for row in radarr('movie', settings)
                       if int(row.get('tmdbId', 0)) == movie_id]
            if any(not row.get('id') for row in matches):
                raise ValueError('Radarr returned a movie without an ID; no changes were made')

        excluded = set(settings.get('excludedMovieIds', []))
        excluded.add(movie_id)
        saveSettings({'excludedMovieIds': sorted(excluded)})
        snapshot['items'] = [row for row in snapshot.get('items', []) if row['tmdbId'] != movie_id]
        matching_reviews = [row for row in snapshot.get('reviewed', []) if row['tmdbId'] == movie_id]
        for row in matching_reviews:
            row['included'] = False
            row['reason'] = 'Explicitly excluded from Hecklarr'
        if not matching_reviews and movie:
            snapshot.setdefault('reviewed', []).append({**movie, 'included': False,
                                                         'reason': 'Explicitly excluded from Hecklarr'})
        with LOCK:
            saveJson(STATE_DIR / 'snapshot.json', snapshot)
            SNAPSHOT = snapshot

        if delete_from_radarr:
            try:
                for row in matches:
                    radarr(f"movie/{row['id']}?deleteFiles=true", settings, method='DELETE')
            except ValueError as error:
                raise ValueError('The special was excluded from the feed, but Radarr deletion did not finish: ' + str(error)) from None
            if settings.get('radarrListId'):
                try:
                    radarr('command', settings, {'name': 'ImportListSync',
                                                 'definitionId': settings['radarrListId']})
                except ValueError as error:
                    raise ValueError('The special was excluded and removed from Radarr, but the list sync failed: ' + str(error)) from None
        return {'removedFromRadarr': len(matches),
                'hadFiles': sum(bool(row.get('hasFile')) for row in matches)}


def removeComedian(person_id, delete_from_radarr):
    global SNAPSHOT
    with REFRESH_LOCK:
        with LOCK:
            settings = json.loads(json.dumps(SETTINGS))
            snapshot = json.loads(json.dumps(SNAPSHOT))
        person = next((row for row in settings.get('comedians', []) if row['id'] == person_id), None)
        if person is None:
            raise ValueError('That comedian is no longer in Hecklarr. Refresh and try again.')
        movie_ids = {row['tmdbId'] for row in snapshot.get('items', [])
                     if row.get('personId') == person_id}
        matches = []
        if delete_from_radarr and movie_ids:
            matches = [row for row in radarr('movie', settings)
                       if int(row.get('tmdbId', 0)) in movie_ids]
            if any(not row.get('id') for row in matches):
                raise ValueError('Radarr returned a movie without an ID; no changes were made')
            try:
                for row in matches:
                    radarr(f"movie/{row['id']}?deleteFiles=true", settings, method='DELETE')
            except ValueError as error:
                raise ValueError('Radarr deletion did not finish; the comedian remains in Hecklarr. '
                                 'Some matching movies may already have been removed: ' + str(error)) from None

        saveSettings({'comedians': [row for row in SETTINGS['comedians'] if row['id'] != person_id]})
        snapshot['items'] = [row for row in snapshot.get('items', []) if row.get('personId') != person_id]
        snapshot['reviewed'] = [row for row in snapshot.get('reviewed', [])
                                if row.get('personId') != person_id]
        snapshot['people'] = [row for row in snapshot.get('people', []) if row.get('id') != person_id]
        with LOCK:
            saveJson(STATE_DIR / 'snapshot.json', snapshot)
            SNAPSHOT = snapshot
        return {'removedFromRadarr': len(matches),
                'hadFiles': sum(bool(row.get('hasFile')) for row in matches),
                'trackedCount': len(movie_ids)}


def checkPassword(password, encoded):
    try:
        kind, n, r, p, salt, expected = encoded.split('$')
        if kind != 'scrypt':
            return False
        expected = base64.b64decode(expected)
        with PASSWORD_SLOTS:
            actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n),
                                    r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def publicSettings():
    expireMetadata()
    with LOCK:
        names = {row['personId']: row['comedian'] for row in SNAPSHOT.get('items', [])
                 if 'personId' in row and 'comedian' in row}
        names.update({row['id']: row['name'] for row in SNAPSHOT.get('people', [])})
        allowed = ['radarrUrl', 'rootFolderPath', 'qualityProfileId', 'feedBaseUrl', 'radarrListId']
        return {**{key: SETTINGS.get(key) for key in allowed},
                'comedians': [{**person, 'name': names.get(person['id'], f'TMDB person {person["id"]}')}
                              for person in SETTINGS.get('comedians', [])],
                'hasTmdbKey': bool(SETTINGS.get('tmdbApiKey')),
                'hasRadarrKey': bool(SETTINGS.get('radarrApiKey'))}


class Handler(BaseHTTPRequestHandler):
    timeout = 10

    def setup(self):
        super().setup()
        self.rfile.close()
        # A total read deadline also stops clients that slowly drip header/body bytes.
        self.rfile = io.BufferedReader(RequestReader(self.connection, self.timeout))

    def log_message(self, *args):
        pass  # Feed query strings contain a credential.

    def reply(self, status, body, content_type='application/json', cookie=None):
        payload = body if isinstance(body, bytes) else json.dumps(body).encode() if content_type == 'application/json' else body.encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
        self.send_header('Content-Length', str(len(payload)))
        if cookie:
            for value in cookie if isinstance(cookie, list) else [cookie]:
                self.send_header('Set-Cookie', value)
        self.end_headers()
        self.wfile.write(payload)

    def authenticated(self):
        api_key = self.headers.get('X-Api-Key', '')
        if api_key and hmac.compare_digest(api_key.encode(), SETTINGS['apiKey'].encode()):
            return True
        cookies = http.cookies.SimpleCookie()
        try:
            cookies.load(self.headers.get('Cookie', ''))
        except http.cookies.CookieError:
            return False
        token = cookies.get('hecklarr_session') or cookies.get('standuparr_session')
        with LOCK:
            return bool(token and SESSIONS.get(hashlib.sha256(token.value.encode()).hexdigest(), 0) > time.time())

    def do_GET(self):
        self.connection.settimeout(self.timeout)
        expireMetadata()
        url = urllib.parse.urlsplit(self.path)
        path = url.path
        query = urllib.parse.parse_qs(url.query)
        if path in ['/', '/app.js', '/style.css']:
            filename, kind = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'),
                              '/style.css': ('style.css', 'text/css')}[path]
            return self.reply(200, Path(__file__).with_name(filename).read_text(), kind)
        if path == '/icon.png':
            return self.reply(200, Path(__file__).with_name('icon.png').read_bytes(), 'image/png')
        if path == '/tmdb-logo.svg':
            return self.reply(200, Path(__file__).with_name('tmdb-logo.svg').read_bytes(), 'image/svg+xml')
        if path == '/api/health':
            return self.reply(200 if SNAPSHOT else 503, {'ready': bool(SNAPSHOT),
                              'count': len(SNAPSHOT.get('items', [])), 'updatedAt': SNAPSHOT.get('updatedAt'),
                              'lastError': LAST_ERROR})
        if path == '/api/auth':
            return self.reply(200, {'authenticated': self.authenticated(), 'username': SETTINGS['authUser'],
                                    'setupRequired': not bool(SETTINGS.get('authHash'))})
        if path == '/feed/movies.json':
            if not hmac.compare_digest(query.get('key', [''])[0].encode(), SETTINGS['feedKey'].encode()):
                return self.reply(401, {'error': 'Invalid feed key'})
            if not SNAPSHOT:
                return self.reply(503, {'error': 'No successful refresh yet'})
            # Radarr Custom Lists parse MovieResultResource.Id, not a tmdbId field.
            return self.reply(200, [{'id': row['tmdbId'], 'title': row['title']}
                                    for row in SNAPSHOT['items']])
        if not self.authenticated():
            return self.reply(401, {'error': 'Log in to continue'})
        try:
            with LOCK:
                settings = dict(SETTINGS)
            if path == '/api/settings':
                return self.reply(200, publicSettings())
            if path == '/api/status':
                return self.reply(200, {**SNAPSHOT, 'lastError': LAST_ERROR,
                                        'downloadStatuses': cachedDownloadStatuses()})
            if path == '/api/download-status':
                return self.reply(200, cachedDownloadStatuses())
            if path == '/api/search':
                term = query.get('q', [''])[0].strip()
                if len(term) < 2:
                    raise ValueError('Enter at least two characters')
                data = tmdb('search/person?' + urllib.parse.urlencode({'query': term}), settings)
                return self.reply(200, [{'id': row['id'], 'name': row['name'],
                                        'knownFor': ', '.join(movie.get('title', movie.get('name', ''))
                                                              for movie in row.get('known_for', [])[:3])}
                                       for row in data['results']])
            if path == '/api/radarr/options':
                return self.reply(200, {'roots': radarr('rootfolder', settings),
                                       'profiles': [{'id': row['id'], 'name': row['name']}
                                                    for row in radarr('qualityprofile', settings)]})
            return self.reply(404, {'error': 'Not found'})
        except ValueError as error:
            if isinstance(error, TmdbAccessDenied):
                clearMetadata()
            return self.reply(400, {'error': str(error)})

    def do_POST(self):
        expireMetadata()
        if self.headers.get('X-Hecklarr') != '1' and self.headers.get('X-Standuparr') != '1':
            return self.reply(403, {'error': 'Missing request header'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > 65536:
                raise ValueError('Invalid request size')
            payload = self.rfile.read(length)
            self.connection.settimeout(self.timeout)
            body = json.loads(payload or b'{}')
            if not isinstance(body, dict):
                raise ValueError('Expected an object')
            if self.path == '/api/setup':
                with LOCK:
                    if SETTINGS.get('authHash'):
                        return self.reply(409, {'error': 'An account already exists. Log in to continue.'})
                    username = str(body.get('username', '')).strip()
                    password = str(body.get('password', ''))
                    if not username or len(username) > 80:
                        raise ValueError('Enter a username of 1 to 80 characters')
                    if len(password) < 8:
                        raise ValueError('Use a password with at least 8 characters')
                    if password != body.get('passwordConfirmation'):
                        raise ValueError('Passwords do not match')
                    salt = secrets.token_bytes(16)
                    with PASSWORD_SLOTS:
                        hashed = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=64)
                    encoded = 'scrypt$16384$8$1$' + base64.b64encode(salt).decode() + '$' + base64.b64encode(hashed).decode()
                    saveSettings({'authUser': username, 'authHash': encoded})
                return self.reply(201, {'ok': True})
            if self.path == '/api/login':
                if not SETTINGS.get('authHash'):
                    return self.reply(409, {'error': 'Create your account first'})
                ip = self.client_address[0]
                with LOCK:
                    cutoff = time.time() - 600
                    for address in list(FAILURES):
                        recent = [stamp for stamp in FAILURES[address] if stamp > cutoff]
                        if recent:
                            FAILURES[address] = recent
                        else:
                            FAILURES.pop(address)
                    recent = FAILURES.get(ip, [])
                    if len(recent) >= 8 or (ip not in FAILURES and len(FAILURES) >= 1024):
                        return self.reply(429, {'error': 'Too many attempts. Try again in ten minutes.'})
                    # Reserve before hashing so concurrent attempts cannot share the same budget.
                    FAILURES[ip] = recent + [time.time()]
                user_ok = hmac.compare_digest(str(body.get('username', '')).encode(), SETTINGS['authUser'].encode())
                pass_ok = checkPassword(str(body.get('password', '')), SETTINGS['authHash'])
                if not user_ok or not pass_ok:
                    return self.reply(401, {'error': 'Incorrect username or password'})
                token = secrets.token_urlsafe(32)
                with LOCK:
                    FAILURES.pop(ip, None)
                    expired = [key for key, expiry in SESSIONS.items() if expiry <= time.time()]
                    for key in expired:
                        SESSIONS.pop(key)
                    SESSIONS[hashlib.sha256(token.encode()).hexdigest()] = time.time() + 43200
                    saveJson(STATE_DIR / 'sessions.json', SESSIONS)
                secure = '; Secure' if self.headers.get('X-Forwarded-Proto') == 'https' else ''
                return self.reply(200, {'ok': True}, cookie=f'hecklarr_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200{secure}')
            if not self.authenticated():
                return self.reply(401, {'error': 'Log in to continue'})
            if self.path == '/api/logout':
                cookies = http.cookies.SimpleCookie(self.headers.get('Cookie', ''))
                with LOCK:
                    for name in ['hecklarr_session', 'standuparr_session']:
                        token = cookies.get(name)
                        if token:
                            SESSIONS.pop(hashlib.sha256(token.value.encode()).hexdigest(), None)
                    saveJson(STATE_DIR / 'sessions.json', SESSIONS)
                return self.reply(200, {'ok': True}, cookie=[name + '=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0'
                                                           for name in ['hecklarr_session', 'standuparr_session']])
            if self.path == '/api/settings':
                patch = {key: str(body[key]).strip() for key in ['radarrUrl', 'feedBaseUrl', 'rootFolderPath'] if key in body}
                for key in ['radarrUrl', 'feedBaseUrl']:
                    if key in patch and urllib.parse.urlsplit(patch[key]).scheme not in ['http', 'https']:
                        raise ValueError('Use an http or https URL')
                for key in ['tmdbApiKey', 'radarrApiKey']:
                    if body.get(key):
                        patch[key] = str(body[key]).strip()
                if 'qualityProfileId' in body:
                    patch['qualityProfileId'] = int(body['qualityProfileId'])
                saveSettings(patch)
                return self.reply(200, publicSettings())
            if self.path == '/api/comedians':
                person_id = int(body['id'])
                person = tmdb(f'person/{person_id}', SETTINGS)
                with REFRESH_LOCK:
                    people = SETTINGS['comedians'][:]
                    if not any(row['id'] == person_id for row in people):
                        people.append({'id': person_id, 'includeIds': [], 'excludeIds': []})
                    saveSettings({'comedians': people})
                result = publicSettings()
                for row in result['comedians']:
                    if row['id'] == person_id:
                        row['name'] = person['name']
                return self.reply(200, result)
            if self.path == '/api/comedians/remove':
                person_id = int(body.get('id', 0))
                delete_from_radarr = body.get('deleteFromRadarr', False)
                if person_id <= 0 or not isinstance(delete_from_radarr, bool):
                    raise ValueError('Choose a comedian and deletion option')
                result = removeComedian(person_id, delete_from_radarr)
                return self.reply(200, {'settings': publicSettings(), **result})
            if self.path == '/api/overrides':
                with REFRESH_LOCK:
                    people = json.loads(json.dumps(SETTINGS['comedians']))
                    person = next(row for row in people if row['id'] == int(body['personId']))
                    movie_id = int(body['movieId'])
                    if movie_id <= 0 or body['action'] not in ['include', 'exclude']:
                        raise ValueError('Choose include or exclude and a valid TMDB movie ID')
                    for key in ['includeIds', 'excludeIds']:
                        person[key] = [entry for entry in person.get(key, []) if entry != movie_id]
                    person[body['action'] + 'Ids'].append(movie_id)
                    patch = {'comedians': people}
                    if body['action'] == 'include':
                        patch['excludedMovieIds'] = [entry for entry in SETTINGS.get('excludedMovieIds', [])
                                                     if entry != movie_id]
                    saveSettings(patch)
                return self.reply(200, publicSettings())
            if self.path == '/api/specials/exclude':
                movie_id = int(body.get('movieId', 0))
                delete_from_radarr = body.get('deleteFromRadarr', False)
                if movie_id <= 0 or not isinstance(delete_from_radarr, bool):
                    raise ValueError('Choose a valid special and deletion option')
                result = excludeSpecial(movie_id, delete_from_radarr)
                return self.reply(200, result)
            if self.path == '/api/refresh':
                return self.reply(200, refresh(sync=True))
            if self.path == '/api/sync':
                if not SNAPSHOT:
                    raise ValueError('Refresh the catalog first')
                return self.reply(200, syncRadarr())
            return self.reply(404, {'error': 'Not found'})
        except TimeoutError:
            self.close_connection = True
            self.connection.settimeout(self.timeout)
            return self.reply(408, {'error': 'Request timed out'})
        except (ValueError, KeyError, StopIteration) as error:
            if isinstance(error, TmdbAccessDenied):
                clearMetadata()
            return self.reply(400, {'error': str(error) if isinstance(error, ValueError) else 'Invalid request'})


def scheduledRefresh():
    while True:
        zone = ZoneInfo(os.environ.get('TZ', 'America/Detroit'))
        local = dt.datetime.now(zone)
        target = local.replace(hour=3, minute=0, second=0, microsecond=0)
        if target <= local:
            target += dt.timedelta(days=1)
        time.sleep(target.timestamp() - local.timestamp())
        try:
            refresh(sync=True)
        except ValueError:
            pass


def main():
    global SETTINGS, SNAPSHOT, SESSIONS
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    SETTINGS = loadSettings()
    if (STATE_DIR / 'snapshot.json').exists():
        SNAPSHOT = json.loads((STATE_DIR / 'snapshot.json').read_text())
    expireMetadata()
    if (STATE_DIR / 'sessions.json').exists():
        SESSIONS = json.loads((STATE_DIR / 'sessions.json').read_text())
    threading.Thread(target=scheduledRefresh, daemon=True).start()
    threading.Thread(target=maintainMetadata, daemon=True).start()
    threading.Thread(target=scheduledDownloadStatuses, daemon=True).start()
    def initialRefresh():
        try:
            refresh()
        except ValueError:
            pass
    threading.Thread(target=initialRefresh, daemon=True).start()
    LimitedThreadingHTTPServer(('0.0.0.0', 6162), Handler).serve_forever()


if __name__ == '__main__':
    main()
