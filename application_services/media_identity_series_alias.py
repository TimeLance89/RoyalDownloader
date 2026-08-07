"""Finalize TMDB series alias retry semantics for media identity v2.

TMDB's legacy ``series()`` cache normalizes punctuation out of its cache key.
That means a failed provider spelling such as ``Star Wars - Skeleton Crew``
can cache ``None`` under the same key needed by the corrected
``Star Wars: Skeleton Crew`` retry.  Media identity intentionally tries both
human spellings, so clear only that transient negative entry between alias
attempts while preserving every successful cache entry.
"""

from __future__ import annotations

import time
from typing import Optional

import tmdb_client as _tmdb_module

from application_services import media_identity as _identity


_ORIGINAL_SERIES = _identity._ORIGINAL_SERIES


def _series_with_alias_retry(self, title: str, force: bool = False) -> Optional[dict]:
    original_key = _tmdb_module._normalize(
        _identity._clean_query_seed(title, "series")
    )
    now = time.time()
    with self._lock:
        cached = self._series_cache.get(original_key)
        if (
            cached
            and cached[1] is not None
            and not force
            and now - cached[0] < _tmdb_module._series_cache_ttl(cached[1])
        ):
            return cached[1]

    negative_key = ("series", original_key)
    if not force and _identity._negative_cache_hit(self, negative_key):
        return None

    result = None
    for variant in _identity.media_title_variants(title, "series"):
        # The old resolver stores failed punctuation variants under the same
        # normalized key.  Remove only a cached miss before the next distinct
        # TMDB query; positive metadata is never discarded.
        variant_key = _tmdb_module._normalize(variant)
        with self._lock:
            cached_variant = self._series_cache.get(variant_key)
            if cached_variant and cached_variant[1] is None:
                self._series_cache.pop(variant_key, None)
        result = _ORIGINAL_SERIES(self, variant, force=force)
        if result:
            break

    with self._lock:
        self._series_cache[original_key] = (now, result)
    if result:
        _identity._forget_negative(self, negative_key)
    else:
        _identity._remember_negative(self, negative_key)
    return result


_tmdb_module.TMDBClient.series = _series_with_alias_retry
