"""Large-queue resilience without network downloads or external provider calls."""

from __future__ import annotations

import concurrent.futures
import json

from core.queue_jobs import (
    HISTORY_LIMIT, SCHEMA_VERSION, atomic_save, load_document,
    new_job, normalize_document,
)
from media.downloader import DownloadQueue


class _QueuedOnly:
    """Cheap stand-in for a physical job; intentionally never started."""

    is_preparation_job = False
    host_group = "cdn.invalid"
    queue_priority = 100

    def __init__(self, ordinal: int):
        self.ordinal = ordinal

    def cancel(self):
        return None


def test_parallel_queue_producers_preserve_all_eight_hundred_claims():
    queue = DownloadQueue(max_parallel=3, per_host_limit=1)

    def add_range(start: int):
        for ordinal in range(start, start + 100):
            queue.add(_QueuedOnly(ordinal))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(add_range, range(0, 800, 100)))

    jobs = queue.pending_jobs()
    assert queue.pending_count() == 800
    assert {job.ordinal for job in jobs} == set(range(800))
    assert queue.active_count() == 0

    queue.cancel_all()
    assert queue.pending_count() == 0
    assert queue.active_count() == 0


def test_650_queue_jobs_preserve_identity_and_retry_backoff_across_restart(tmp_path):
    path = tmp_path / "download_queue.json"
    jobs = []
    expected_ids = {}
    expected_attempts = {}
    for i in range(650):
        slug = f"provider:show-s01e{i + 1:04d}"
        job = new_job(slug, job_id=f"job-{i:04d}")
        job["attempt_id"] = f"attempt-{i:04d}"
        job["status"] = ("preparing", "downloading", "waiting_provider", "queued")[i % 4]
        job["source_retry_count"] = i % 11
        job["next_retry_at"] = float(i + 10) if i % 4 == 2 else 0.0
        expected_ids[slug] = job["job_id"]
        expected_attempts[slug] = job["attempt_id"]
        jobs.append(job)

    record = {
        "schema_version": SCHEMA_VERSION, "revision": 29, "jobs": jobs, "history": [],
    }
    atomic_save(path, record)
    restored, migrated = load_document(path)
    assert migrated is False
    assert len(restored["jobs"]) == 650
    assert restored["revision"] == 29
    for i, job in enumerate(restored["jobs"]):
        slug = job["slug"]
        assert job["job_id"] == expected_ids[slug]
        assert job["attempt_id"] == expected_attempts[slug]
        assert job["status"] == (
            "queued" if i % 4 in {0, 1} else ("waiting_provider" if i % 4 == 2 else "queued")
        )
        assert job["source_retry_count"] == i % 11
        if i % 4 == 2:
            assert job["next_retry_at"] == float(i + 10)


def test_recovery_deduplicates_650_claims_by_slug_and_job_id():
    items = []
    for i in range(650):
        job = new_job(f"movie:{i:04d}", job_id=f"job-{i:04d}")
        items.append(job)
    # Repeated requests from different frontends/integrations must collapse.
    repeated = [dict(items[i], job_id=f"conflicting-{i}") for i in range(40)]
    other_slug_same_id = dict(items[90], slug="movie:impostor")
    record = {
        "schema_version": SCHEMA_VERSION, "jobs": items + repeated + [other_slug_same_id],
        "history": [],
    }
    normalized, _ = normalize_document(record)
    assert len(normalized["jobs"]) == 650
    assert {job["slug"] for job in normalized["jobs"]} == {x["slug"] for x in items}
    assert {job["job_id"] for job in normalized["jobs"]} == {x["job_id"] for x in items}


def test_history_is_bounded_when_650_jobs_complete():
    history = []
    for index in range(650):
        job = new_job(f"movie:{index:04d}", job_id=f"done-{index}")
        job.update(status="completed", completed_at=float(index + 1))
        history.append(job)
    document, _ = normalize_document({
        "schema_version": SCHEMA_VERSION, "jobs": [], "history": history,
    })
    assert len(document["history"]) == HISTORY_LIMIT
    assert document["history"][0]["job_id"] == "done-649"
    assert document["history"][-1]["job_id"] == "done-150"
