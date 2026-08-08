"""Reserve disk space before starting a media download."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import downloader
from hoster_intel import HosterIntel

_MIN_FREE_GIB = max(
    0.0,
    min(1024.0, float(os.environ.get("DOWNLOAD_MIN_FREE_GIB", "5") or 5)),
)
_MIN_FREE_BYTES = int(_MIN_FREE_GIB * 1024 * 1024 * 1024)
_ORIGINAL_PREPARE_STAGING = downloader.DownloadJob._prepare_staging
_ORIGINAL_RECORD_DOWNLOAD = HosterIntel.record_download


def _existing_ancestor(path: Path) -> Path:
    candidate = Path(path).expanduser()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _prepare_staging(self):
    if _MIN_FREE_BYTES > 0:
        root = _existing_ancestor(self.out_path.parent)
        try:
            free = int(shutil.disk_usage(root).free)
        except OSError:
            free = -1
        if 0 <= free < _MIN_FREE_BYTES:
            self.failure_kind = "storage"
            gib = free / (1024 ** 3)
            return False, (
                "Nicht genügend freier Speicherplatz: "
                f"{gib:.1f} GiB frei, mindestens {_MIN_FREE_GIB:g} GiB Reserve erforderlich"
            )
    return _ORIGINAL_PREPARE_STAGING(self)


def _record_download(self, url, ok, hoster_name="", speed_bps=0, failure_kind=""):
    if not ok and str(failure_kind or "") == "storage":
        # A full destination filesystem says nothing about hoster reliability.
        return _ORIGINAL_RECORD_DOWNLOAD(
            self,
            url,
            True,
            hoster_name=hoster_name,
            speed_bps=speed_bps,
            failure_kind="",
        )
    return _ORIGINAL_RECORD_DOWNLOAD(
        self,
        url,
        ok,
        hoster_name=hoster_name,
        speed_bps=speed_bps,
        failure_kind=failure_kind,
    )


if not getattr(downloader.DownloadJob, "_royal_storage_guard_patched", False):
    downloader.DownloadJob._prepare_staging = _prepare_staging
    downloader.DownloadJob._royal_storage_guard_patched = True

if not getattr(HosterIntel, "_royal_storage_guard_patched", False):
    HosterIntel.record_download = _record_download
    HosterIntel._royal_storage_guard_patched = True
