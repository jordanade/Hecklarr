"""Prefer likely comedians among matching TMDB names, then popularity."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, wait
import hashlib
import math
import re
import threading
import time
import unicodedata


def normalizeName(value):
    return ''.join(character for character in unicodedata.normalize('NFKD', value.casefold())
                   if character.isalnum())


def isComedian(profile):
    """Look for a comedian occupation in the person's own introduction.

    Comedy genres also describe actors, and later biography paragraphs often
    mention comedian relatives or collaborators. Neither identifies this person.
    Missing or ambiguous biographies simply receive no ranking boost.
    """
    biography = profile.get('biography') or ''
    introduction = re.sub(r'^From Wikipedia[^\n]*\n*', '', biography, flags=re.IGNORECASE)
    introduction = introduction.split('\n\n', 1)[0][:600]
    occupation = r'\b(?:comedian|comedienne|stand[\s‐‑–-]*up comic)\b'
    if re.match(occupation, introduction, re.IGNORECASE):
        return True
    for description in re.finditer(r'\b(?:is|was)\s+(?:an?|the)\s+[^.!?\n]{0,180}?' + occupation,
                                   introduction, re.IGNORECASE):
        if not re.search(r'\b(?:of|with|portraying|playing|portrayed|played)\b', description[0], re.IGNORECASE):
            return True
    return False


class ComedianSearchCache:
    """Bound optional biography work across all browser sessions.

    Search must still work when individual profiles are missing or slow. Late
    successes warm the cache for later searches; failures never become durable
    negative classifications. Credential-scoped keys prevent cross-source reuse.
    """

    def __init__(self, max_age=86400, capacity=512, max_pending=32, wait_seconds=1.5, clock=time.monotonic):
        self.max_age, self.capacity = max_age, capacity
        self.max_pending, self.wait_seconds = max_pending, wait_seconds
        self.clock = clock
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix='comedian-search')
        self.cache = OrderedDict()
        self.pending = {}

    def loadSignal(self, key, settings, fetch):
        try:
            signal = isComedian(fetch(f'person/{key[1]}', settings))
        except Exception:
            signal = None
        with self.lock:
            self.pending.pop(key, None)
            if signal is not None:
                self.cache[key] = (self.clock(), signal)
                self.cache.move_to_end(key)
                while len(self.cache) > self.capacity:
                    self.cache.popitem(last=False)
        return signal

    def comedianIds(self, rows, settings, fetch):
        source = hashlib.sha256(settings.get('tmdbApiKey', '').encode()).digest()
        keys = list(dict.fromkeys((source, row['id']) for row in rows))
        futures = {}
        with self.lock:
            for key in keys:
                cached = self.cache.get(key)
                if cached is not None and self.clock() - cached[0] < self.max_age:
                    self.cache.move_to_end(key)
                    continue
                future = self.pending.get(key)
                if future is None and len(self.pending) < self.max_pending:
                    future = self.executor.submit(self.loadSignal, key, settings, fetch)
                    self.pending[key] = future
                if future is not None:
                    futures[future] = key
        confirmed = set()
        if futures:
            completed, _ = wait(futures, timeout=self.wait_seconds)
            confirmed = {futures[future][1] for future in completed if future.result()}
        with self.lock:
            return confirmed | {key[1] for key in keys if (cached := self.cache.get(key)) is not None
                                and self.clock() - cached[0] < self.max_age and cached[1]}


def rankPeople(rows, term, comedian_ids=()):
    query = normalizeName(term)

    def score(row):
        names = [normalizeName(name) for name in [row.get('name'), row.get('original_name')]
                 if isinstance(name, str) and name.strip()]
        # Treat exact, prefix, and later name matches equally: "Chris Rock"
        # should outrank obscure people named "Rock". Keep reversed-name or
        # alias-only TMDB matches available after literal name matches.
        relevance = 0 if any(query in name for name in names) else 1
        try:
            popularity = float(row.get('popularity') or 0)
        except (TypeError, ValueError):
            popularity = 0
        if not math.isfinite(popularity):
            popularity = 0
        return relevance, row.get('id') not in comedian_ids, -max(0, popularity)

    return sorted(rows, key=score)
