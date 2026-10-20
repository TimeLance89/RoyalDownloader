"""Resolve a filmography series by TMDB identity before exposing its episodes.

A TMDB-discovered show must reuse already resolved provider inventory before
trying potentially slow remote searches. Candidate identity is checked against
one authoritative TMDB response; external ID verification happens only for
the selected loaded provider, not for every search listing.
"""

import logging
import re
import time
import unicodedata

logger = logging.getLogger(__name__)


def _normalized_title(title):
    ascii_name = unicodedata.normalize("NFKD", str(title or "")).casefold()
    return re.sub(r"[^\w]+", " ", ascii_name).strip()


def resolve_person_series(client, tmdb_id, providers, search, load, *,
                          cached_series=(), budget_seconds=25, clock=time.monotonic):
    started = clock()
    lightweight_identity = getattr(client, "series_identity_by_id", client.series_by_id)
    metadata = lightweight_identity(tmdb_id)
    if not metadata:
        return None
    titles = list(dict.fromkeys(filter(None, [metadata.get("title"), metadata.get("original_title")])))
    normalized = {_normalized_title(title) for title in titles}
    wanted_year = str(metadata.get("year") or "")

    def plausible(value, loaded=False):
        year = str(getattr(value, "year", "") or "")
        if loaded and wanted_year and not year:
            return False
        if wanted_year and year and year != wanted_year:
            return False
        # Filter obvious mismatches without dozens of TMDB search requests.
        return _normalized_title(getattr(value, "title", "")) in normalized

    def confirmed(value):
        if not value or not getattr(value, "seasons", None) or not plausible(value, loaded=True):
            return False
        return client.series_matches_id(value.title, tmdb_id, str(getattr(value, "year", "") or ""))

    # Most previously opened series already have complete provider seasons;
    # reopening one should never trigger a full provider search.
    for series in tuple(cached_series):
        if clock() - started > budget_seconds:
            return None
        try:
            if confirmed(series):
                return series
        except Exception as error:
            logger.warning("Cached series validation failed: %s", error)

    for provider in providers:
        for title in titles:
            if clock() - started > budget_seconds:
                logger.warning("TMDB series source resolution reached the search budget for %s", tmdb_id)
                return None
            try:
                for candidate in search(provider, title):
                    if clock() - started > budget_seconds:
                        return None
                    if not plausible(candidate):
                        continue
                    series = load(provider, candidate.sample_slug)
                    if clock() - started > budget_seconds:
                        return None
                    if confirmed(series):
                        return series
            except Exception as error:
                # One provider failure must not lose every other series source.
                logger.warning("Person series source %s unavailable: %s", provider, error)
    return None
