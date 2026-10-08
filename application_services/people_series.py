"""Resolve a filmography series by TMDB identity before exposing its episodes."""

import logging

logger = logging.getLogger(__name__)


def resolve_person_series(client, tmdb_id, providers, search, load):
    metadata = client.series_by_id(tmdb_id)
    if not metadata:
        return None
    titles = list(dict.fromkeys(filter(None, [metadata.get("title"), metadata.get("original_title")])))
    wanted_year = str(metadata.get("year") or "")

    def matches(value, loaded=False):
        year = str(getattr(value, "year", "") or "")
        if loaded and wanted_year and not year:
            return False
        if wanted_year and year and year != wanted_year:
            return False
        # Sparse search listings can be inspected; loaded sources must confirm the year.
        return client.series_matches_id(value.title, tmdb_id, year)

    for provider in providers:
        for title in titles:
            try:
                candidates = search(provider, title)
                for candidate in candidates:
                    if not matches(candidate):
                        continue
                    series = load(provider, candidate.sample_slug)
                    if series and series.seasons and matches(series, loaded=True):
                        return series
            except Exception as error:  # One provider failure must not lose other sources.
                logger.warning("Person series source %s unavailable: %s", provider, error)
    return None
