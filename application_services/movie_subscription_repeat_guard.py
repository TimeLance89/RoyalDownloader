"""Prevent subscribed movies from repeatedly downloading the same false upgrade.

Provider quality labels are only an advertisement.  When a source claims a higher
resolution but the committed file is measured at the same or a lower resolution,
remember the exact source/hoster candidate set and skip it until that candidate
actually changes.  This keeps automatic subscriptions useful without turning a
persistently mislabelled provider entry into an endless download loop.
"""

from __future__ import annotations

import hashlib
import json
import time

import api_library_router as library_router
from application_services.runtime import (
    backend_value,
    import_backend_namespace,
    publish_service,
)

# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

globals().update(import_backend_namespace())

_ORIGINAL_PREPARE_MOVIE_SUBSCRIPTION_UPGRADE = backend_value(
    "_prepare_movie_subscription_upgrade"
)
_ORIGINAL_MOVIE_SUBSCRIPTION_FINISHED = backend_value(
    "_movie_subscription_download_finished"
)

_MAX_REJECTED_CANDIDATES = 24
_CANDIDATE_SIGNATURE_FIELD = "_upgrade_candidate_signature"
_CANDIDATE_FROM_RANK_FIELD = "_upgrade_candidate_from_rank"
_CANDIDATE_ADVERTISED_RANK_FIELD = "_upgrade_candidate_advertised_rank"
_REJECTED_CANDIDATES_FIELD = "upgrade_rejected_candidates"


def _safe_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _candidate_signature(source, current_rank: int, target: str) -> str:
    """Hash one currently eligible source without persisting provider URLs."""
    ceiling = MOVIE_QUALITY_TARGETS[normalize_movie_quality(target)]
    hosters = []
    for hoster in list(getattr(source, "hosters", []) or []):
        rank = movie_quality_rank(getattr(hoster, "quality", ""))
        if not (current_rank < rank <= ceiling):
            continue
        hoster_url = str(getattr(hoster, "url", "") or "").strip()
        if not hoster_url:
            continue
        hosters.append(
            (
                hoster_url,
                rank,
                str(getattr(hoster, "quality", "") or "").strip().casefold(),
            )
        )
    if not hosters:
        return ""
    payload = {
        "source": str(getattr(source, "url", "") or "").strip(),
        "hosters": sorted(hosters),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rejection_blocks(entry: dict, signature: str, current_rank: int) -> bool:
    rejected = entry.get(_REJECTED_CANDIDATES_FIELD)
    if not signature or not isinstance(rejected, dict):
        return False
    record = rejected.get(signature)
    if not isinstance(record, dict):
        return False
    observed_rank = _safe_int(record.get("observed_rank"))
    # If the library quality later drops below what this candidate actually
    # delivered, it can become a real upgrade again and must be allowed.
    return observed_rank > 0 and observed_rank <= current_rank


def _clear_candidate_fields(entry: dict) -> None:
    entry.pop(_CANDIDATE_SIGNATURE_FIELD, None)
    entry.pop(_CANDIDATE_FROM_RANK_FIELD, None)
    entry.pop(_CANDIDATE_ADVERTISED_RANK_FIELD, None)


def _prepare_movie_subscription_upgrade(entry: dict, sources: list):
    """Exclude source groups already proven not to improve the current file."""
    current_rank = _safe_int(entry.get("current_quality_rank"))
    target = normalize_movie_quality(entry.get("target_quality"))
    filtered_sources = []
    for source in sources:
        signature = _candidate_signature(source, current_rank, target)
        if signature and _rejection_blocks(entry, signature, current_rank):
            continue
        filtered_sources.append(source)

    primary, fallbacks, rank, label = _ORIGINAL_PREPARE_MOVIE_SUBSCRIPTION_UPGRADE(
        entry,
        filtered_sources,
    )
    if primary is None:
        _clear_candidate_fields(entry)
        return primary, fallbacks, rank, label

    signature = _candidate_signature(primary, current_rank, target)
    if signature:
        entry[_CANDIDATE_SIGNATURE_FIELD] = signature
        entry[_CANDIDATE_FROM_RANK_FIELD] = current_rank
        entry[_CANDIDATE_ADVERTISED_RANK_FIELD] = _safe_int(rank)
    else:
        _clear_candidate_fields(entry)
    return primary, fallbacks, rank, label


def _record_rejected_candidate(
    entry: dict,
    signature: str,
    *,
    from_rank: int,
    advertised_rank: int,
    observed_rank: int,
) -> None:
    raw = entry.get(_REJECTED_CANDIDATES_FIELD)
    rejected = dict(raw) if isinstance(raw, dict) else {}
    rejected[signature] = {
        "from_rank": _safe_int(from_rank),
        "advertised_rank": _safe_int(advertised_rank),
        "observed_rank": _safe_int(observed_rank),
        "recorded_at": time.time(),
    }
    if len(rejected) > _MAX_REJECTED_CANDIDATES:
        ordered = sorted(
            rejected.items(),
            key=lambda item: float((item[1] or {}).get("recorded_at") or 0.0),
            reverse=True,
        )
        rejected = dict(ordered[:_MAX_REJECTED_CANDIDATES])
    entry[_REJECTED_CANDIDATES_FIELD] = rejected


def _movie_subscription_download_finished(movie_slug, out_path, quality) -> None:
    """Remember a candidate only when ffprobe proves it was not an upgrade."""
    subscription = None
    signature = ""
    from_rank = 0
    advertised_rank = 0
    observed_at_before = 0.0
    with state.movie_subscriptions_lock:
        subscription = next(
            (
                entry
                for entry in state.movie_subscriptions
                if entry.get("pending_slug") == movie_slug
                or entry.get("source_slug") == movie_slug
            ),
            None,
        )
        if subscription is not None:
            signature = str(subscription.get(_CANDIDATE_SIGNATURE_FIELD) or "")
            from_rank = _safe_int(subscription.get(_CANDIDATE_FROM_RANK_FIELD))
            advertised_rank = _safe_int(
                subscription.get(_CANDIDATE_ADVERTISED_RANK_FIELD)
            )
            try:
                observed_at_before = float(
                    subscription.get("quality_observed_at") or 0.0
                )
            except (TypeError, ValueError):
                observed_at_before = 0.0

    _ORIGINAL_MOVIE_SUBSCRIPTION_FINISHED(movie_slug, out_path, quality)

    if subscription is None:
        return

    rejected_now = False
    changed = False
    with state.movie_subscriptions_lock:
        if not any(current is subscription for current in state.movie_subscriptions):
            return
        observed_rank = _safe_int(subscription.get("current_quality_rank"))
        try:
            observed_at_after = float(subscription.get("quality_observed_at") or 0.0)
        except (TypeError, ValueError):
            observed_at_after = 0.0
        observed_by_probe_now = (
            str(subscription.get("quality_source") or "") == "ffprobe"
            and observed_at_after > observed_at_before
        )
        if (
            signature
            and advertised_rank > from_rank
            and observed_by_probe_now
            and observed_rank > 0
            and observed_rank <= from_rank
        ):
            _record_rejected_candidate(
                subscription,
                signature,
                from_rank=from_rank,
                advertised_rank=advertised_rank,
                observed_rank=observed_rank,
            )
            rejected_now = True
            changed = True
        if any(
            field in subscription
            for field in (
                _CANDIDATE_SIGNATURE_FIELD,
                _CANDIDATE_FROM_RANK_FIELD,
                _CANDIDATE_ADVERTISED_RANK_FIELD,
            )
        ):
            _clear_candidate_fields(subscription)
            changed = True

    if rejected_now:
        log(
            "Film-Abo: vermeintliches Qualitäts-Upgrade lieferte keine bessere "
            "Auflösung; diese unveränderte Quelle wird künftig übersprungen.",
            "warn",
        )
    if changed:
        _persist_movie_subscriptions_background()


# The original library-router checker resolves this helper in its own module
# namespace.  Patch that local seam as well as the composition-root service so
# both API checks and background checks use the same guard.
library_router._prepare_movie_subscription_upgrade = _prepare_movie_subscription_upgrade


_SERVICE_EXPORTS = (
    "_prepare_movie_subscription_upgrade",
    "_movie_subscription_download_finished",
)
publish_service(globals(), _SERVICE_EXPORTS)
