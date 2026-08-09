"""Final staging guard for measured movie-subscription upgrades.

A probed stream is only a promise.  This layer independently measures the fully
downloaded staging file, rejects equal/worse results before commit, and forwards
the actual collision-safe committed path to queue history and subscription
cleanup.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from application_services.runtime import backend_value, import_backend_namespace, publish_service
import application_services.source_resolution as source_resolution
from downloader import DownloadJob
from hoster_intel import HosterIntel
from media_quality import (
    media_profile_complete,
    media_profile_is_better,
    media_profile_label,
    normalize_media_profile,
    probe_media_profile,
)

# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

globals().update(import_backend_namespace())

_BASELINE_FIELD = "upgrade_probe_baseline_profile"
_AVAILABLE_PROFILE_FIELD = "upgrade_available_profile"
_ORIGINAL_MOVIE_SUBSCRIPTION_FINISHED = backend_value("_movie_subscription_download_finished")
_ORIGINAL_MOVIE_SUBSCRIPTION_FAILED = backend_value("_movie_subscription_download_failed")
_ORIGINAL_ON_JOB_DONE = backend_value("on_job_done")

_committed_paths: dict[str, Path] = {}
_committed_profiles: dict[str, dict] = {}
_commit_lock = threading.RLock()


def _subscription_baseline_for_slug(slug: str) -> dict:
    if not slug:
        return {}
    with state.movie_subscriptions_lock:
        for entry in state.movie_subscriptions:
            if entry.get("pending_slug") != slug:
                continue
            baseline = normalize_media_profile(entry.get(_BASELINE_FIELD))
            return baseline if baseline.get("height") else {}
    return {}


def _patch_download_job() -> None:
    if getattr(DownloadJob, "_royal_stream_quality_patched", False):
        return
    original_init = DownloadJob.__init__
    original_validate = DownloadJob._validate_media
    original_commit = DownloadJob._commit_file

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        baseline = _subscription_baseline_for_slug(str(self.queue_slug or ""))
        self._subscription_quality_baseline = baseline
        self._subscription_quality_actual = {}
        self.final_path = None

    def validate(self, path: Path):
        valid, message = original_validate(self, path)
        if not valid:
            return valid, message
        baseline = normalize_media_profile(
            getattr(self, "_subscription_quality_baseline", {})
        )
        if not baseline.get("height"):
            return True, message
        profile, error = probe_media_profile(path)
        if error or not media_profile_complete(profile):
            self.failure_kind = "quality"
            return False, f"Qualitätsprüfung fehlgeschlagen: {error or 'unvollständiges Profil'}"
        if not media_profile_is_better(profile, baseline):
            self.failure_kind = "quality"
            return False, (
                "Kein tatsächliches Qualitäts-Upgrade: "
                f"{media_profile_label(profile)} ist nicht besser als "
                f"{media_profile_label(baseline)}"
            )
        self._subscription_quality_actual = normalize_media_profile(profile)
        return True, f"{message}; Qualitäts-Upgrade {media_profile_label(profile)} bestätigt"

    def commit(self, source: Path, target: Path):
        committed = original_commit(self, source, target)
        self.final_path = committed
        slug = str(self.queue_slug or "")
        if slug:
            with _commit_lock:
                _committed_paths[slug] = Path(committed)
                profile = normalize_media_profile(
                    getattr(self, "_subscription_quality_actual", {})
                )
                if profile.get("height"):
                    _committed_profiles[slug] = profile
        return committed

    DownloadJob.__init__ = init
    DownloadJob._validate_media = validate
    DownloadJob._commit_file = commit
    DownloadJob._royal_stream_quality_patched = True


def _patch_hoster_intel() -> None:
    if getattr(HosterIntel, "_royal_stream_quality_patched", False):
        return
    original = HosterIntel.record_download

    def record_download(self, url, ok, hoster_name="", speed_bps=0, failure_kind=""):
        if not ok and str(failure_kind or "") == "quality":
            # Transport and media validity succeeded; only the subscription's
            # upgrade threshold was not met.  Do not teach hoster health that
            # this is a broken hoster.
            return original(
                self,
                url,
                True,
                hoster_name=hoster_name,
                speed_bps=speed_bps,
                failure_kind="",
            )
        return original(
            self,
            url,
            ok,
            hoster_name=hoster_name,
            speed_bps=speed_bps,
            failure_kind=failure_kind,
        )

    HosterIntel.record_download = record_download
    HosterIntel._royal_stream_quality_patched = True


def on_job_done(ok, msg, label, out_path, hoster_url="", slug="", job_id="", attempt_id=""):
    actual_path = Path(out_path)
    if ok and slug:
        with _commit_lock:
            actual_path = Path(_committed_paths.get(slug, actual_path))
    return _ORIGINAL_ON_JOB_DONE(
        ok,
        msg,
        label,
        actual_path,
        hoster_url=hoster_url,
        slug=slug,
        job_id=job_id,
        attempt_id=attempt_id,
    )


def _movie_subscription_download_finished(movie_slug, out_path, quality) -> None:
    with _commit_lock:
        actual_path = Path(_committed_paths.get(movie_slug, Path(out_path)))
        measured = normalize_media_profile(_committed_profiles.get(movie_slug))
    if not measured.get("height"):
        measured, _error = probe_media_profile(actual_path)
    measured = normalize_media_profile(measured)
    effective_quality = media_profile_label(measured) if measured.get("height") else quality

    _ORIGINAL_MOVIE_SUBSCRIPTION_FINISHED(movie_slug, actual_path, effective_quality)

    changed = False
    with state.movie_subscriptions_lock:
        for entry in state.movie_subscriptions:
            if (
                entry.get("source_slug") != movie_slug
                and entry.get("key") != movie_slug
                and str(entry.get("existing_path") or "") != str(actual_path)
            ):
                continue
            entry["existing_path"] = str(actual_path)
            if measured.get("height"):
                entry["current_media_profile"] = measured
                entry["current_quality_rank"] = int(measured["height"])
                entry["current_quality"] = media_profile_label(measured)
                entry["quality_source"] = "ffprobe"
                entry["quality_observed_at"] = time.time()
            entry.pop(_BASELINE_FIELD, None)
            entry.pop(_AVAILABLE_PROFILE_FIELD, None)
            changed = True
            break
    if changed:
        _persist_movie_subscriptions_background()
    with _commit_lock:
        _committed_paths.pop(movie_slug, None)
        _committed_profiles.pop(movie_slug, None)


def _movie_subscription_download_failed(movie_slug: str, message: str) -> None:
    try:
        _ORIGINAL_MOVIE_SUBSCRIPTION_FAILED(movie_slug, message)
    finally:
        with state.movie_subscriptions_lock:
            for entry in state.movie_subscriptions:
                if entry.get("source_slug") == movie_slug or entry.get("key") == movie_slug:
                    entry.pop(_BASELINE_FIELD, None)
        with _commit_lock:
            _committed_paths.pop(movie_slug, None)
            _committed_profiles.pop(movie_slug, None)


_patch_download_job()
_patch_hoster_intel()
source_resolution.on_job_done = on_job_done

_SERVICE_EXPORTS = (
    "on_job_done",
    "_movie_subscription_download_finished",
    "_movie_subscription_download_failed",
)
publish_service(globals(), _SERVICE_EXPORTS)
