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
# this shorter cache also prevents temporary provider outages from hiding a
# title for an excessive amount of time.
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


def _candidate_value(candidate: Any, name: str, default: Any = "") -> Any:
    if isinstance(candidate, dict):
        return candidate.get(name, default)
    return getattr(candidate, name, default)


def _tmdb_movie_aliases(movie: dict[str, Any]) -> set[str]:
    aliases: set[str] = set()
    for title in (movie.get("title"), movie.get("original_title")):
        if title:
            aliases.update(_movie_title_match_keys(str(title)))
    return aliases


def _candidate_matches_tmdb_movie(candidate: Any, movie: dict[str, Any]) -> bool:
    if _candidate_value(candidate, "is_movie", True) is False:
        return False
    aliases = _tmdb_movie_aliases(movie)
    if not aliases:
        return False
    return _movie_matches_tmdb_choice(
        str(_candidate_value(candidate, "title", "")),
        str(_candidate_value(candidate, "year", "")),
        aliases,
        str(movie.get("year") or ""),
    )


def _verify_tmdb_movie_source(
    index: int,
    movie: dict[str, Any],
) -> tuple[int, dict[str, Any] | None]:
    try:
        sources = resolve_tmdb_movie_sources(movie["tmdb_id"])
    except LookupError:
        return index, None
    except Exception as exc:
        log(
            f"Anbieterprüfung für «{movie.get('title') or movie['tmdb_id']}» "
            f"übersprungen: {exc}",
            "warn",
        )
        return index, None
    return index, movie if sources else None


def _tmdb_search_results(query: str) -> list[dict[str, Any]]:
    """Return only TMDB films confirmed by at least one active provider.

    The broad provider search is executed once for the submitted query and is
    used as a cheap pre-filter. Only plausible TMDB identities then enter the
    existing exact source resolver, which validates localized/original titles,
    release year, real hosters, provider priority, and fallback sources.
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

        try:
            provider_candidates = list(search_movie_candidates(query))
        except Exception as exc:
            # Individual provider failures are already isolated inside
            # ``search_movie_candidates``. This final guard keeps an unexpected
            # adapter failure from turning the complete search into HTTP 500.
            log(f"Film-Anbietersuche übersprungen: {exc}", "warn")
            provider_candidates = []

        plausible = [
            movie
            for movie in tmdb_results
            if any(
                _candidate_matches_tmdb_movie(candidate, movie)
                for candidate in provider_candidates
            )
        ]
        if not plausible:
            _MOVIE_SEARCH_AVAILABILITY_CACHE[cache_key] = ()
            return []

        verified_by_index: dict[int, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=min(4, len(plausible))) as pool:
            futures = [
                pool.submit(_verify_tmdb_movie_source, index, movie)
                for index, movie in enumerate(plausible)
            ]
            for future in as_completed(futures):
                index, movie = future.result()
                if movie is not None:
                    verified_by_index[index] = movie

        verified = [
            verified_by_index[index]
            for index in range(len(plausible))
            if index in verified_by_index
        ]
        _MOVIE_SEARCH_AVAILABILITY_CACHE[cache_key] = tuple(
            dict(movie) for movie in verified
        )
        return [dict(movie) for movie in verified]


_SERVICE_EXPORTS = ("_tmdb_search_results",)
publish_service(globals(), _SERVICE_EXPORTS)
