"""Reserve disk space before starting a media download."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

import media.downloader as downloader
from media.hoster_intel import HosterIntel

_MIN_FREE_GIB = max(
    0.0,
    min(1024.0, float(os.environ.get("DOWNLOAD_MIN_FREE_GIB", "5") or 5)),
)
_MIN_FREE_BYTES = int(_MIN_FREE_GIB * 1024 * 1024 * 1024)
_ORIGINAL_PREPARE_STAGING = downloader.DownloadJob._prepare_staging
_ORIGINAL_RECORD_DOWNLOAD = HosterIntel.record_download
_ORIGINAL_COMMIT_FILE = downloader.DownloadJob._commit_file


def _existing_ancestor(path: Path) -> Path:
    candidate = Path(path).expanduser()
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def _prepare_staging(self):
    error = _storage_budget_check(self, force=True)
    if error:
        self.failure_kind = "storage"
        return False, error
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


def _same_filesystem(first: Path, second: Path) -> bool:
    return first.stat().st_dev == second.stat().st_dev


def _storage_budget_check(self, *, force=False, publishing_source=None):
    """Check actual destination and staging floors at most every five seconds.

    The legacy mode retains its start guard. Enabled placement also accounts
    for remaining bytes and other jobs sharing the physical volume.
    """
    now = time.monotonic()
    if not force and now - getattr(self, "_royal_budget_checked_at", 0) < 5:
        return ""
    self._royal_budget_checked_at = now
    from application_services.storage_autopilot_runtime import queue_context
    from storage.storage_autopilot import get_autopilot
    from storage.storage_inventory import read_state, transact
    from storage.storage_placement import reserved_by_volume
    from storage.storage_move_runtime import list_move_jobs
    from storage.storage_policy import GIB
    document = read_state()
    if document.get("storage_error"):
        return "Autopilot-Sicherheitsdaten nicht lesbar; Download zurückgestellt."
    if document["policy"]["mode"] not in ("automatic", "full"):
        return ""
    try:
        jobs = queue_context()
        current = get_autopilot(queue_jobs=jobs)
        matches = []
        for root in current["roots"]:
            try:
                self.out_path.absolute().relative_to(Path(root.get("resolved_path") or root["path"]))
                matches.append(root)
            except ValueError:
                continue
        if not matches:
            return "Downloadziel ist kein registrierter Medienpfad."
        root = max(matches, key=lambda root: len(Path(root["path"]).parts))
        if not root.get("available") or not root.get("writable"):
            return "Downloadvolume offline oder nicht beschreibbar."
        reservation = document["reservations"].get(self.job_id, {})
        expected = max(int(self.total_bytes or 0), int(reservation.get("expected_total_bytes", reservation.get("size_bytes", 0))),
                       int(document["policy"]["unknown_download_gib"] * GIB) if not self.total_bytes else 0)
        destination = _existing_ancestor(self.out_path.parent)
        staging = _existing_ancestor(Path(publishing_source).parent if publishing_source else self.staging_dir.parent)
        same_disk = _same_filesystem(destination, staging)
        if publishing_source:
            # Validated media has a known exact size. Same-volume publication
            # needs no second copy; fallback staging needs the entire target size.
            expected = Path(publishing_source).stat().st_size
            remaining = 0 if same_disk else expected
        else:
            # Bytes on another staging disk have not consumed destination space.
            remaining = max(0, expected - int(self.downloaded_bytes or 0)) if same_disk else expected
        budgets = reserved_by_volume(document, current["roots"], jobs, list_move_jobs()["jobs"], exclude=self.job_id)
        floor = max(_MIN_FREE_BYTES, int(root["policy"]["reserve_gib"] * GIB))
        free = int(shutil.disk_usage(destination).free)
        if free - remaining - budgets.get(root.get("volume_id"), 0) < floor:
            return "Speicherreserve einschließlich geplanter Downloads nicht mehr gewährleistet."
        if not publishing_source and int(shutil.disk_usage(staging).free) < _MIN_FREE_BYTES:
            return "Freie Staging-Reserve unterschritten."
        if reservation and (reservation["size_bytes"] != remaining or reservation.get("expected_total_bytes") != expected):
            def update(state):
                live = state["reservations"].get(self.job_id)
                if live:
                    live.update(size_bytes=remaining, expected_total_bytes=expected)
            transact(update)
    except (OSError, ValueError):
        return "Speicherreserve momentan nicht zuverlässig prüfbar."
    return ""


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


def _commit_file(self, source, target):
    error = _storage_budget_check(self, force=True, publishing_source=source)
    if error:
        self.failure_kind = "storage"
        raise OSError(error)
    result = _ORIGINAL_COMMIT_FILE(self, source, target)
    from application_services.storage_autopilot_runtime import record_publication
    try:
        record_publication(self, result)
    except Exception:
        # Inventory is optional metadata; verified publication remains valid.
        pass
    return result


if not getattr(downloader.DownloadJob, "_royal_storage_guard_patched", False):
    downloader.DownloadJob._prepare_staging = _prepare_staging
    downloader.DownloadJob._commit_file = _commit_file
    downloader.DownloadJob._storage_budget_check = _storage_budget_check
    downloader.DownloadJob._royal_storage_guard_patched = True

if not getattr(HosterIntel, "_royal_storage_guard_patched", False):
    HosterIntel.record_download = _record_download
    HosterIntel._royal_storage_guard_patched = True
