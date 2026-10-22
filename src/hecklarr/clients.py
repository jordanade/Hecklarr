"""HTTP transport shared by the TMDB and Radarr clients."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request


class TmdbNotFound(ValueError):
    """TMDB no longer has the requested resource."""


class TmdbAccessDenied(ValueError):
    """TMDB rejected the installation's credential."""


class RadarrValidationError(ValueError):
    """Keep validation failures available for narrowly acknowledging empty lists."""

    def __init__(self, failures):
        super().__init__('Radarr returned HTTP 400')
        self.failures = failures


class SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Allow redirects without forwarding credentials to another origin."""

    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        def origin(url):
            parsed = urllib.parse.urlsplit(url)
            port = parsed.port
            if port is None:
                port = 443 if parsed.scheme == 'https' else 80
            return parsed.scheme.lower(), parsed.hostname, port

        target = urllib.parse.urlsplit(new_url)
        # urllib forwards custom headers on redirects, so the destination must
        # remain exactly the same origin before TMDB or Radarr keys are reused.
        if (target.username is not None or target.password is not None
                or origin(request.full_url) != origin(new_url)):
            raise ValueError('Redirect to a different origin was blocked. Use the final service address.')
        return super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )


HTTP_OPENER = urllib.request.build_opener(SameOriginRedirectHandler())
IDEMPOTENT_METHODS = {'GET', 'HEAD', 'PUT', 'DELETE'}


def retryDelay(value, default=2, limit=10):
    """Read a Retry-After header in seconds; HTTP dates and bad values use the default."""
    try:
        delay = int(value)
    except (TypeError, ValueError):
        delay = default
    return max(0, min(delay, limit))


def requestJson(url, key, body=None, method=None, tmdb=False, opener=HTTP_OPENER):
    """Send one authenticated JSON request with bounded transient retries."""
    headers = {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
        'User-Agent': 'Hecklarr/0.1',
    }
    if tmdb:
        if '.' in key:
            headers['Authorization'] = 'Bearer ' + key
        else:
            url += ('&' if '?' in url else '?') + urllib.parse.urlencode({'api_key': key})
    else:
        headers['X-Api-Key'] = key
    payload = json.dumps(body).encode() if body is not None else None
    service = 'TMDB' if tmdb else 'Radarr'
    # A timed-out POST may already have created a Radarr list or root folder, so only
    # requests that are safe to repeat are retried.
    attempts = 3 if (method or ('POST' if payload is not None else 'GET')).upper() in IDEMPOTENT_METHODS else 1
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, data=payload, headers=headers, method=method)
            with opener.open(request, timeout=30) as response:
                response_body = response.read()
                return json.loads(response_body) if response_body else None
        except urllib.error.HTTPError as error:
            if tmdb and error.code == 404:
                raise TmdbNotFound('TMDB entry no longer available') from None
            if tmdb and error.code in [401, 403]:
                raise TmdbAccessDenied('TMDB access denied; cached metadata cleared') from None
            if (error.code == 429 or error.code >= 500) and attempt < attempts - 1:
                # Retry-After is advisory but capped so one request cannot stall a worker indefinitely.
                time.sleep(retryDelay(error.headers.get('Retry-After') if error.headers else None))
                continue
            if not tmdb and error.code == 400:
                try:
                    failures = json.loads(error.read(65536))
                except (ValueError, TypeError):
                    failures = None
                raise RadarrValidationError(failures) from None
            raise ValueError(f'{service} returned HTTP {error.code}') from None
        except (urllib.error.URLError, TimeoutError):
            if attempt < attempts - 1:
                time.sleep(1)
                continue
            raise ValueError(f'{service} connection failed') from None
