"""Provider-first movie search with optional TMDB metadata enrichment.

The provider catalogs are the source of truth for search availability. TMDB is
used only to enrich and coalesce provider hits; a missing or ambiguous TMDB
match must never hide a movie that an active provider returned.
"""
# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

from __future__ import annotations

import copy
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from application_services.runtime import import_backend_namespace, publish_service
from runtime_cache import BoundedTTLCache


globals().update(import_backend_namespace())

MOVIE_SEARCH_METADATA_MAX_RESULTS = 100
MOVIE_SEARCH_VERIFY_MAX_WORKERS = 12

# Search results are intentionally short-lived. Provider detail objects keep
# using the existing longer-lived caches in the composition root.
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
    return copy.deepcopy(list(cached))


def _normalize_search_term(value: str) -> str:
    return " ".join(str(value or "").split()).strip().casefold()


def _movie_search_cache_key(query: str) -> tuple[str, tuple[str, ...], str]:
    client = get_tmdb_client()
    return (
        _normalize_search_term(query),
        tuple(provider_priority("movies")),
        str(getattr(client, "language", "") or ""),
    )


def _candidate_provider(candidate: Any) -> str:
    return str(
        getattr(candidate, "provider", "")
        or provider_for_value(str(getattr(candidate, "slug", "") or ""))
    ).strip().casefold()


def _candidate_content_language(candidate: Any, loaded: Any = None) -> str:
    for value in (
        getattr(loaded, "content_language", "") if loaded is not None else "",
        getattr(candidate, "content_language", ""),
    ):
        normalized = normalize_content_language(str(value or ""))
        if normalized:
            return normalized
    return provider_content_language(_candidate_provider(candidate))


def _candidate_record(candidate: Any, position: int) -> dict[str, Any] | None:
    if not getattr(candidate, "is_movie", False):
        return None
    slug = str(getattr(candidate, "slug", "") or "").strip()
    provider = _candidate_provider(candidate)
    title = clean_movie_title(str(getattr(candidate, "title", "") or ""))
    keys = _movie_title_match_keys(title)
    if not slug or not provider or not title or not keys:
        return None
    return {
        "candidate": candidate,
        "position": position,
        "provider": provider,
        "slug": slug,
        "title": title,
        "keys": set(keys),
        "year": _resolved_movie_year(
            str(getattr(candidate, "title", "") or ""),
            str(getattr(candidate, "year", "") or ""),
        ),
    }


def _provider_candidate_records(query: str) -> list[dict[str, Any]]:
    try:
        candidates = list(search_movie_candidates(query))
    except Exception as exc:
        # search_movie_candidates isolates individual providers already; this
        # keeps an unexpected aggregate failure from breaking the HTTP route.
        log(f"Film-Anbietersuche fehlgeschlagen: {exc}", "warn")
        return []

    active = set(provider_priority("movies"))
    records: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for position, candidate in enumerate(candidates):
        record = _candidate_record(candidate, position)
        if record is None:
            continue
        if record["provider"] not in active or record["slug"] in seen_slugs:
            continue
        seen_slugs.add(record["slug"])
        records.append(record)
    return records


def _known_years_by_key(records: list[dict[str, Any]]) -> dict[str, set[str]]:
    known: dict[str, set[str]] = defaultdict(set)
    for record in records:
        year = str(record["year"] or "").strip()
        if not year:
            continue
        for key in record["keys"]:
            known[key].add(year)
    return known


def _resolved_group_year(
    record: dict[str, Any],
    known_years: dict[str, set[str]],
) -> str:
    year = str(record["year"] or "").strip()
    if year:
        return year
    possible = {
        known_year
        for key in record["keys"]
        for known_year in known_years.get(key, set())
    }
    return next(iter(possible)) if len(possible) == 1 else ""


def _years_can_group(
    group_year: str,
    record_year: str,
    shared_keys: set[str],
    known_years: dict[str, set[str]],
) -> bool:
    if group_year and record_year:
        return group_year == record_year
    if not group_year and not record_year:
        return True
    possible = {
        known_year
        for key in shared_keys
        for known_year in known_years.get(key, set())
    }
    known = group_year or record_year
    return len(possible) == 1 and known in possible


def _merge_group_into(target: dict[str, Any], source: dict[str, Any]) -> None:
    target["records"].extend(source["records"])
    target["keys"].update(source["keys"])
    target["years"].update(source["years"])
    target["position"] = min(target["position"], source["position"])
    if not target["match_year"]:
        target["match_year"] = source["match_year"]


def _group_provider_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group provider hits conservatively by normalized title aliases and year."""
    known_years = _known_years_by_key(records)
    groups: list[dict[str, Any]] = []

    for record in records:
        record_year = _resolved_group_year(record, known_years)
        compatible: list[int] = []
        for index, group in enumerate(groups):
            shared = set(record["keys"]) & set(group["keys"])
            if not shared:
                continue
            if _years_can_group(
                str(group["match_year"] or ""), record_year, shared, known_years
            ):
                compatible.append(index)

        new_group = {
            "records": [record],
            "keys": set(record["keys"]),
            "years": {str(record["year"])} if record["year"] else set(),
            "match_year": record_year,
            "position": record["position"],
            "tmdb": None,
        }
        if not compatible:
            groups.append(new_group)
            continue

        first = compatible[0]
        _merge_group_into(groups[first], new_group)
        for index in reversed(compatible[1:]):
            _merge_group_into(groups[first], groups[index])
            groups.pop(index)

    for group in groups:
        if not group["match_year"] and len(group["years"]) == 1:
            group["match_year"] = next(iter(group["years"]))
    groups.sort(key=lambda group: group["position"])
    return groups


def _tmdb_search_candidates(query: str) -> list[dict[str, Any]]:
    client = get_tmdb_client()
    if not client.configured:
        return []
    try:
        return [
            dict(movie)
            for movie in client.search_movies(
                query,
                max_results=MOVIE_SEARCH_METADATA_MAX_RESULTS,
            )
        ]
    except Exception as exc:
        log(f"TMDB-Metadaten für Filmsuche übersprungen: {exc}", "warn")
        return []


def _tmdb_movie_aliases(movie: dict[str, Any]) -> set[str]:
    return {
        key
        for title in (movie.get("title"), movie.get("original_title"))
        if title
        for key in _movie_title_match_keys(str(title))
        if key
    }


def _match_group_to_tmdb(
    group: dict[str, Any],
    tmdb_results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    group_year = str(group["match_year"] or "").strip()
    matches: list[dict[str, Any]] = []
    for movie in tmdb_results:
        aliases = _tmdb_movie_aliases(movie)
        if not aliases or not (aliases & set(group["keys"])):
            continue
        movie_year = str(movie.get("year") or "").strip()
        if group_year and movie_year and group_year != movie_year:
            continue
        matches.append(movie)

    if len(matches) == 1:
        return matches[0]
    if group_year:
        exact_year = [
            movie for movie in matches
            if str(movie.get("year") or "").strip() == group_year
        ]
        if len(exact_year) == 1:
            return exact_year[0]
    return None


def _coalesce_tmdb_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge localized provider groups when TMDB proves one shared identity."""
    merged: list[dict[str, Any]] = []
    by_tmdb_id: dict[int, dict[str, Any]] = {}
    for group in groups:
        movie = group.get("tmdb")
        tmdb_id = int(movie["tmdb_id"]) if movie and movie.get("tmdb_id") else None
        if tmdb_id is None or tmdb_id not in by_tmdb_id:
            merged.append(group)
            if tmdb_id is not None:
                by_tmdb_id[tmdb_id] = group
            continue
        target = by_tmdb_id[tmdb_id]
        _merge_group_into(target, group)
    merged.sort(key=lambda group: group["position"])
    return merged


def _provider_positions() -> dict[str, int]:
    return {
        provider: index
        for index, provider in enumerate(provider_priority("movies"))
    }


def _ordered_group_records(group: dict[str, Any]) -> list[dict[str, Any]]:
    positions = _provider_positions()
    return sorted(
        group["records"],
        key=lambda record: (
            positions.get(record["provider"], len(positions)),
            record["position"],
        ),
    )


def _verification_aliases(group: dict[str, Any]) -> set[str]:
    aliases = set(group["keys"])
    if group.get("tmdb"):
        aliases.update(_tmdb_movie_aliases(group["tmdb"]))
    return aliases


def _verify_group_primary(
    index: int,
    group: dict[str, Any],
) -> tuple[int, dict[str, Any] | None, Any | None]:
    """Resolve the first usable source without letting one bad provider hide a group."""
    aliases = _verification_aliases(group)
    wanted_year = str(
        (group.get("tmdb") or {}).get("year") or group.get("match_year") or ""
    ).strip()

    for record in _ordered_group_records(group):
        candidate = record["candidate"]
        slug = record["slug"]
        try:
            loaded = state.fp_movies.get(slug) or load_movie_for_slug(slug)
        except Exception as exc:
            log(f"Filmquelle {record['title']} nicht ladbar: {exc}", "warn")
            continue
        if not loaded or not getattr(loaded, "hosters", None):
            continue
        loaded_year = _resolved_movie_year(
            str(getattr(loaded, "title", "") or ""),
            str(
                getattr(loaded, "year", "")
                or getattr(candidate, "year", "")
                or ""
            ),
        )
        if wanted_year and (not loaded_year or loaded_year != wanted_year):
            continue
        if not (_movie_title_match_keys(str(getattr(loaded, "title", "") or "")) & aliases):
            continue
        state.fp_movies[slug] = loaded
        return index, record, loaded
    return index, None, None


def _source_payloads(group: dict[str, Any], verified_slug: str) -> list[dict[str, Any]]:
    positions = _provider_positions()
    best_by_provider: dict[str, dict[str, Any]] = {}
    for record in _ordered_group_records(group):
        provider = record["provider"]
        if provider in best_by_provider:
            continue
        candidate = record["candidate"]
        best_by_provider[provider] = {
            "key": provider,
            "label": PROVIDER_LABELS.get(provider, provider),
            "content_language": _candidate_content_language(candidate),
            "slug": record["slug"],
            "url": str(getattr(candidate, "url", "") or ""),
            "verified": record["slug"] == verified_slug,
        }
    return sorted(
        best_by_provider.values(),
        key=lambda source: positions.get(source["key"], len(positions)),
    )


def _group_result(
    group: dict[str, Any],
    record: dict[str, Any],
    loaded: Any,
) -> dict[str, Any]:
    candidate = record["candidate"]
    tmdb = dict(group.get("tmdb") or {})
    loaded_title = clean_movie_title(str(getattr(loaded, "title", "") or ""))
    candidate_title = clean_movie_title(str(getattr(candidate, "title", "") or ""))
    loaded_year = _resolved_movie_year(
        str(getattr(loaded, "title", "") or ""),
        str(getattr(loaded, "year", "") or getattr(candidate, "year", "") or ""),
    )
    provider = record["provider"]
    sources = _source_payloads(group, record["slug"])

    result: dict[str, Any] = {
        **tmdb,
        "title": tmdb.get("title") or loaded_title or candidate_title,
        "year": tmdb.get("year") or loaded_year or group.get("match_year") or "",
        "cover_url": (
            tmdb.get("cover_url")
            or str(getattr(candidate, "cover_url", "") or "")
            or str(getattr(loaded, "cover_url", "") or "")
        ),
        "description": tmdb.get("description") or "",
        "slug": record["slug"],
        "url": str(getattr(candidate, "url", "") or getattr(loaded, "url", "") or ""),
        "is_movie": True,
        "provider": provider,
        "provider_label": PROVIDER_LABELS.get(provider, provider),
        "content_language": _candidate_content_language(candidate, loaded),
        "sources": sources,
        "source_count": len(sources),
        "metadata_source": "TMDB" if tmdb.get("tmdb_id") else "provider",
    }
    if not tmdb.get("tmdb_id"):
        result["tmdb_id"] = None
    return result


def _tmdb_search_results(query: str) -> list[dict[str, Any]]:
    """Return provider-backed movie cards, optionally enriched by TMDB.

    The function name is retained for compatibility with the discovery router.
    Unlike the former implementation, providers are searched first and define
    the complete candidate set. TMDB can merge localized duplicates and enrich
    metadata, but TMDB result limits, outages, or ambiguous matches never remove
    a provider-backed movie. Each visible group is then validated against the
    first usable source in provider-priority order so a dead source does not make
    the card unopenable.
    """
    query = " ".join(str(query or "").split()).strip()
    if not query:
        return []

    cache_key = _movie_search_cache_key(query)
    try:
        return _copy_cached_results(_MOVIE_SEARCH_AVAILABILITY_CACHE[cache_key])
    except KeyError:
        pass

    with _MOVIE_SEARCH_AVAILABILITY_LOCK:
        try:
            return _copy_cached_results(_MOVIE_SEARCH_AVAILABILITY_CACHE[cache_key])
        except KeyError:
            pass

        records = _provider_candidate_records(query)
        if not records:
            _MOVIE_SEARCH_AVAILABILITY_CACHE[cache_key] = ()
            return []

        groups = _group_provider_records(records)
        tmdb_results = _tmdb_search_candidates(query)
        if tmdb_results:
            for group in groups:
                group["tmdb"] = _match_group_to_tmdb(group, tmdb_results)
            groups = _coalesce_tmdb_groups(groups)

        verified: dict[int, tuple[dict[str, Any], Any]] = {}
        with ThreadPoolExecutor(
            max_workers=min(MOVIE_SEARCH_VERIFY_MAX_WORKERS, len(groups))
        ) as pool:
            futures = [
                pool.submit(_verify_group_primary, index, group)
                for index, group in enumerate(groups)
            ]
            for future in as_completed(futures):
                index, record, loaded = future.result()
                if record is not None and loaded is not None:
                    verified[index] = (record, loaded)

        results = [
            _group_result(groups[index], *verified[index])
            for index in range(len(groups))
            if index in verified
        ]
        _MOVIE_SEARCH_AVAILABILITY_CACHE[cache_key] = tuple(
            copy.deepcopy(result) for result in results
        )
        return copy.deepcopy(results)


_SERVICE_EXPORTS = ("_tmdb_search_results",)
publish_service(globals(), _SERVICE_EXPORTS)
