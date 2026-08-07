"""Target-aware HLS variant selection for subscription deep probes."""

from __future__ import annotations

import threading
import time
from dataclasses import replace

import application_services.movie_subscription_probe_optimizer as optimizer
import application_services.movie_subscription_stream_quality as stream_quality
from media_quality import (
    media_profile_complete,
    media_profile_within_target,
    normalize_media_profile,
    probe_media_profile,
)


def _selected_manifest_variant(
    stream_url: str,
    baseline: dict,
    target: str,
    *,
    referer: str = "",
    origin: str = "",
):
    text, error = optimizer._fetch_hls_manifest(
        stream_url,
        referer=referer,
        origin=origin,
    )
    if error:
        return {}, "", error, False
    variants = optimizer._manifest_variants(text, stream_url)
    if not variants:
        return {}, "", "HLS-Medienplaylist ohne Master-Varianten", False
    eligible = [
        item
        for item in variants
        if media_profile_within_target(item["profile"], target)
    ]
    if not eligible:
        return {}, "", "Keine HLS-Variante innerhalb der Zielqualität", True
    selected = max(
        eligible,
        key=lambda item: (
            int(item["profile"].get("height") or 0),
            int(item["profile"].get("width") or 0),
            int(item["profile"].get("video_bitrate") or 0),
        ),
    )
    profile = normalize_media_profile(selected["profile"])
    baseline_height = int(normalize_media_profile(baseline).get("height") or 0)
    if baseline_height and int(profile.get("height") or 0) < baseline_height:
        return profile, str(selected.get("uri") or ""), (
            "HLS-Master eindeutig unter vorhandener Auflösung"
        ), True
    return profile, str(selected.get("uri") or ""), "", False


def _merge_profile(primary: dict, fallback: dict) -> dict:
    merged = normalize_media_profile(primary)
    other = normalize_media_profile(fallback)
    for key, value in other.items():
        current = merged.get(key)
        if current in (None, "", 0, 0.0) and value not in (None, "", 0, 0.0):
            merged[key] = value
    return normalize_media_profile(merged)


def _probe_uncached(
    source,
    hoster,
    index: int,
    cache: dict,
    cache_lock: threading.RLock,
    unsupported_domains: set,
    barren: set,
    baseline: dict,
    target: str,
    counters: dict[str, int],
    counter_lock: threading.RLock,
):
    key = stream_quality._candidate_key(source, hoster, index)
    clone = replace(source, hosters=[hoster])
    with stream_quality.state.hoster_extract_lock:
        result = stream_quality._ORIGINAL_EXTRACT_FROM_MOVIE(
            clone,
            unsupported_domains,
            barren_hoster_urls=barren,
        )
    if not result.stream_info:
        with cache_lock:
            stream_quality._store_probe(
                cache,
                key,
                profile=None,
                error="Hoster nicht auflösbar oder nicht ladbar",
            )
        return None

    stream_url, stream_type = result.stream_info
    manifest_profile = {}
    selected_uri = ""
    manifest_reason = ""
    skip_deep = False
    if str(stream_type or "").casefold() == "hls" or ".m3u8" in stream_url.casefold():
        manifest_profile, selected_uri, manifest_reason, skip_deep = _selected_manifest_variant(
            stream_url,
            baseline,
            target,
            referer=result.referer,
            origin=result.origin,
        )
        with counter_lock:
            counters["manifest"] += 1
    if skip_deep:
        with cache_lock:
            optimizer._store_manifest_skip(cache, key, manifest_profile, manifest_reason)
        with counter_lock:
            counters["manifest_skipped"] += 1
        return None

    with counter_lock:
        counters["deep"] += 1
    probe_url = selected_uri or stream_url
    profile, error = probe_media_profile(
        probe_url,
        referer=result.referer,
        origin=result.origin,
    )
    profile = _merge_profile(profile, manifest_profile)
    if error and not media_profile_complete(profile) and probe_url != stream_url:
        fallback_profile, fallback_error = probe_media_profile(
            stream_url,
            referer=result.referer,
            origin=result.origin,
        )
        fallback_profile = _merge_profile(fallback_profile, manifest_profile)
        if media_profile_complete(fallback_profile):
            profile, error = fallback_profile, ""
        else:
            error = fallback_error or error
    if error and not media_profile_complete(profile):
        with cache_lock:
            stream_quality._store_probe(cache, key, profile=None, error=error)
        return None

    profile = normalize_media_profile(profile)
    with cache_lock:
        stream_quality._store_probe(cache, key, profile=profile)
    clone._quality_inventory_candidate = True
    clone._probed_media_profile = profile
    clone._quality_pre_resolved = stream_quality._pre_resolved_payload(result, profile)
    return clone


optimizer._probe_uncached = _probe_uncached
