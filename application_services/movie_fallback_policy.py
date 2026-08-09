"""Exhaustive cross-provider fallback policy for movie downloads.

Cached movie sources are useful seeds, but they are never proof that every
active provider was checked successfully.  This service keeps those seeds for
fast failover while forcing one live search across every still-untried movie
provider before a logical job may become terminal.
"""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from __future__ import annotations

from typing import Optional

from application_services.runtime import (
    backend_value,
    import_backend_namespace,
    publish_service,
)
from providers.models import FilmpalastMovie, FilmpalastSearchResult, parse_episode_slug


globals().update(import_backend_namespace())

_ORIGINAL_RUN_DOWNLOAD_QUEUE = backend_value("run_download_queue")


class _SeedFallbackMap(dict):
    """Expose cached movie fallbacks through ``get`` but not completeness checks.

    ``download_queue.run_download_queue`` historically used ``slug in
    movie_fallbacks`` as shorthand for "all providers already searched".  A
    cache entry cannot make that guarantee: it may be empty, stale, language
    filtered, or have been created while another provider was temporarily
    unavailable.  Known sources therefore stay readable through ``get`` while
    movie membership deliberately reports ``False`` until the runtime live
    fallback search has executed.
    """

    def __init__(self, values, incomplete_movie_slugs: set[str]):
        super().__init__(values or {})
        self._incomplete_movie_slugs = set(incomplete_movie_slugs)

    def __contains__(self, key):
        if key in self._incomplete_movie_slugs:
            return False
        return super().__contains__(key)


def run_download_queue(
    jobs: list[tuple],
    out_root,
    movie_fallbacks: Optional[dict[str, list[FilmpalastMovie]]] = None,
    start_queue: bool = True,
    cancelled=None,
):
    """Run the existing queue while treating movie fallback caches as seeds.

    Episode fallback semantics are unchanged.  For movies, an existing cache
    key no longer suppresses the live cross-provider search after the seeded
    sources fail.
    """

    movie_slugs = {
        slug for _movie, slug in jobs
        if parse_episode_slug(slug) is None
    }
    seeded_fallbacks = movie_fallbacks
    if movie_fallbacks is not None and movie_slugs:
        seeded_fallbacks = _SeedFallbackMap(movie_fallbacks, movie_slugs)
    return _ORIGINAL_RUN_DOWNLOAD_QUEUE(
        jobs,
        out_root,
        movie_fallbacks=seeded_fallbacks,
        start_queue=start_queue,
        cancelled=cancelled,
    )


def _movie_fallback_identity(movie: FilmpalastMovie) -> tuple[list[str], set[str], str]:
    """Build conservative search aliases and match keys for one logical movie."""

    title = clean_movie_title(movie.title)
    requested_year = str(movie.year or "").strip()
    summary = None
    try:
        client = get_tmdb_client()
        if client.configured:
            summary = client.movie_summary(title, requested_year)
    except Exception as exc:
        log(f"  TMDB-Identität für Film-Fallback nicht ladbar: {exc}", "warn")

    canonical_year = str((summary or {}).get("year") or requested_year).strip()
    raw_titles = [
        str((summary or {}).get("title") or "").strip(),
        str((summary or {}).get("original_title") or "").strip(),
        title,
    ]

    search_titles: list[str] = []
    aliases: list[str] = []
    seen_queries: set[str] = set()
    seen_aliases: set[str] = set()
    for raw in raw_titles:
        if not raw:
            continue
        for variant in media_title_variants(raw, "movie"):
            variant = " ".join(str(variant or "").split()).strip()
            key = normalize_media_identity_title(variant)
            if not key:
                continue
            if key not in seen_aliases:
                seen_aliases.add(key)
                aliases.append(variant)
            if key not in seen_queries and len(search_titles) < 3:
                seen_queries.add(key)
                search_titles.append(variant)

    match_keys = {
        key
        for alias in aliases
        for key in _movie_title_match_keys(alias)
        if key
    }
    return search_titles, match_keys, canonical_year


def _requested_movie_language(movie_slug: str) -> str:
    """Preserve the language lane already stored on the logical queue job."""

    try:
        job = _queue_job_for_slug(movie_slug)
    except Exception:
        job = None
    if not job:
        return ""
    return normalize_content_language(job.get("content_language"))


def _fallback_title_matches(title: str, match_keys: set[str]) -> bool:
    return bool(_movie_title_match_keys(title) & match_keys)


def find_movie_source_fallbacks(
    movie: FilmpalastMovie,
    selected_slug: str,
    excluded_urls: set,
) -> list[FilmpalastMovie]:
    """Search every still-untried active movie provider once before failure.

    Provider/title caches only seed ``source_movies`` in the caller.  This
    function is the authoritative live exhaustion pass.  Matching uses TMDB's
    canonical/original title when available plus Royal's media-identity aliases
    and the movie year.  At most one usable source per provider is returned, in
    the configured provider order, with no arbitrary six-provider cap.
    """

    title = clean_movie_title(movie.title)
    search_titles, match_keys, wanted_year = _movie_fallback_identity(movie)
    if not search_titles or not match_keys:
        return []

    active_providers = list(provider_priority("movies"))
    active_set = set(active_providers)
    attempted_providers = {_movie_provider(movie, selected_slug)}
    for url in excluded_urls:
        provider = provider_for_value(str(url or ""))
        if provider:
            attempted_providers.add(provider)
    attempted_providers.discard("")
    desired_language = _requested_movie_language(selected_slug)

    log(
        f"  Live-Fallback über verbleibende Filmanbieter für «{title}» …",
        "warn",
    )

    candidates: list[FilmpalastSearchResult] = []
    seen_candidate_slugs: set[str] = set()
    for search_title in search_titles:
        try:
            results = search_movie_candidates(search_title)
        except Exception as exc:
            log(f"  Film-Fallback-Suche für «{search_title}» fehlgeschlagen: {exc}", "warn")
            continue
        for candidate in results:
            provider = str(
                candidate.provider or provider_for_value(candidate.slug)
            ).strip().casefold()
            if (
                not candidate.is_movie
                or not provider
                or provider not in active_set
                or provider in attempted_providers
                or candidate.slug == selected_slug
                or candidate.slug in seen_candidate_slugs
                or candidate.url in excluded_urls
                or not _fallback_title_matches(candidate.title, match_keys)
            ):
                continue
            candidate_year = _resolved_movie_year(candidate.title, candidate.year)
            if wanted_year and candidate_year and candidate_year != wanted_year:
                continue
            seen_candidate_slugs.add(candidate.slug)
            candidates.append(candidate)

    positions = {provider: index for index, provider in enumerate(active_providers)}
    candidates.sort(
        key=lambda candidate: positions.get(
            str(candidate.provider or provider_for_value(candidate.slug)).casefold(),
            len(positions),
        )
    )

    alternatives: list[FilmpalastMovie] = []
    used_providers = set(attempted_providers)
    seen_urls = set(excluded_urls)
    for candidate in candidates:
        provider = str(
            candidate.provider or provider_for_value(candidate.slug)
        ).strip().casefold()
        if provider in used_providers:
            continue
        try:
            loaded = state.fp_movies.get(candidate.slug) or load_movie_for_slug(candidate.slug)
        except Exception as exc:
            log(f"  Filmquelle {candidate.title} nicht ladbar: {exc}", "warn")
            continue
        if not loaded or not loaded.hosters or loaded.url in seen_urls:
            continue
        loaded_provider = _movie_provider(loaded, candidate.slug)
        if not loaded_provider or loaded_provider in used_providers:
            continue
        if not _fallback_title_matches(loaded.title, match_keys):
            continue
        loaded_year = _resolved_movie_year(loaded.title, loaded.year or candidate.year)
        if wanted_year and (not loaded_year or loaded_year != wanted_year):
            continue
        if desired_language:
            source_language = normalize_content_language(
                _movie_content_language(loaded, fallback=candidate.slug)
            )
            if source_language and source_language != desired_language:
                continue
        state.fp_movies[candidate.slug] = loaded
        used_providers.add(loaded_provider)
        seen_urls.add(loaded.url)
        alternatives.append(loaded)

    alternatives.sort(
        key=lambda source: positions.get(_movie_provider(source), len(positions))
    )
    if alternatives:
        labels = ", ".join(
            PROVIDER_LABELS.get(_movie_provider(source), _movie_provider(source))
            for source in alternatives
        )
        log(f"  Live-Fallback gefunden: {labels}")
    else:
        log("  Kein weiterer aktiver Filmanbieter lieferte eine passende Quelle.", "warn")
    return alternatives


_SERVICE_EXPORTS = (
    "run_download_queue",
    "find_movie_source_fallbacks",
)
publish_service(globals(), _SERVICE_EXPORTS)
