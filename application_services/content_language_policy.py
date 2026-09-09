"""Language-aware catalog balancing and persistent movie download routing.

When German and English content are enabled together, provider count must not
turn into language dominance. Catalog entries are therefore assigned to
alternating language lanes while provider priority remains authoritative inside
each lane. Movie downloads can select a language without selecting one fixed
provider: all provider fallbacks remain available, but only within that chosen
language.
"""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from __future__ import annotations

import re
import threading
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field, replace
from typing import Any, Optional

from application_services.runtime import (
    backend_value,
    import_backend_namespace,
    publish_service,
)
from providers.catalog import normalize_content_language, provider_content_language
from providers.models import FilmpalastSearchResult, parse_episode_slug


globals().update(import_backend_namespace())

_ORIGINAL_MIX_MOVIES = backend_value("_mix_movie_provider_results")
_ORIGINAL_MIX_SERIES = backend_value("_mix_series_provider_results")
_ORIGINAL_LOAD_MOVIE = backend_value("load_movie_for_slug")
_ORIGINAL_PREFERRED_MOVIE_SOURCES = backend_value("_preferred_movie_sources")
_ORIGINAL_ENSURE_QUEUE_JOB = backend_value("_ensure_queue_job")
_ORIGINAL_CACHED_MOVIE_FALLBACKS = backend_value("cached_movie_source_fallbacks")

_RESOLUTION_GUARD = threading.local()
_LANGUAGE_PROVIDER_PREFIX = "language:"


@dataclass
class _LanguageAwareMovieResult(FilmpalastSearchResult):
    """Catalog result carrying all known stream languages for one identity."""

    content_languages: list[str] = field(default_factory=list)


def _mixed_german_english_enabled() -> bool:
    with state.provider_priority_lock:
        languages = {
            normalize_content_language(language)
            for language in state.content_languages
        }
    return "de" in languages and "en" in languages


def _provider_language(provider: str) -> str:
    return normalize_content_language(provider_content_language(provider))


def _result_language(provider: str, result) -> str:
    return _title_release_language(getattr(result, "title", "")) or normalize_content_language(
        str(getattr(result, "content_language", "") or "")
    ) or _provider_language(provider)


def _ordered_languages(values) -> list[str]:
    normalized = {
        normalize_content_language(value)
        for value in values
        if normalize_content_language(value)
    }
    return [language for language in ("de", "en") if language in normalized] + sorted(
        normalized - {"de", "en"}
    )


def _language_lane_order(groups: list[dict[str, Any]]) -> list[tuple[dict[str, Any], str]]:
    """Alternate EN/DE lanes and gracefully fill from whichever lane remains.

    A bilingual identity may satisfy either lane. Its visible primary source is
    chosen from that lane, while the complete language set stays attached to
    the logical card. Starting with English deliberately counters the much
    larger number of German providers without hiding German content.
    """

    remaining = list(groups)
    ordered: list[tuple[dict[str, Any], str]] = []
    target = "en"
    while remaining:
        index = next(
            (i for i, group in enumerate(remaining) if target in group["languages"]),
            None,
        )
        if index is None:
            index = 0
        group = remaining.pop(index)
        lane = target if target in group["languages"] else (
            "en" if "en" in group["languages"] else
            "de" if "de" in group["languages"] else ""
        )
        ordered.append((group, lane))
        target = "de" if target == "en" else "en"
    return ordered


def _movie_result_with_languages(result, languages: set[str]):
    return _LanguageAwareMovieResult(
        title=result.title,
        slug=result.slug,
        url=result.url,
        year=result.year,
        is_movie=result.is_movie,
        provider=result.provider,
        content_language=result.content_language,
        cover_url=result.cover_url,
        content_languages=_ordered_languages(languages),
    )


def _mix_movie_provider_results(
    provider_results,
    priority,
    claimed_identities: Optional[set[tuple]] = None,
    newest_first: bool = False,
):
    """Deduplicate movies by identity, then balance visible DE/EN language lanes."""

    if not _mixed_german_english_enabled():
        return _ORIGINAL_MIX_MOVIES(
            provider_results, priority, claimed_identities, newest_first=newest_first,
        )

    years_by_title = defaultdict(set)
    for results in provider_results.values():
        for result in results:
            title_key = _norm_title(clean_movie_title(result.title))
            year = str(result.year or "").strip()
            if title_key and year:
                years_by_title[title_key].add(year)

    already_claimed = claimed_identities if claimed_identities is not None else set()
    grouped: OrderedDict[tuple, list[tuple[str, Any]]] = OrderedDict()
    for provider in priority:
        for result in provider_results.get(provider, []):
            identity = _movie_result_identity(result, provider, years_by_title)
            if identity in already_claimed:
                continue
            grouped.setdefault(identity, []).append((provider, result))

    groups: list[dict[str, Any]] = []
    for identity, matches in grouped.items():
        if identity in already_claimed:
            continue
        already_claimed.add(identity)
        languages = {
            _result_language(provider, result)
            for provider, result in matches
            if _result_language(provider, result)
        }
        groups.append({
            "identity": identity,
            "matches": matches,
            "languages": languages,
        })

    if newest_first:
        ranks = {}
        for provider_index, provider in enumerate(priority):
            for index, result in enumerate(provider_results.get(provider, [])):
                identity = _movie_result_identity(result, provider, years_by_title)
                rank = (index, provider_index)
                ranks[identity] = min(rank, ranks.get(identity, rank))
        groups.sort(key=lambda group: ranks[group["identity"]])

    mixed = []
    for group, lane in _language_lane_order(groups):
        matches = group["matches"]
        primary_provider, primary_result = next(
            (
                (provider, result)
                for provider, result in matches
                if lane and _result_language(provider, result) == lane
            ),
            matches[0],
        )
        visible = _movie_result_with_languages(primary_result, group["languages"])
        visible.provider = primary_provider
        visible.content_language = _result_language(primary_provider, primary_result)
        mixed.append((primary_provider, visible))
    return mixed


def _mix_series_provider_results(
    provider_results,
    priority,
    claimed_identities: Optional[set[tuple]] = None,
):
    """Balance logical series identities by language instead of provider count."""

    if not _mixed_german_english_enabled():
        return _ORIGINAL_MIX_SERIES(provider_results, priority, claimed_identities)

    years_by_title = defaultdict(set)
    for results in provider_results.values():
        for result in results:
            title_key = _norm_title(strip_source_suffix(result.title))
            year = str(result.year or "").strip()
            if title_key and year:
                years_by_title[title_key].add(year)

    grouped: OrderedDict[tuple, list[tuple[str, Any]]] = OrderedDict()
    for provider in priority:
        for result in provider_results.get(provider, []):
            identity = _series_result_identity(result, provider, years_by_title)
            grouped.setdefault(identity, []).append((provider, result))

    seen = claimed_identities if claimed_identities is not None else set()
    groups = []
    for identity, matches in grouped.items():
        if _claim_series_identity(identity, seen):
            continue
        languages = {
            _provider_language(provider)
            for provider, _result in matches
            if _provider_language(provider)
        }
        groups.append({
            "identity": identity,
            "matches": matches,
            "languages": languages,
        })

    mixed = []
    for group, lane in _language_lane_order(groups):
        matches = group["matches"]
        primary_provider, primary_result = next(
            (
                (provider, result)
                for provider, result in matches
                if lane and _provider_language(provider) == lane
            ),
            matches[0],
        )
        source_set = {provider for provider, _result in matches}
        sources = tuple(provider for provider in priority if provider in source_set)
        year = str(primary_result.year or "").strip() or next(
            (str(result.year).strip() for _provider, result in matches if result.year),
            "",
        )
        cover_url = str(primary_result.cover_url or "").strip() or next(
            (
                str(result.cover_url).strip()
                for _provider, result in matches
                if result.cover_url
            ),
            "",
        )
        visible_result = replace(primary_result, year=year, cover_url=cover_url)
        mixed.append(_SeriesCatalogEntry(
            provider=primary_provider,
            result=visible_result,
            providers=sources or (primary_provider,),
        ))
    return mixed


def _queue_requested_language(slug: str) -> str:
    try:
        job = _queue_job_for_slug(slug)
    except Exception:
        return ""
    if not job:
        return ""
    return normalize_content_language(job.get("content_language"))


def _source_language(source) -> str:
    return normalize_content_language(_movie_content_language(source))


def _cached_sources(slug: str, movie=None) -> list:
    with state.movie_source_cache_lock:
        sources = list(state.movie_source_cache.get(slug) or [])
    if not sources and movie is not None:
        sources = [movie]
    return sources


def _expand_catalog_movie_sources(slug: str, movie):
    """Resolve all active provider languages only when a catalog detail is opened."""

    if movie is None or parse_episode_slug(slug):
        return [movie] if movie is not None else []
    sources = _cached_sources(slug, movie)
    languages = {_source_language(source) for source in sources if _source_language(source)}
    desired = _queue_requested_language(slug)
    needs_mixed_resolution = _mixed_german_english_enabled() and not {"de", "en"}.issubset(languages)
    needs_selected_resolution = bool(desired and desired not in languages)
    if not (needs_mixed_resolution or needs_selected_resolution):
        return sources

    summary = get_tmdb_client().movie_summary(clean_movie_title(movie.title), movie.year)
    tmdb_id = str((summary or {}).get("tmdb_id") or "").strip()
    if not tmdb_id.isdigit():
        return sources
    try:
        _RESOLUTION_GUARD.active = True
        resolved = list(resolve_tmdb_movie_sources(tmdb_id))
    except Exception as exc:
        log(f"Sprachquellen für «{movie.title}» konnten nicht gebündelt werden: {exc}", "warn")
        return sources
    finally:
        _RESOLUTION_GUARD.active = False
    if not resolved:
        return sources
    with state.movie_source_cache_lock:
        state.movie_source_cache[slug] = list(resolved)
    return resolved


def load_movie_for_slug(slug: str):
    """Load a movie and lazily expose all languages for mixed DE/EN details."""

    if getattr(_RESOLUTION_GUARD, "active", False):
        return _ORIGINAL_LOAD_MOVIE(slug)

    is_tmdb_slug = bool(re.fullmatch(r"tmdb:\d+", str(slug or ""), flags=re.IGNORECASE))
    if is_tmdb_slug:
        try:
            _RESOLUTION_GUARD.active = True
            movie = _ORIGINAL_LOAD_MOVIE(slug)
        finally:
            _RESOLUTION_GUARD.active = False
    else:
        movie = _ORIGINAL_LOAD_MOVIE(slug)
    if movie is None or parse_episode_slug(slug):
        return movie

    sources = _cached_sources(slug, movie)
    if not is_tmdb_slug:
        sources = _expand_catalog_movie_sources(slug, movie)

    desired = _queue_requested_language(slug)
    if desired:
        selected = next(
            (source for source in sources if _source_language(source) == desired),
            None,
        )
        if selected is not None:
            state.fp_movies[slug] = selected
            return selected
    return movie


def _preferred_movie_sources(slug: str, movie, preference):
    """Select a language lane while retaining provider fallback inside that lane."""

    provider = str(getattr(preference, "provider", "") or "").strip().casefold()
    if (
        preference is None
        or parse_episode_slug(slug)
        or not provider.startswith(_LANGUAGE_PROVIDER_PREFIX)
    ):
        return _ORIGINAL_PREFERRED_MOVIE_SOURCES(slug, movie, preference)

    language = normalize_content_language(provider.removeprefix(_LANGUAGE_PROVIDER_PREFIX))
    if language not in {"de", "en"}:
        raise ValueError("Unbekannte Downloadsprache.")

    sources = _cached_sources(slug, movie)
    matching = [source for source in sources if _source_language(source) == language]
    if not matching:
        matching = [
            source for source in _expand_catalog_movie_sources(slug, movie)
            if _source_language(source) == language
        ]
    if not matching:
        label = "Deutsch" if language == "de" else "Englisch"
        raise LookupError(f"{label} ist für diesen Film derzeit nicht verfügbar.")

    positions = {
        provider_key: index
        for index, provider_key in enumerate(provider_priority("movies"))
    }
    matching.sort(key=lambda source: positions.get(_movie_provider(source), len(positions)))
    chosen = replace(matching[0], hosters=list(matching[0].hosters))
    chosen.content_language = language
    quality = str(getattr(preference, "quality", "") or "").strip()
    hoster_url = str(getattr(preference, "hoster_url", "") or "").strip()
    chosen._preferred_quality = quality
    if hoster_url:
        chosen.hosters.sort(key=lambda hoster: str(hoster.url or "").strip() != hoster_url)
    return chosen, list(matching[1:])


def _ensure_queue_job(slug: str, movie=None, *, job_id: str = ""):
    """Persist the selected stream language on the stable logical queue job."""

    job = _ORIGINAL_ENSURE_QUEUE_JOB(slug, movie, job_id=job_id)
    if movie is None:
        return job
    provider = _movie_provider(movie)
    language = _source_language(movie)
    with state.queue_claim_lock:
        if provider and not job.get("provider"):
            job["provider"] = provider
        # Never overwrite an existing language during restart/retry recovery.
        if language and not job.get("content_language"):
            job["content_language"] = language
    return job


def cached_movie_source_fallbacks(slug: str):
    """Keep restored/retried movie fallbacks inside the persisted language lane."""

    fallbacks = _ORIGINAL_CACHED_MOVIE_FALLBACKS(slug)
    desired = _queue_requested_language(slug)
    if not desired or fallbacks is None:
        return fallbacks
    current = state.fp_movies.get(slug)
    current_url = str(getattr(current, "url", "") or "")
    return [
        source
        for source in fallbacks
        if _source_language(source) == desired
        and str(getattr(source, "url", "") or "") != current_url
    ]


_SERVICE_EXPORTS = (
    "_mix_movie_provider_results",
    "_mix_series_provider_results",
    "load_movie_for_slug",
    "_preferred_movie_sources",
    "_ensure_queue_job",
    "cached_movie_source_fallbacks",
)
publish_service(globals(), _SERVICE_EXPORTS)
