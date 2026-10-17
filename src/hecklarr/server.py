"""Small, dependency-free TMDB performer watchlist and Radarr Custom List service."""
import base64
import datetime as dt
import hashlib
import hmac
import http.cookies
import io
import ipaddress
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

from .clients import HTTP_OPENER
from .clients import SameOriginRedirectHandler  # noqa: F401 - re-exported for tests
from .clients import TmdbAccessDenied, TmdbNotFound
from .clients import requestJson as performJsonRequest
from .discovery import buildSnapshot as buildDiscoverySnapshot
from .discovery import classify  # noqa: F401 - re-exported for tests
from .discovery import itemOwners, migrateSnapshot
from .downloads import MovieListCache
from .downloads import fetchDownloadStatuses as fetchRadarrDownloadStatuses
from .downloads import movieDownloadState  # noqa: F401 - re-exported for tests

STATE_DIR = Path(os.environ.get('CONFIG_DIR', '/config'))
# Python uses a src layout, while the browser assets remain at the repository
# and container root so the README and image build share the same files.
ASSET_DIR = Path(__file__).resolve().parents[2]
# LOCK protects in-memory state and its persisted JSON mirrors. REFRESH_LOCK
# serializes catalog-changing workflows that may release LOCK during network I/O.
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
DOWNLOAD_MOVIES = MovieListCache()
DOWNLOAD_POLL_SECONDS = 60
# Radarr's movie list can be large, so download status is polled only while a
# browser has asked for it recently.
DOWNLOAD_ACTIVE_SECONDS = 300
LAST_STATUS_REQUEST = 0.0
# Printed to the log at startup and required to create the first account.
SETUP_CODE = None
MAX_TRACKED_ADDRESSES = 1024


def parseNetworks(value):
    """Parse a comma-separated list of proxy addresses or CIDR ranges."""
    networks = []
    for entry in value.split(','):
        entry = entry.strip()
        if entry:
            try:
                networks.append(ipaddress.ip_network(entry, strict=False))
            except ValueError:
                raise ValueError(f'TRUSTED_PROXIES contains an invalid address: {entry}') from None
    return networks


TRUSTED_PROXIES = parseNetworks(os.environ.get('TRUSTED_PROXIES', ''))


def addressTrusted(address):
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in TRUSTED_PROXIES)


class RequestReader(io.RawIOBase):
    """Enforce one total deadline across all header and body reads."""

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
    """Bound concurrent request workers so slow clients cannot exhaust threads."""

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


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def saveJson(path, data):
    """Atomically replace a private JSON state file without a shared temp path."""
    fd, filename = tempfile.mkstemp(prefix=path.stem + '.', suffix='.tmp', dir=path.parent)
    temporary = Path(filename)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(json.dumps(data, indent=2) + '\n')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def saveSettings(patch):
    global DOWNLOAD_STATUSES, SETTINGS
    with LOCK:
        previous_radarr = (SETTINGS.get('radarrUrl'), SETTINGS.get('radarrApiKey'))
        # Build and persist a new dict, then swap it in, so threads reading SETTINGS
        # without the lock never see a URL from one save paired with a key from another.
        updated = {**SETTINGS, **patch}
        # Keep selection/exception IDs as preferences, not cached TMDB names.
        updated['comedians'] = [{key: value for key, value in person.items() if key != 'name'}
                                for person in updated.get('comedians', [])]
        saveJson(STATE_DIR / 'settings.json', updated)
        SETTINGS = updated
        if previous_radarr != (SETTINGS.get('radarrUrl'), SETTINGS.get('radarrApiKey')):
            DOWNLOAD_STATUSES = {'items': {}, 'updatedAt': None, 'lastError': None}
            invalidateDownloadCache()


def invalidateDownloadCache():
    """Re-read Radarr's movie list on the next poll, after Hecklarr changed Radarr or the catalog."""
    DOWNLOAD_MOVIES.invalidate()
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
    return performJsonRequest(url, key, body, method, tmdb, HTTP_OPENER)


def tmdb(path, settings):
    if not settings.get('tmdbApiKey'):
        raise ValueError('Add a TMDB API key in Settings')
    return requestJson('https://api.themoviedb.org/3/' + path, settings['tmdbApiKey'], tmdb=True)


def radarr(path, settings, body=None, method=None):
    if not settings.get('radarrUrl') or not settings.get('radarrApiKey'):
        raise ValueError('Add the Radarr URL and API key in Settings')
    return requestJson(settings['radarrUrl'].rstrip('/') + '/api/v3/' + path,
                       settings['radarrApiKey'], body, method)


def fetchDownloadStatuses(settings, movie_ids, fetch=None, cache=None):
    # The live Radarr path shares one movie-list cache; injected fetchers get none.
    if fetch is None:
        fetch, cache = radarr, DOWNLOAD_MOVIES
    return fetchRadarrDownloadStatuses(settings, movie_ids, fetch, cache)


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
            # The poll may have cached the previous Radarr's movies.
            DOWNLOAD_MOVIES.invalidate()
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


def noteStatusRequest():
    """Record browser interest in download status, waking an idle poller at once."""
    global LAST_STATUS_REQUEST
    with LOCK:
        idle = time.time() - LAST_STATUS_REQUEST >= DOWNLOAD_ACTIVE_SECONDS
        LAST_STATUS_REQUEST = time.time()
    if idle:
        DOWNLOAD_REFRESH.set()


def logUnexpected(context, error):
    """Log an unexpected failure by type and location without its message, which may hold URLs."""
    frames = traceback.extract_tb(error.__traceback__)
    where = f' at {Path(frames[-1].filename).name}:{frames[-1].lineno}' if frames else ''
    print(f'{now()} {context} failed: {type(error).__name__}{where}', flush=True)


def downloadStatusTick():
    """Poll Radarr once if a browser is watching; never let a failure end the poller."""
    if time.time() - LAST_STATUS_REQUEST >= DOWNLOAD_ACTIVE_SECONDS:
        return False
    try:
        updateDownloadStatuses()
    except Exception as error:
        logUnexpected('Download status update', error)
    return True


def scheduledDownloadStatuses():
    while True:
        DOWNLOAD_REFRESH.clear()
        downloadStatusTick()
        DOWNLOAD_REFRESH.wait(DOWNLOAD_POLL_SECONDS)


def buildSnapshot(settings, previous, fetch=tmdb):
    return buildDiscoverySnapshot(settings, previous, fetch, now, TmdbNotFound)


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
        try:
            expireMetadata()
        except Exception as error:
            logUnexpected('Metadata expiry', error)
        time.sleep(3600)


def refresh(sync=False):
    """Replace the catalog only after a complete snapshot builds successfully."""
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
            invalidateDownloadCache()
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
        existing = next((entry for entry in lists if entry['name'] == 'Hecklarr - Comedy'), None)
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
    invalidateDownloadCache()
    return {'id': saved['id'], 'rootFolderPath': root, 'name': saved['name']}


def excludeSpecial(movie_id, delete_from_radarr):
    """Persist an exclusion before optionally deleting its Radarr movie."""
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
            # Review rows belong to one comedian each, matching what a refresh produces.
            names = movie.get('comedians') or []
            for index, owner in enumerate(itemOwners(movie)):
                snapshot.setdefault('reviewed', []).append({
                    'tmdbId': movie['tmdbId'], 'title': movie['title'], 'year': movie.get('year', ''),
                    'releaseDate': movie.get('releaseDate', ''), 'personId': owner,
                    'comedian': names[index] if index < len(names) else '',
                    'included': False, 'reason': 'Explicitly excluded from Hecklarr'})
        with LOCK:
            saveJson(STATE_DIR / 'snapshot.json', snapshot)
            SNAPSHOT = snapshot

        if delete_from_radarr:
            try:
                for row in matches:
                    radarr(f"movie/{row['id']}?deleteFiles=true", settings, method='DELETE')
            except ValueError as error:
                raise ValueError('The special was excluded from the feed, but Radarr deletion did not finish: ' + str(error)) from None
            finally:
                invalidateDownloadCache()
            if settings.get('radarrListId'):
                try:
                    radarr('command', settings, {'name': 'ImportListSync',
                                                 'definitionId': settings['radarrListId']})
                except ValueError as error:
                    raise ValueError('The special was excluded and removed from Radarr, but the list sync failed: ' + str(error)) from None
        return {'removedFromRadarr': len(matches),
                'hadFiles': sum(bool(row.get('hasFile')) for row in matches)}


def withoutOwner(row, person_id):
    """Return a catalog item with one comedian removed from its owners."""
    owners = itemOwners(row)
    names = row.get('comedians') or []
    keep = [index for index, owner in enumerate(owners) if owner != person_id]
    return {**row, 'personIds': [owners[index] for index in keep],
            'comedians': [names[index] for index in keep if index < len(names)]}


def removeComedian(person_id, delete_from_radarr):
    """Remove one comedian, deleting Radarr movies first when requested.

    A special that another tracked comedian also qualifies for stays in the feed
    and in Radarr; only specials this comedian alone owns are removed.
    """
    global SNAPSHOT
    with REFRESH_LOCK:
        with LOCK:
            settings = json.loads(json.dumps(SETTINGS))
            snapshot = json.loads(json.dumps(SNAPSHOT))
        person = next((row for row in settings.get('comedians', []) if row['id'] == person_id), None)
        if person is None:
            raise ValueError('That comedian is no longer in Hecklarr. Refresh and try again.')
        owned = [row for row in snapshot.get('items', []) if person_id in itemOwners(row)]
        movie_ids = {row['tmdbId'] for row in owned if set(itemOwners(row)) == {person_id}}
        shared_count = len(owned) - len(movie_ids)
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
            finally:
                invalidateDownloadCache()

        with LOCK:
            saveSettings({'comedians': [row for row in SETTINGS['comedians'] if row['id'] != person_id]})
        snapshot['items'] = [withoutOwner(row, person_id) if person_id in itemOwners(row) else row
                             for row in snapshot.get('items', [])
                             if row['tmdbId'] not in movie_ids]
        snapshot['reviewed'] = [row for row in snapshot.get('reviewed', [])
                                if row.get('personId') != person_id]
        snapshot['people'] = [row for row in snapshot.get('people', []) if row.get('id') != person_id]
        with LOCK:
            saveJson(STATE_DIR / 'snapshot.json', snapshot)
            SNAPSHOT = snapshot
        return {'removedFromRadarr': len(matches),
                'hadFiles': sum(bool(row.get('hasFile')) for row in matches),
                'trackedCount': len(movie_ids),
                'sharedCount': shared_count}


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
        names = {}
        for row in SNAPSHOT.get('items', []):
            names.update(zip(itemOwners(row), row.get('comedians') or [], strict=False))
        names.update({row['id']: row['name'] for row in SNAPSHOT.get('people', [])})
        allowed = ['radarrUrl', 'rootFolderPath', 'qualityProfileId', 'feedBaseUrl', 'radarrListId']
        return {**{key: SETTINGS.get(key) for key in allowed},
                'comedians': [{**person, 'name': names.get(person['id'], f'TMDB person {person["id"]}')}
                              for person in SETTINGS.get('comedians', [])],
                'hasTmdbKey': bool(SETTINGS.get('tmdbApiKey')),
                'hasRadarrKey': bool(SETTINGS.get('radarrApiKey')),
                'timeZone': os.environ.get('TZ', 'America/Detroit')}


STATIC_FILES = {
    '/': ('index.html', 'text/html'),
    '/app.js': ('app.js', 'text/javascript'),
    '/style.css': ('style.css', 'text/css'),
    '/icon.png': ('icon.png', 'image/png'),
    '/tmdb-logo.svg': ('tmdb-logo.svg', 'image/svg+xml'),
}


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
        token = cookies.get('hecklarr_session')
        with LOCK:
            return bool(token and SESSIONS.get(hashlib.sha256(token.value.encode()).hexdigest(), 0) > time.time())

    def staticFile(self, path):
        filename, content_type = STATIC_FILES[path]
        asset = ASSET_DIR / filename
        body = asset.read_bytes() if content_type.startswith('image/') else asset.read_text()
        return self.reply(200, body, content_type)

    def health(self):
        # Liveness only: a fresh install or a TMDB outage is not an unhealthy process.
        result = {
            'ready': bool(SNAPSHOT),
            'count': len(SNAPSHOT.get('items', [])),
            'updatedAt': SNAPSHOT.get('updatedAt'),
        }
        if self.authenticated():
            result['lastError'] = LAST_ERROR
        return self.reply(200, result)

    def authStatus(self):
        authenticated = self.authenticated()
        result = {'authenticated': authenticated, 'setupRequired': not bool(SETTINGS.get('authHash'))}
        if authenticated:
            result['username'] = SETTINGS['authUser']
        return self.reply(200, result)

    def movieFeed(self, query):
        if not hmac.compare_digest(query.get('key', [''])[0].encode(), SETTINGS['feedKey'].encode()):
            return self.reply(401, {'error': 'Invalid feed key'})
        if not SNAPSHOT:
            return self.reply(503, {'error': 'No successful refresh yet'})
        # Radarr Custom Lists parse MovieResultResource.Id, not a tmdbId field.
        return self.reply(200, [{'id': row['tmdbId'], 'title': row['title']}
                                for row in SNAPSHOT['items']])

    def searchPeople(self, query, settings):
        term = query.get('q', [''])[0].strip()
        if len(term) < 2:
            raise ValueError('Enter at least two characters')
        data = tmdb('search/person?' + urllib.parse.urlencode({'query': term}), settings)
        return self.reply(200, [{
            'id': row['id'],
            'name': row['name'],
            'knownFor': ', '.join(movie.get('title', movie.get('name', ''))
                                  for movie in row.get('known_for', [])[:3]),
        } for row in data['results']])

    def radarrOptions(self, settings):
        return self.reply(200, {
            'roots': radarr('rootfolder', settings),
            'profiles': [{'id': row['id'], 'name': row['name']}
                         for row in radarr('qualityprofile', settings)],
        })

    def clientAddress(self):
        """Return the visitor's address, reading X-Forwarded-For only from trusted proxies."""
        peer = self.client_address[0]
        if not addressTrusted(peer):
            return peer
        forwarded = [part.strip() for part in self.headers.get('X-Forwarded-For', '').split(',') if part.strip()]
        # Proxies append, so the rightmost untrusted entry is the one a trusted proxy observed.
        for address in reversed(forwarded):
            if not addressTrusted(address):
                return address
        return forwarded[0] if forwarded else peer

    def unexpectedError(self, error):
        logUnexpected(f'{self.command} {urllib.parse.urlsplit(self.path).path}', error)
        try:
            self.close_connection = True
            self.reply(500, {'error': 'Something went wrong. Check the Hecklarr log for details.'})
        except OSError:
            pass

    def do_GET(self):
        try:
            self.routeGet()
        except Exception as error:
            self.unexpectedError(error)

    def routeGet(self):
        self.connection.settimeout(self.timeout)
        expireMetadata()
        url = urllib.parse.urlsplit(self.path)
        path = url.path
        query = urllib.parse.parse_qs(url.query)
        if path in STATIC_FILES:
            return self.staticFile(path)
        if path == '/api/health':
            return self.health()
        if path == '/api/auth':
            return self.authStatus()
        if path == '/feed/movies.json':
            return self.movieFeed(query)
        if not self.authenticated():
            return self.reply(401, {'error': 'Log in to continue'})
        try:
            with LOCK:
                settings = dict(SETTINGS)
            if path == '/api/settings':
                return self.reply(200, publicSettings())
            if path == '/api/status':
                noteStatusRequest()
                return self.reply(200, {**SNAPSHOT, 'lastError': LAST_ERROR,
                                        'downloadStatuses': cachedDownloadStatuses()})
            if path == '/api/download-status':
                noteStatusRequest()
                return self.reply(200, cachedDownloadStatuses())
            if path == '/api/search':
                return self.searchPeople(query, settings)
            if path == '/api/radarr/options':
                return self.radarrOptions(settings)
            return self.reply(404, {'error': 'Not found'})
        except ValueError as error:
            if isinstance(error, TmdbAccessDenied):
                clearMetadata()
            return self.reply(400, {'error': str(error)})

    def readJsonBody(self):
        length = int(self.headers.get('Content-Length', '0'))
        if length < 0 or length > 65536:
            raise ValueError('Invalid request size')
        payload = self.rfile.read(length)
        self.connection.settimeout(self.timeout)
        body = json.loads(payload or b'{}')
        if not isinstance(body, dict):
            raise ValueError('Expected an object')
        return body

    def setupAccount(self, body):
        global SETUP_CODE
        with LOCK:
            if SETTINGS.get('authHash'):
                return self.reply(409, {'error': 'An account already exists. Log in to continue.'})
            ip = self.clientAddress()
            if not self.reserveLoginAttempt(ip):
                return self.reply(429, {'error': 'Too many attempts. Try again in ten minutes.'})
            code = str(body.get('setupCode', '')).strip()
            if not SETUP_CODE or not hmac.compare_digest(code.encode(), SETUP_CODE.encode()):
                return self.reply(401, {'error': 'Enter the setup code shown in the Hecklarr log'})
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
            encoded = ('scrypt$16384$8$1$' + base64.b64encode(salt).decode() + '$'
                       + base64.b64encode(hashed).decode())
            saveSettings({'authUser': username, 'authHash': encoded})
            FAILURES.pop(ip, None)
            SETUP_CODE = None
        return self.reply(201, {'ok': True})

    def reserveLoginAttempt(self, ip):
        with LOCK:
            cutoff = time.time() - 600
            for address in list(FAILURES):
                recent = [stamp for stamp in FAILURES[address] if stamp > cutoff]
                if recent:
                    FAILURES[address] = recent
                else:
                    FAILURES.pop(address)
            recent = FAILURES.get(ip, [])
            if len(recent) >= 8:
                return False
            if ip not in FAILURES and len(FAILURES) >= MAX_TRACKED_ADDRESSES:
                # Evict the quietest address instead of refusing everyone new, which would
                # let an attacker with many addresses lock out the owner.
                FAILURES.pop(min(FAILURES, key=lambda address: FAILURES[address][-1]))
            # Reserve before hashing so concurrent attempts cannot share the same budget.
            FAILURES[ip] = recent + [time.time()]
            return True

    def login(self, body):
        if not SETTINGS.get('authHash'):
            return self.reply(409, {'error': 'Create your account first'})
        ip = self.clientAddress()
        if not self.reserveLoginAttempt(ip):
            return self.reply(429, {'error': 'Too many attempts. Try again in ten minutes.'})
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
        cookie = f'hecklarr_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=43200{secure}'
        return self.reply(200, {'ok': True}, cookie=cookie)

    def logout(self):
        cookies = http.cookies.SimpleCookie(self.headers.get('Cookie', ''))
        with LOCK:
            token = cookies.get('hecklarr_session')
            if token:
                SESSIONS.pop(hashlib.sha256(token.value.encode()).hexdigest(), None)
            saveJson(STATE_DIR / 'sessions.json', SESSIONS)
        return self.reply(200, {'ok': True}, cookie='hecklarr_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0')

    def updateSettings(self, body):
        patch = {key: str(body[key]).strip()
                 for key in ['radarrUrl', 'feedBaseUrl', 'rootFolderPath'] if key in body}
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

    def addComedian(self, body):
        person_id = int(body['id'])
        person = tmdb(f'person/{person_id}', SETTINGS)
        # Settings-only changes take LOCK, not REFRESH_LOCK, so they do not wait for a
        # running refresh; the browser starts a fresh refresh afterwards.
        with LOCK:
            people = SETTINGS['comedians'][:]
            if not any(row['id'] == person_id for row in people):
                people.append({'id': person_id, 'includeIds': [], 'excludeIds': []})
            saveSettings({'comedians': people})
        result = publicSettings()
        for row in result['comedians']:
            if row['id'] == person_id:
                row['name'] = person['name']
        return self.reply(200, result)

    def removeComedianRequest(self, body):
        person_id = int(body.get('id', 0))
        delete_from_radarr = body.get('deleteFromRadarr', False)
        if person_id <= 0 or not isinstance(delete_from_radarr, bool):
            raise ValueError('Choose a comedian and deletion option')
        result = removeComedian(person_id, delete_from_radarr)
        return self.reply(200, {'settings': publicSettings(), **result})

    def updateOverride(self, body):
        with LOCK:
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

    def excludeSpecialRequest(self, body):
        movie_id = int(body.get('movieId', 0))
        delete_from_radarr = body.get('deleteFromRadarr', False)
        if movie_id <= 0 or not isinstance(delete_from_radarr, bool):
            raise ValueError('Choose a valid special and deletion option')
        return self.reply(200, excludeSpecial(movie_id, delete_from_radarr))

    def authenticatedPost(self, path, body):
        routes = {
            '/api/logout': lambda: self.logout(),
            '/api/settings': lambda: self.updateSettings(body),
            '/api/comedians': lambda: self.addComedian(body),
            '/api/comedians/remove': lambda: self.removeComedianRequest(body),
            '/api/overrides': lambda: self.updateOverride(body),
            '/api/specials/exclude': lambda: self.excludeSpecialRequest(body),
            '/api/refresh': lambda: self.reply(200, refresh(sync=True)),
            '/api/sync': lambda: self.reply(200, syncRadarr()),
        }
        if path == '/api/sync' and not SNAPSHOT:
            raise ValueError('Refresh the catalog first')
        handler = routes.get(path)
        return handler() if handler else self.reply(404, {'error': 'Not found'})

    def do_POST(self):
        try:
            self.routePost()
        except Exception as error:
            self.unexpectedError(error)

    def routePost(self):
        expireMetadata()
        if self.headers.get('X-Hecklarr') != '1':
            return self.reply(403, {'error': 'Missing request header'})
        try:
            body = self.readJsonBody()
            if self.path == '/api/setup':
                return self.setupAccount(body)
            if self.path == '/api/login':
                return self.login(body)
            if not self.authenticated():
                return self.reply(401, {'error': 'Log in to continue'})
            return self.authenticatedPost(self.path, body)
        except TimeoutError:
            self.close_connection = True
            self.connection.settimeout(self.timeout)
            return self.reply(408, {'error': 'Request timed out'})
        except (ValueError, KeyError, TypeError, StopIteration) as error:
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
            pass  # refresh() already logged the failure.
        except Exception as error:
            logUnexpected('Scheduled refresh', error)


def ensureSetupCode():
    """Create and log a one-time code while no account exists."""
    global SETUP_CODE
    with LOCK:
        if SETTINGS.get('authHash'):
            SETUP_CODE = None
        elif not SETUP_CODE:
            SETUP_CODE = secrets.token_hex(6)
            print(f'{now()} No account yet. Setup code for the first account: {SETUP_CODE}', flush=True)
        return SETUP_CODE


def main():
    global SETTINGS, SNAPSHOT, SESSIONS
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    SETTINGS = loadSettings()
    ensureSetupCode()
    if (STATE_DIR / 'snapshot.json').exists():
        SNAPSHOT = migrateSnapshot(json.loads((STATE_DIR / 'snapshot.json').read_text()))
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
