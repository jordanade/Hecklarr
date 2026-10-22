"""Rank TMDB's person matches by name relevance, then popularity."""

import math
import unicodedata


def normalizeName(value):
    return ''.join(character for character in unicodedata.normalize('NFKD', value.casefold())
                   if character.isalnum())


def rankPeople(rows, term):
    query = normalizeName(term)

    def score(row):
        names = [normalizeName(name) for name in [row.get('name'), row.get('original_name')]
                 if isinstance(name, str) and name.strip()]
        # TMDB can rank reversed names above an unfinished first/last name, as
        # with "Tom Taylor" for "Taylor To". Keep popularity within name groups.
        relevance = min((0 if name == query else 1 if name.startswith(query)
                         else 2 if query in name else 3 for name in names), default=3)
        try:
            popularity = float(row.get('popularity') or 0)
        except (TypeError, ValueError):
            popularity = 0
        if not math.isfinite(popularity):
            popularity = 0
        return relevance, -max(0, popularity)

    return sorted(rows, key=score)
