"""Fast provider-verified TMDB movie search results."""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from __future__ import annotations

import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from application_services.runtime import import_backend_namespace, publish_service
from runtime_cache import BoundedTTLCache


globals().update(import_backend_namespace())

# Search results are intentionally cached only briefly. Provider detail pages
# and positive source resolutions keep using their existing longer-lived caches.
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


def _normalize_search_term(value: str) -> str:
    return " ".join(str(value or "").split()).strip().casefold()


def _movie_search_cache_key(query: str) -> tuple[str, tuple[str, ...], str]:
    client = get_tmdb_client()
    return (
        _normalize_search_term(query),
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


def _tmdb_movie_aliases(movie: dict[str, Any]) -> set[str]:
    return {
        key
        for title in (movie.get("title"), movie.get("original_title"))
        if title
        for key in _movie_title_match_keys(str(title))
    }


def _top_result_fallback_term(
    query: str,
    tmdb_results: list[dict[str, Any]],
) -> str:
    """Return at most one alternate title for the user's most relevant result."""
    if not tmdb_results:
        return ""
    normalized_query = _normalize_search_term(query)
    first = tmdb_results[0]
    # Prefer the original title: localized searches are the common case where
    # an English-language provider indexes a different title than the UI query.
    for value in (first.get("original_title"), first.get("title")):
        term = " ".join(str(value or "").split()).strip()
        if term and _normalize_search_term(term) != normalized_query:
            return term
    return ""


def _candidate_provider(candidate: Any) -> str:
    return str(
        getattr(candidate, "provider", "")
        or provider_for_value(str(getattr(candidate, "slug", "") or ""))
    ).strip().casefold()


def _match_provider_candidates(
    tmdb_results: list[dict[str, Any]],
    candidates: list[Any],
) -> dict[int, list[Any]]:
    """Assign provider search hits to exactly one TMDB identity.

    Provider hits are intersected with TMDB by localized title, original title
    and release year. Ambiguous provider hits without a usable year are ignored
    rather than risking a false-positive movie card.
    """
    identities = [
        (_tmdb_movie_aliases(movie), str(movie.get("year") or "").strip())
        for movie in tmdb_results
    ]
    matched: dict[int, list[Any]] = defaultdict(list)
    seen_slugs: dict[int, set[str]] = defaultdict(set)

    for candidate in candidates:
        if not getattr(candidate, "is_movie", False):
            continue
        title = str(getattr(candidate, "title", "") or "")
        year = str(getattr(candidate, "year", "") or "")
        matching_indexes = [
            index
            for index, (aliases, wanted_year) in enumerate(identities)
            if aliases
            and _movie_matches_tmdb_choice(title, year, aliases, wanted_year)
        ]
        if len(matching_indexes) != 1:
            continue
        index = matching_indexes[0]
        slug = str(getattr(candidate, "slug", "") or "")
        if not slug or slug in seen_slugs[index]:
            continue
        seen_slugs[index].add(slug)
        matched[index].append(candidate)

    positions = {
        provider: index
        for index, provider in enumerate(provider_priority("movies"))
    }
    for items in matched.values():
        items.sort(
            key=lambda candidate: positions.get(
                _candidate_provider(candidate), len(positions)
            )
        )
    return dict(matched)


def _verify_tmdb_movie_candidates(
    index: int,
    movie: dict[str, Any],
    candidates: list[Any],
) -> tuple[int, dict[str, Any] | None]:
    """Confirm one TMDB identity with the cheapest usable provider candidate."""
    aliases = _tmdb_movie_aliases(movie)
    wanted_year = str(movie.get("year") or "").strip()

    for candidate in candidates:
        slug = str(getattr(candidate, "slug", "") or "")
        try:
            loaded = state.fp_movies.get(slug) or load_movie_for_slug(slug)
        except Exception as exc:
            log(
                f"Filmquelle {getattr(candidate, 'title', slug)} nicht ladbar: {exc}",
                "warn",
            )
            continue
        if not loaded or not getattr(loaded, "hosters", None):
            continue
        if not _movie_matches_tmdb_choice(
            str(getattr(loaded, "title", "") or ""),
            str(getattr(loaded, "year", "") or getattr(candidate, "year", "") or ""),
            aliases,
            wanted_year,
        ):
            continue
        state.fp_movies[slug] = loaded
        return index, movie
    return index, None


def _provider_candidates_for_search(
    query: str,
    tmdb_results: list[dict[str, Any]],
) -> tuple[list[Any], dict[int, list[Any]]]:
    """Search providers once, with one bounded top-result title fallback."""
    try:
        provider_candidates = list(search_movie_candidates(query))
    except Exception as exc:
        # search_movie_candidates already isolates individual providers; this
        # protects the API from an unexpected aggregate failure.
        log(f"Film-Anbieterprüfung übersprungen: {exc}", "warn")
        provider_candidates = []

    candidates_by_index = _match_provider_candidates(
        tmdb_results,
        provider_candidates,
    )
    if 0 in candidates_by_index:
        return provider_candidates, candidates_by_index

    fallback_term = _top_result_fallback_term(query, tmdb_results)
    if not fallback_term:
        return provider_candidates, candidates_by_index

    try:
        provider_candidates.extend(search_movie_candidates(fallback_term))
    except Exception as exc:
        log(f"Alternative Film-Anbieterprüfung übersprungen: {exc}", "warn")
        return provider_candidates, candidates_by_index

    return provider_candidates, _match_provider_candidates(
        tmdb_results,
        provider_candidates,
    )


def _tmdb_search_results(query: str) -> list[dict[str, Any]]:
    """Return only TMDB films confirmed by an active provider with hosters.

    The expensive per-TMDB resolver used by detail/download flows is purposely
    not called here. All active providers are searched once in parallel for the
    user's query. If the top TMDB result is still unmatched, one alternate title
    is searched to cover localized/original-title differences. Only matching
    provider hits are detail-loaded, and checking stops for a movie as soon as
    one usable source with hosters is confirmed.
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

    # Prevent duplicate provider waves when several browser tabs submit the
    # same search concurrently. The critical section now contains at most two
    # bounded provider search waves instead of one full resolver per TMDB hit.
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

        _provider_candidates, candidates_by_index = _provider_candidates_for_search(
            query,
            tmdb_results,
        )
        if not candidates_by_index:
            _MOVIE_SEARCH_AVAILABILITY_CACHE[cache_key] = ()
            return []

        verified_by_index: dict[int, dict[str, Any]] = {}
        # Only TMDB identities that already have a matching provider search hit
        # reach the detail/hoster stage. Each worker walks providers in user
        # priority order and stops at the first confirmed source.
        with ThreadPoolExecutor(
            max_workers=min(8, len(candidates_by_index))
        ) as pool:
            futures = [
                pool.submit(
                    _verify_tmdb_movie_candidates,
                    index,
                    tmdb_results[index],
                    candidates,
                )
                for index, candidates in candidates_by_index.items()
            ]
            for future in as_completed(futures):
                index, movie = future.result()
                if movie is not None:
                    verified_by_index[index] = movie

        # Preserve TMDB relevance order even though provider detail checks may
        # finish in a different order.
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
