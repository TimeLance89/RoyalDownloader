"""Measured stream-quality inventory for subscribed movie upgrades.

For movie subscriptions the provider/hoster quality label is only a hint.  This
service inventories every hoster of every resolved provider source, samples the
real stream with ffprobe, compares the best measured profile with the Jellyfin
copy, and arms a staging-time guard so the existing movie is replaced only after
the fully downloaded file has independently proven to be better.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import api_library_router as library_router
import application_services.movie_subscription_quality as quality_service
from application_services.runtime import (
    backend_value,
    import_backend_namespace,
    publish_service,
)
from media_quality import (
    media_profile_complete,
    media_profile_from_height,
    media_profile_from_jellyfin_item,
    media_profile_is_better,
    media_profile_label,
    media_profile_within_target,
    media_quality_score,
    normalize_media_profile,
    probe_media_profile,
)

# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

globals().update(import_backend_namespace())

_PROBE_CACHE_FIELD = "quality_probe_cache"
_BASELINE_FIELD = "upgrade_probe_baseline_profile"
_AVAILABLE_PROFILE_FIELD = "upgrade_available_profile"
_PROBE_CHECKED_AT_FIELD = "upgrade_probe_checked_at"
_PROBE_SUCCESS_TTL = 2 * 60 * 60
_PROBE_FAILURE_TTL = 10 * 60
_JELLYFIN_PROFILE_TTL = 10 * 60
_MAX_PROBE_CACHE_ENTRIES = 96
_PRE_RESOLVED_TTL = 5 * 60

_ORIGINAL_EXTRACT_FROM_MOVIE = backend_value("_extract_from_movie")
_ORIGINAL_ENQUEUE_HOSTER_ATTEMPT = backend_value("_enqueue_hoster_attempt")
_HOSTER_RESULT = backend_value("_HosterResult")

_jellyfin_profile_cache: dict[tuple[str, str], tuple[float, dict]] = {}
_jellyfin_profile_lock = threading.RLock()


def _safe_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _stable_url(value: str) -> str:
    """Keep stable host/path identity while dropping rotating query tokens."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return raw
    if not parsed.scheme or not parsed.netloc:
        return raw.split("?", 1)[0].split("#", 1)[0]
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc.casefold(), parsed.path, "", ""))


def _candidate_key(source, hoster, index: int) -> str:
    """Identify one provider hoster slot without depending on signed URLs."""
    payload = {
        "provider": str(getattr(source, "provider", "") or _movie_provider(source)).casefold(),
        "source": _stable_url(getattr(source, "url", "")),
        "hoster_index": int(index),
        "hoster_name": str(getattr(hoster, "name", "") or "").strip().casefold(),
        "advertised_quality": str(getattr(hoster, "quality", "") or "").strip().casefold(),
        "language": str(getattr(hoster, "language", "") or "").strip().casefold(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _trim_probe_cache(cache: dict) -> dict:
    if len(cache) <= _MAX_PROBE_CACHE_ENTRIES:
        return cache
    ordered = sorted(
        cache.items(),
        key=lambda item: float((item[1] or {}).get("checked_at") or 0.0),
        reverse=True,
    )
    return dict(ordered[:_MAX_PROBE_CACHE_ENTRIES])


def _cached_probe(cache: dict, key: str, now: float) -> tuple[dict | None, bool]:
    record = cache.get(key)
    if not isinstance(record, dict):
        return None, False
    checked_at = float(record.get("checked_at") or 0.0)
    success = bool(record.get("ok"))
    ttl = _PROBE_SUCCESS_TTL if success else _PROBE_FAILURE_TTL
    if now - checked_at >= ttl:
        return None, False
    if not success:
        return None, True
    profile = normalize_media_profile(record.get("profile"))
    return (profile if media_profile_complete(profile) else None), True


def _store_probe(cache: dict, key: str, *, profile: dict | None, error: str = "") -> None:
    normalized = normalize_media_profile(profile)
    ok = media_profile_complete(normalized)
    cache[key] = {
        "checked_at": time.time(),
        "ok": ok,
        "profile": normalized if ok else {},
        "error": " ".join(str(error or "").split())[:160] if not ok else "",
    }


def _local_existing_profile(entry: dict) -> dict:
    paths: list[Path] = []
    existing = str(entry.get("existing_path") or "").strip()
    if existing:
        paths.append(Path(existing))
    try:
        title = clean_movie_title(str(entry.get("title") or ""))
        year = str(entry.get("year") or "")
        expected = Path(state.save_path) / build_movie_filename(title, year)
        paths.append(expected)
        if expected.parent.is_dir():
            paths.extend(
                candidate
                for candidate in expected.parent.glob(expected.stem + ".*")
                if candidate.suffix.casefold() in {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}
            )
    except (OSError, TypeError, ValueError):
        pass
    seen: set[Path] = set()
    best = {}
    for path in paths:
        try:
            resolved = path.expanduser().resolve(strict=False)
        except OSError:
            continue
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        profile, error = probe_media_profile(resolved)
        if error:
            continue
        if media_quality_score(profile) > media_quality_score(best):
            best = profile
    return normalize_media_profile(best)


def _jellyfin_raw_profile(jf_client, item: dict) -> dict:
    item_id = str(item.get("id") or "").strip()
    if not item_id or not jf_client.configured:
        return normalize_media_profile({})
    cache_key = (str(jf_client.base_url or ""), item_id)
    now = time.time()
    with _jellyfin_profile_lock:
        cached = _jellyfin_profile_cache.get(cache_key)
        if cached and now - cached[0] < _JELLYFIN_PROFILE_TTL:
            return normalize_media_profile(cached[1])
    try:
        raw_items = jf_client._list_items(
            {
                "Ids": item_id,
                "IncludeItemTypes": "Movie",
                "Recursive": "true",
                "CollapseBoxSetItems": "false",
                "ExcludeLocationTypes": "Virtual,Offline",
                "IsMissing": "false",
                "IsPlaceHolder": "false",
                "Fields": "MediaSources,Path",
            },
            1,
            "Jellyfin-Filmqualitätsprofil",
        )
    except Exception:
        raw_items = None
    profile = media_profile_from_jellyfin_item(raw_items[0] if raw_items else {})
    with _jellyfin_profile_lock:
        _jellyfin_profile_cache[cache_key] = (now, profile)
        if len(_jellyfin_profile_cache) > 256:
            oldest = min(_jellyfin_profile_cache, key=lambda key: _jellyfin_profile_cache[key][0])
            _jellyfin_profile_cache.pop(oldest, None)
    return profile


def _current_profile(entry: dict) -> dict:
    """Resolve the real current Jellyfin/local profile, with height-only fallback."""
    current_rank = _safe_int(entry.get("current_quality_rank"))

    # The file that exists *now* is authoritative.  A stored profile is only a
    # fallback because users can replace/downgrade media outside RoyalDownloader.
    local_profile = _local_existing_profile(entry)
    if media_profile_complete(local_profile):
        return local_profile

    jf_client = get_jellyfin_client()
    if jf_client.configured:
        try:
            items = get_jellyfin_library(force=False)
        except Exception:
            items = None
        if items:
            item = quality_service._jellyfin_item_for_subscription(entry, items)
            if item:
                path = str(item.get("path") or "").strip()
                if path:
                    profile, error = probe_media_profile(Path(path))
                    if not error and media_profile_complete(profile):
                        return profile
                profile = _jellyfin_raw_profile(jf_client, item)
                if media_profile_complete(profile):
                    return profile
                current_rank = max(current_rank, _safe_int(item.get("quality_rank")))

    stored = normalize_media_profile(entry.get("current_media_profile"))
    if stored["height"] and (not current_rank or stored["height"] == current_rank):
        return stored
    return media_profile_from_height(current_rank)


def _pre_resolved_payload(result, profile: dict) -> dict:
    return {
        "expires_at": time.time() + _PRE_RESOLVED_TTL,
        "stream_info": result.stream_info,
        "hoster_used": result.hoster_used,
        "hoster_url_used": result.hoster_url_used,
        "source_hoster_url": result.source_hoster_url,
        "referer": result.referer,
        "origin": result.origin,
        "gated": bool(result.gated),
        "provider": result.provider,
        "content_language": result.content_language,
        "quality": result.quality,
        "profile": normalize_media_profile(profile),
    }


def _probe_hoster(source, hoster, index: int, cache: dict, unsupported_domains: set, barren: set):
    key = _candidate_key(source, hoster, index)
    now = time.time()
    cached, known = _cached_probe(cache, key, now)
    if known:
        if cached is None:
            return None
        clone = replace(source, hosters=[hoster])
        clone._quality_inventory_candidate = True
        clone._probed_media_profile = cached
        return clone

    clone = replace(source, hosters=[hoster])
    with state.hoster_extract_lock:
        result = _ORIGINAL_EXTRACT_FROM_MOVIE(
            clone,
            unsupported_domains,
            barren_hoster_urls=barren,
        )
    if not result.stream_info:
        _store_probe(cache, key, profile=None, error="Hoster nicht auflösbar oder nicht ladbar")
        return None
    stream_url, _stream_type = result.stream_info
    profile, error = probe_media_profile(
        stream_url,
        referer=result.referer,
        origin=result.origin,
    )
    if error or not media_profile_complete(profile):
        _store_probe(cache, key, profile=None, error=error or "unvollständiges Medienprofil")
        return None
    _store_probe(cache, key, profile=profile)
    clone._quality_inventory_candidate = True
    clone._probed_media_profile = profile
    clone._quality_pre_resolved = _pre_resolved_payload(result, profile)
    return clone


def _prepare_movie_subscription_upgrade(entry: dict, sources: list):
    """Probe every provider/hoster and return only measured real upgrades."""
    baseline = _current_profile(entry)
    target = normalize_movie_quality(entry.get("target_quality"))
    with state.movie_subscriptions_lock:
        # The measured inventory supersedes the old advertised-quality URL guard.
        # Clear transient legacy candidate metadata so a stale signature cannot
        # reject a genuine same-resolution HDR/audio upgrade on completion.
        entry.pop("_upgrade_candidate_signature", None)
        entry.pop("_upgrade_candidate_from_rank", None)
        entry.pop("_upgrade_candidate_advertised_rank", None)
        raw_cache = entry.get(_PROBE_CACHE_FIELD)
        cache = dict(raw_cache) if isinstance(raw_cache, dict) else {}

    unsupported_domains: set = set()
    barren: set = set()
    candidates = []
    provider_count = 0
    hoster_count = 0
    for source_index, source in enumerate(sources or []):
        provider_count += 1
        for hoster_index, hoster in enumerate(list(getattr(source, "hosters", []) or [])):
            if not getattr(hoster, "url", ""):
                continue
            hoster_count += 1
            candidate = _probe_hoster(
                source,
                hoster,
                hoster_index,
                cache,
                unsupported_domains,
                barren,
            )
            if candidate is None:
                continue
            profile = normalize_media_profile(getattr(candidate, "_probed_media_profile", {}))
            if not media_profile_within_target(profile, target):
                continue
            if not media_profile_is_better(profile, baseline):
                continue
            candidates.append((media_quality_score(profile), -source_index, -hoster_index, candidate, profile))

    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    cache = _trim_probe_cache(cache)
    now = time.time()
    with state.movie_subscriptions_lock:
        entry[_PROBE_CACHE_FIELD] = cache
        entry[_BASELINE_FIELD] = normalize_media_profile(baseline)
        entry[_PROBE_CHECKED_AT_FIELD] = now
        entry["upgrade_probe_provider_count"] = provider_count
        entry["upgrade_probe_hoster_count"] = hoster_count
        if candidates:
            entry[_AVAILABLE_PROFILE_FIELD] = normalize_media_profile(candidates[0][4])
        else:
            entry.pop(_AVAILABLE_PROFILE_FIELD, None)
    if not candidates:
        return None, [], 0, ""

    primary = candidates[0][3]
    fallbacks = [item[3] for item in candidates[1:]]
    best_profile = candidates[0][4]
    label = media_profile_label(best_profile)
    log(
        f"Film-Abo: Qualitätsinventur «{entry.get('title', '')}»: "
        f"{provider_count} Anbieter / {hoster_count} Hoster geprüft; "
        f"beste echte Quelle {label} gegenüber {media_profile_label(baseline)}."
    )
    return primary, fallbacks, int(best_profile.get("height") or 0), label


def _extract_from_movie(movie, unsupported_domains: set, excluded_hoster_urls=None, barren_hoster_urls=None):
    """Reuse the just-probed stream for a few minutes instead of extracting twice."""
    cached = getattr(movie, "_quality_pre_resolved", None)
    source_url = str((cached or {}).get("source_hoster_url") or "")
    excluded = excluded_hoster_urls or set()
    barren = barren_hoster_urls or set()
    if (
        isinstance(cached, dict)
        and float(cached.get("expires_at") or 0.0) > time.time()
        and cached.get("stream_info")
        and source_url not in excluded
        and source_url not in barren
    ):
        result = _HOSTER_RESULT()
        for field in (
            "stream_info", "hoster_used", "hoster_url_used", "source_hoster_url",
            "referer", "origin", "gated", "provider", "content_language", "quality",
        ):
            setattr(result, field, cached.get(field))
        result.resolved_from_cache = True
        return result
    return _ORIGINAL_EXTRACT_FROM_MOVIE(
        movie,
        unsupported_domains,
        excluded_hoster_urls=excluded_hoster_urls,
        barren_hoster_urls=barren_hoster_urls,
    )


def _enqueue_hoster_attempt(*args, **kwargs):
    """Inventory candidates already got a fresh resolve; never redownload one twice."""
    movie = args[0] if args else kwargs.get("movie")
    result = args[3] if len(args) > 3 else kwargs.get("result")
    refreshed = args[10] if len(args) > 10 else kwargs.get("refreshed_hoster_urls")
    if (
        getattr(movie, "_quality_inventory_candidate", False)
        and result is not None
        and isinstance(refreshed, set)
        and getattr(result, "source_hoster_url", "")
    ):
        # The quality inventory resolved and sampled this source immediately
        # before scheduling.  If the full transfer or final quality guard fails,
        # move to the next measured candidate instead of repeating a whole movie.
        refreshed.add(result.source_hoster_url)
    return _ORIGINAL_ENQUEUE_HOSTER_ATTEMPT(*args, **kwargs)


# The library router resolves this helper locally.  Patch that seam as well as
# the backend so manual and scheduled subscription checks share one inventory.
library_router._prepare_movie_subscription_upgrade = _prepare_movie_subscription_upgrade

_SERVICE_EXPORTS = (
    "_prepare_movie_subscription_upgrade",
    "_extract_from_movie",
    "_enqueue_hoster_attempt",
)
publish_service(globals(), _SERVICE_EXPORTS)
