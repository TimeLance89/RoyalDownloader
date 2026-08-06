"""Provider-verified TMDB movie search results."""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from application_services.runtime import import_backend_namespace, publish_service
from runtime_cache import BoundedTTLCache


globals().update(import_backend_namespace())

# Search results are intentionally cached only briefly. Positive provider
# sources keep their existing two-hour cache in ``state.movie_source_cache``;
# this shorter result cache also prevents temporary provider outages from
# hiding a title for an excessive amount of time.
_MOVIE_SEARCH_AVAILABILITY_CACHE = BoundedTTLCache[
    tuple[str, tuple[str, ...], str], tuple[dict[str, Any], ...]
](
    "movie_search_availability",
    max_entries=128,
    ttl_seconds=2 * 60,
)
_MOVIE_SEARCH_AVAILABILITY_LOCK = threading.Lock()


def _copy_cached_results(
    cached: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    return [dict(item) for item in cached]


def _movie_search_cache_key(query: str) -> tuple[str, tuple[str, ...], str]:
    client = get_tmdb_client()
    normalized_query = " ".join(str(query or "").split()).casefold()
    return (
        normalized_query,
        tuple(provider_priority("movies")),
        str(getattr(client, "language", "") or ""),
    )


def _format_tmdb_movie(movie: dict[str, Any]) -> dict[str, Any]:
    tmdb_id = int(movie["tmdb_id"])
    return {
        **movie,
        "slug": f"tmdb:{tmdb_id}",
        "url": f"https://www.themoviedb.org/movie/{tmdb_id}",
        "is_movie": True,
        "provider": "",
        "content_language": "",
    }


def _verify_tmdb_movie_source(
    index: int,
    movie: dict[str, Any],
) -> tuple[int, dict[str, Any] | None]:
    try:
        # The established resolver searches localized and original titles at
        # every active provider, validates the release year, loads candidate
        # details, requires real hosters, and stores ordered fallback sources.
        sources = resolve_tmdb_movie_sources(movie["tmdb_id"])
    except LookupError:
        return index, None
    except Exception as exc:
        # One broken provider or one malformed candidate must never abort the
        # remaining TMDB identities in this search.
        log(
            f"Anbieterprüfung für «{movie.get('title') or movie['tmdb_id']}» "
            f"übersprungen: {exc}",
            "warn",
        )
        return index, None
    return index, movie if sources else None


def _tmdb_search_results(query: str) -> list[dict[str, Any]]:
    """Return only TMDB films confirmed by at least one active provider.

    Every TMDB identity enters the existing exact source resolver. This avoids
    false negatives when a provider knows only the localized title or only the
    original title. Verification runs with bounded parallelism; provider-level
    searches inside the resolver remain parallel and failure-isolated.
    """
    query = " ".join(str(query or "").split()).strip()
    if not query:
        return []

    client = get_tmdb_client()
    if not client.configured:
        return []

    cache_key = _movie_search_cache_key(query)
    try:
        return _copy_cached_results(_MOVIE_SEARCH_AVAILABILITY_CACHE[cache_key])
    except KeyError:
        pass

    # A single-user installation can still submit the same search from several
    # browser tabs. Re-checking inside the lock avoids duplicate provider waves.
    with _MOVIE_SEARCH_AVAILABILITY_LOCK:
        try:
            return _copy_cached_results(_MOVIE_SEARCH_AVAILABILITY_CACHE[cache_key])
        except KeyError:
            pass

        movies = client.search_movies(
            query,
            max_results=TMDB_MOVIE_SEARCH_MAX_RESULTS,
        )
        tmdb_results = [_format_tmdb_movie(movie) for movie in movies]
        if not tmdb_results:
            _MOVIE_SEARCH_AVAILABILITY_CACHE[cache_key] = ()
            return []

        verified_by_index: dict[int, dict[str, Any]] = {}
        # Each resolver already fans out across the active providers. Limiting
        # the outer pool prevents a 40-result TMDB search from creating an
        # unbounded number of simultaneous network and detail requests.
        with ThreadPoolExecutor(max_workers=min(3, len(tmdb_results))) as pool:
            futures = [
                pool.submit(_verify_tmdb_movie_source, index, movie)
                for index, movie in enumerate(tmdb_results)
            ]
            for future in as_completed(futures):
                index, movie = future.result()
                if movie is not None:
                    verified_by_index[index] = movie

        # Preserve TMDB relevance order even though provider checks finish in a
        # different order.
        verified = [
            verified_by_index[index]
            for index in range(len(tmdb_results))
            if index in verified_by_index
        ]
        _MOVIE_SEARCH_AVAILABILITY_CACHE[cache_key] = tuple(
            dict(movie) for movie in verified
        )
        return [dict(movie) for movie in verified]


_SERVICE_EXPORTS = ("_tmdb_search_results",)
publish_service(globals(), _SERVICE_EXPORTS)
