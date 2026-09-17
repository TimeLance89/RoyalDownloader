"""Install runtime compatibility for provider series source migrations."""

from __future__ import annotations

from functools import wraps

from application_services import runtime as _runtime
from providers import serienstream as _serienstream
from providers.series_migrations import (
    canonical_provider_series_slug,
    canonical_series_source,
    equivalent_series_sources,
)


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


_install_serienstream_migrations()
_install_watchlist_migrations()
