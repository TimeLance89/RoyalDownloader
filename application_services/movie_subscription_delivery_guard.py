"""Block repeated delivery of an unchanged movie-subscription upgrade."""

from __future__ import annotations

import hashlib
import json
import time

import api_library_router as library_router
import application_services.source_resolution as source_resolution
import application_services.movie_subscription_quality_hardening as hardening
import application_services.movie_subscription_stream_quality as stream_quality
from application_services.runtime import (
    backend_value,
    import_backend_namespace,
    publish_service,
)
from media_quality import (
    media_profile_complete,
    media_profile_is_better,
    normalize_media_profile,
)

# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

globals().update(import_backend_namespace())

_ORIGINAL_PREPARE_UPGRADE = hardening._prepare_movie_subscription_upgrade
_ORIGINAL_DOWNLOAD_FINISHED = backend_value("_movie_subscription_download_finished")
_ORIGINAL_DOWNLOAD_FAILED = backend_value("_movie_subscription_download_failed")

_ACTIVE_FINGERPRINT = "_upgrade_delivery_fingerprint"
_LAST_FINGERPRINT = "upgrade_last_delivered_fingerprint"
_LAST_PROFILE = "upgrade_last_delivered_profile"
_LAST_AT = "upgrade_last_delivered_at"
_ACTIVE_INVENTORY = "_upgrade_active_inventory_fingerprint"
_FAILED_INVENTORY = "upgrade_last_failed_inventory_fingerprint"
_FAILED_INVENTORY_AT = "upgrade_last_failed_inventory_at"
_SUCCESS_SETTLE_SECONDS = 24 * 60 * 60


def _candidate_fingerprint(entry: dict, primary) -> str:
    hosters = list(getattr(primary, "hosters", []) or [])
    if not hosters:
        return ""
    profile = normalize_media_profile(
        getattr(primary, "_probed_media_profile", None)
        or entry.get("upgrade_available_profile")
    )
    if not media_profile_complete(profile):
        return ""
    payload = {
        "candidate": hardening._candidate_key(primary, hosters[0], 0),
        "profile": profile,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _inventory_fingerprint(entry: dict, candidates: list) -> str:
    fingerprints = sorted(filter(None, (
        _candidate_fingerprint(entry, candidate) for candidate in candidates
    )))
    if not fingerprints:
        return ""
    return hashlib.sha256("|".join(fingerprints).encode("ascii")).hexdigest()


def _confirmed_local_downgrade(entry: dict) -> bool:
    previous = normalize_media_profile(entry.get(_LAST_PROFILE))
    if not media_profile_complete(previous):
        return False
    current = stream_quality._local_existing_profile(entry)
    return bool(
        media_profile_complete(current)
        and media_profile_is_better(previous, current)
    )


def _prepare_movie_subscription_upgrade(entry: dict, sources: list):
    """Allow an unchanged candidate once, unless the local file truly regressed."""
    result = _ORIGINAL_PREPARE_UPGRADE(entry, sources)
    primary = result[0] if result else None
    if primary is None:
        with state.movie_subscriptions_lock:
            entry.pop(_ACTIVE_FINGERPRINT, None)
            entry.pop(_ACTIVE_INVENTORY, None)
        return result

    fingerprint = _candidate_fingerprint(entry, primary)
    inventory = _inventory_fingerprint(entry, [primary, *(result[1] or [])])
    delivered = str(entry.get(_LAST_FINGERPRINT) or "")
    failed_inventory = str(entry.get(_FAILED_INVENTORY) or "")
    try:
        last_upgraded = float(entry.get("last_upgraded") or 0.0)
    except (TypeError, ValueError):
        last_upgraded = 0.0
    settling_legacy_success = bool(
        not delivered
        and last_upgraded > 0
        and time.time() - last_upgraded < _SUCCESS_SETTLE_SECONDS
    )
    repeated = bool(
        settling_legacy_success
        or (inventory and inventory == failed_inventory and not _confirmed_local_downgrade(entry))
        or (
            fingerprint
            and fingerprint == delivered
            and not _confirmed_local_downgrade(entry)
        )
    )
    with state.movie_subscriptions_lock:
        if repeated:
            entry.pop(_ACTIVE_FINGERPRINT, None)
            entry.pop(_ACTIVE_INVENTORY, None)
            entry.pop("upgrade_available_profile", None)
            return None, [], 0, ""
        if fingerprint:
            entry[_ACTIVE_FINGERPRINT] = fingerprint
        else:
            entry.pop(_ACTIVE_FINGERPRINT, None)
        if inventory:
            entry[_ACTIVE_INVENTORY] = inventory
        else:
            entry.pop(_ACTIVE_INVENTORY, None)
    return result


def _subscription_for_slug(slug: str) -> dict | None:
    with state.movie_subscriptions_lock:
        return next(
            (
                entry
                for entry in state.movie_subscriptions
                if entry.get("pending_slug") == slug
                or entry.get("source_slug") == slug
                or entry.get("key") == slug
            ),
            None,
        )


def _movie_subscription_download_finished(movie_slug, out_path, quality) -> None:
    entry = _subscription_for_slug(str(movie_slug or ""))
    fingerprint = ""
    offered_profile = {}
    if entry is not None:
        with state.movie_subscriptions_lock:
            fingerprint = str(entry.get(_ACTIVE_FINGERPRINT) or "")
            offered_profile = normalize_media_profile(entry.get("upgrade_available_profile"))

    _ORIGINAL_DOWNLOAD_FINISHED(movie_slug, out_path, quality)

    if entry is None:
        return
    changed = False
    with state.movie_subscriptions_lock:
        if not any(current is entry for current in state.movie_subscriptions):
            return
        delivered_profile = normalize_media_profile(entry.get("current_media_profile"))
        if not media_profile_complete(delivered_profile):
            delivered_profile = offered_profile
        if fingerprint:
            entry[_LAST_FINGERPRINT] = fingerprint
            entry[_LAST_PROFILE] = delivered_profile
            entry[_LAST_AT] = time.time()
            changed = True
        if _ACTIVE_FINGERPRINT in entry:
            entry.pop(_ACTIVE_FINGERPRINT, None)
            changed = True
    if changed:
        _persist_movie_subscriptions_background()


def _movie_subscription_download_failed(movie_slug: str, message: str) -> None:
    entry = _subscription_for_slug(str(movie_slug or ""))
    inventory = ""
    if entry is not None:
        with state.movie_subscriptions_lock:
            inventory = str(entry.get(_ACTIVE_INVENTORY) or "")
    try:
        _ORIGINAL_DOWNLOAD_FAILED(movie_slug, message)
    finally:
        if entry is not None:
            with state.movie_subscriptions_lock:
                entry.pop(_ACTIVE_FINGERPRINT, None)
                entry.pop(_ACTIVE_INVENTORY, None)
                normalized_message = str(message or "").casefold()
                if inventory and (
                    "qualitäts-upgrade" in normalized_message
                    or "qualitätsprüfung" in normalized_message
                    or "nicht besser als" in normalized_message
                ):
                    entry[_FAILED_INVENTORY] = inventory
                    entry[_FAILED_INVENTORY_AT] = time.time()
                    _persist_movie_subscriptions_background()


library_router._prepare_movie_subscription_upgrade = _prepare_movie_subscription_upgrade
# source_resolution captured these callbacks before post-service hardening was
# loaded. Patch the actual worker seams, not only the composition-root exports.
source_resolution._movie_subscription_download_finished = _movie_subscription_download_finished
source_resolution._movie_subscription_download_failed = _movie_subscription_download_failed

_SERVICE_EXPORTS = (
    "_movie_subscription_download_finished",
    "_movie_subscription_download_failed",
)
publish_service(globals(), _SERVICE_EXPORTS)
