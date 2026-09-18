"""Install runtime compatibility for provider series source migrations."""

from __future__ import annotations

from functools import wraps

from application_services import runtime as _runtime
from providers import serienstream as _serienstream
from providers.models import FilmpalastSeriesResult
from providers.series_migrations import (
    canonical_identity_for_source,
    canonical_provider_series_slug,
    canonical_series_source,
    equivalent_series_sources,
    series_search_identity,
)
from providers.series_tmdb_overrides import (
    apply_tmdb_season_override,
    tmdb_series_override_for_value,
)


_PROVIDER_PREFIX = {
    "serienstream": "serienstream:",
}
_PROVIDER_URL = {
    "serienstream": "https://serienstream.to/serie/{slug}",
}
_PROVIDER_SUFFIX = {
    "serienstream": "  [S.to]",
}


def _canonical_result(identity, result=None) -> FilmpalastSeriesResult:
    """Build a provider result whose navigation identity stays provider-native."""
    prefix = _PROVIDER_PREFIX[identity.provider]
    base_slug = f"{prefix}{identity.canonical_slug}"
    return FilmpalastSeriesResult(
        title=f"{identity.title}{_PROVIDER_SUFFIX.get(identity.provider, '')}",
        base_slug=base_slug,
        sample_slug=str(getattr(result, "sample_slug", "") or base_slug),
        sample_url=str(
            getattr(result, "sample_url", "")
            or _PROVIDER_URL[identity.provider].format(slug=identity.canonical_slug)
        ),
        year=identity.year,
        cover_url=str(getattr(result, "cover_url", "") or ""),
    )


def _canonicalize_provider_results(provider: str, results) -> list[FilmpalastSeriesResult]:
    """Collapse legacy provider hits onto the current canonical series source."""
    normalized: list[FilmpalastSeriesResult] = []
    seen: set[str] = set()
    for result in results or []:
        identity = canonical_identity_for_source(
            result.base_slug or result.sample_slug or result.sample_url
        )
        current = _canonical_result(identity, result) if identity else result
        key = str(current.base_slug or current.sample_slug or current.sample_url).casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(current)
    return normalized


def _is_direct_canonical_search(query: str, identity) -> bool:
    """Return True for explicit provider URLs/prefixes or canonical bare slugs."""
    raw = str(query or "").strip()
    if not raw:
        return False
    if canonical_identity_for_source(raw) is not None:
        return True
    return raw.casefold() == identity.canonical_slug.casefold()


def _canonical_provider_hit(backend, identity):
    """Resolve the current provider card without leaking fuzzy cross-provider hits."""
    canonical_source = f"{_PROVIDER_PREFIX[identity.provider]}{identity.canonical_slug}"
    try:
        canonical_hits = backend._search_series_for_provider(
            identity.provider, identity.title,
        )
    except Exception:
        canonical_hits = []
    canonical_hits = _canonicalize_provider_results(identity.provider, canonical_hits)
    matching = next((
        result for result in canonical_hits
        if equivalent_series_sources(
            result.base_slug or result.sample_slug or result.sample_url,
            canonical_source,
        )
    ), None)
    return matching or _canonical_result(identity)


def _install_serienstream_migrations() -> None:
    scraper = _serienstream.SerienstreamScraper
    if getattr(scraper, "_royal_series_migrations_installed", False):
        return

    original_series_slug = scraper._series_slug
    original_get_movie = scraper.get_movie

    @staticmethod
    def migrated_series_slug(value: str) -> str:
        return canonical_provider_series_slug("serienstream", original_series_slug(value))

    @wraps(original_get_movie)
    def migrated_get_movie(self, url_or_slug: str):
        return original_get_movie(self, canonical_series_source(url_or_slug))

    scraper._series_slug = migrated_series_slug
    scraper.get_movie = migrated_get_movie
    scraper._royal_series_migrations_installed = True


def _install_watchlist_migrations() -> None:
    backend = _runtime._registered_backend()
    original_lookup = backend.watchlist_lookup
    if getattr(original_lookup, "_royal_series_migrations_installed", False):
        return

    @wraps(original_lookup)
    def migrated_watchlist_lookup(base_slug: str):
        # First prefer an exact persisted row, preserving existing behavior.
        exact = original_lookup(base_slug)
        if exact is not None:
            return exact
        for entry in backend.state.watchlist:
            if equivalent_series_sources(entry.get("base_slug", ""), base_slug):
                return entry
        return None

    migrated_watchlist_lookup._royal_series_migrations_installed = True
    backend.watchlist_lookup = migrated_watchlist_lookup


def _install_load_migrations() -> None:
    """Keep explicit migrated provider identities strict while loading details."""
    backend = _runtime._registered_backend()
    original_get_series_for_value = backend.get_series_for_value
    if getattr(original_get_series_for_value, "_royal_series_load_migrations_installed", False):
        return

    @wraps(original_get_series_for_value)
    def migrated_get_series_for_value(value: str, fallback_title: str = ""):
        tmdb_override = tmdb_series_override_for_value(value)
        if tmdb_override is not None:
            try:
                source_series = backend._load_series_for_provider(
                    tmdb_override.provider,
                    tmdb_override.provider_source,
                )
            except Exception as exc:
                backend.log(
                    f"TMDB-Serie {tmdb_override.tmdb_id} konnte nicht aus "
                    f"{tmdb_override.provider_source} geladen werden: {exc}",
                    "warn",
                )
                return None
            if source_series is None:
                return None
            return apply_tmdb_season_override(source_series, tmdb_override)

        identity = canonical_identity_for_source(value)
        if identity is None:
            return original_get_series_for_value(value, fallback_title)

        canonical_source = (
            f"{_PROVIDER_PREFIX[identity.provider]}{identity.canonical_slug}"
        )
        try:
            series = backend._load_series_for_provider(identity.provider, canonical_source)
        except Exception as exc:
            backend.log(
                f"{_PROVIDER_SUFFIX.get(identity.provider, identity.provider)} "
                f"Serie «{identity.title}» direkt nicht ladbar: {exc}",
                "warn",
            )
            series = None
        if series is not None and getattr(series, "seasons", None):
            return series

        # Eine explizite Provider-Identität darf niemals per Fuzzy-Fallback zu
        # einer anderen Serie oder sogar einem anderen Anbieter mutieren. Ein
        # letzter Retry bleibt deshalb auf denselben Provider beschränkt und
        # akzeptiert nur den kanonisch äquivalenten Treffer.
        try:
            hits = backend._search_series_for_provider(identity.provider, identity.title)
        except Exception:
            hits = []
        for hit in _canonicalize_provider_results(identity.provider, hits):
            if not equivalent_series_sources(
                hit.base_slug or hit.sample_slug or hit.sample_url,
                canonical_source,
            ):
                continue
            try:
                series = backend._load_series_for_provider(
                    identity.provider,
                    hit.sample_slug or hit.base_slug or hit.sample_url,
                )
            except Exception:
                series = None
            if series is not None and getattr(series, "seasons", None):
                return series
        return None

    migrated_get_series_for_value._royal_series_load_migrations_installed = True
    backend.get_series_for_value = migrated_get_series_for_value


def _install_search_migrations() -> None:
    """Keep provider identities authoritative through discovery and UI payloads."""
    backend = _runtime._registered_backend()
    original_provider_search = backend._search_series_provider_results
    if getattr(original_provider_search, "_royal_series_search_migrations_installed", False):
        return

    @wraps(original_provider_search)
    def migrated_provider_search(query: str):
        identity = series_search_identity(query)
        if identity is not None and _is_direct_canonical_search(query, identity):
            active = list(backend.provider_priority("series"))
            if identity.provider not in active:
                return {}
            return {identity.provider: [_canonical_provider_hit(backend, identity)]}

        # Freie Titelsuchen bleiben vollständig provider-first. Insbesondere
        # "Monster" darf die getrennten TMDB-Serien/Provider-Treffer zeigen;
        # die Sonderzuordnung auf S.to passiert erst beim Öffnen per TMDB-ID.
        return original_provider_search(query)

    migrated_provider_search._royal_series_search_migrations_installed = True
    backend._search_series_provider_results = migrated_provider_search

    original_search_catalog = backend.series_search_catalog

    @wraps(original_search_catalog)
    def migrated_search_catalog(query: str):
        catalog = original_search_catalog(query)
        identity = series_search_identity(query)
        if identity is None or not _is_direct_canonical_search(query, identity):
            return catalog
        canonical_source = f"{_PROVIDER_PREFIX[identity.provider]}{identity.canonical_slug}"
        entries = list(catalog.get("entries") or [])
        entries.sort(key=lambda entry: not equivalent_series_sources(
            entry.result.base_slug or entry.result.sample_slug or entry.result.sample_url,
            canonical_source,
        ))
        return {**catalog, "entries": entries}

    backend.series_search_catalog = migrated_search_catalog

    original_entry_to_dict = backend._series_entry_to_dict

    @wraps(original_entry_to_dict)
    def migrated_entry_to_dict(entry):
        payload = original_entry_to_dict(entry)
        raw_source = (
            entry.result.base_slug or entry.result.sample_slug or entry.result.sample_url
        )
        identity = canonical_identity_for_source(raw_source)
        if (
            identity is not None
            and canonical_series_source(raw_source).casefold()
            == str(raw_source or "").strip().casefold()
        ):
            payload["metadata_policy"] = identity.metadata_policy
            payload["canonical_series_source"] = (
                f"{_PROVIDER_PREFIX[identity.provider]}{identity.canonical_slug}"
            )
        return payload

    backend._series_entry_to_dict = migrated_entry_to_dict


_install_serienstream_migrations()
_install_watchlist_migrations()
_install_load_migrations()
_install_search_migrations()
