from core.personal_requests import PersonalRequestStore
from core.queue_jobs import new_job, normalize_document


def _job(job_id: str, slug: str, *, status: str = "queued", created_at: float = 10.0):
    job = new_job(slug, job_id=job_id, title=slug.title(), created_at=created_at)
    job["status"] = status
    job["requested_by_user_id"] = "user-a"
    return job


def test_personal_request_survives_queue_cleanup_and_restart(tmp_path):
    path = tmp_path / "personal_requests.json"
    store = PersonalRequestStore(path, clock=lambda: 100.0)
    job = _job("request-1", "dune", created_at=20.0)

    created = store.record("user-a", job, source="detail")
    assert created and created["status"] == "queued"
    job.update(status="completed", completed_at=30.0)
    assert store.update_from_job(job)

    # Queue state may now be empty; durable history reloads independently.
    recovered = PersonalRequestStore(path, clock=lambda: 101.0)
    recent = recovered.recent_for_user("user-a")
    assert recovered.count_for_user("user-a") == 1
    assert recent[0]["title"] == "Dune"
    assert recent[0]["status"] == "completed"
    assert recent[0]["requested_at"] == 20.0


def test_personal_requests_are_isolated_and_a_retry_does_not_duplicate(tmp_path):
    store = PersonalRequestStore(tmp_path / "personal_requests.json", clock=lambda: 100.0)
    job_a = _job("request-a", "dune")
    job_b = _job("request-b", "interstellar", created_at=11.0)

    first = store.record("user-a", job_a, source="search")
    retried = store.record("user-a", {**job_a, "status": "queued"}, source="search")
    store.record("user-b", job_b, source="recommendation")

    assert first["id"] == retried["id"]
    assert [item["media_key"] for item in store.recent_for_user("user-a")] == ["dune"]
    assert [item["media_key"] for item in store.recent_for_user("user-b")] == ["interstellar"]


def test_personal_request_keeps_failed_status_and_queue_owner_round_trips():
    job = _job("request-1", "dune")
    job["request_source"] = "web"
    document, _ = normalize_document({"schema_version": 3, "jobs": [job], "history": []})

    assert document["jobs"][0]["requested_by_user_id"] == "user-a"
    assert document["jobs"][0]["request_source"] == "web"


def test_backfill_only_imports_historical_requests_with_a_manual_source(tmp_path):
    store = PersonalRequestStore(tmp_path / "personal_requests.json", clock=lambda: 100.0)
    manual = _job("request-manual", "dune")
    manual["request_source"] = "web"
    subscription = _job("request-subscription", "show-s01e01")
    subscription["request_source"] = "subscription"

    store.backfill([manual, subscription])

    assert [item["media_key"] for item in store.recent_for_user("user-a")] == ["dune"]


def test_legacy_failed_episode_request_is_available_for_one_time_recovery(tmp_path):
    path = tmp_path / "personal_requests.json"
    path.write_text(
        """{
  "schema_version": 1,
  "requests": [{
    "id": "legacy-request",
    "user_id": "user-a",
    "job_id": "legacy-job",
    "media_key": "serienstream:sailor-moon-s04e19",
    "media_type": "series",
    "title": "Sailor Moon S04E19",
    "request_source": "web",
    "status": "failed",
    "requested_at": 10,
    "failed_at": 20,
    "updated_at": 20
  }]
}""",
        encoding="utf-8",
    )

    store = PersonalRequestStore(path, clock=lambda: 100.0)

    candidates = store.legacy_failed_episode_requests()
    assert [item["job_id"] for item in candidates] == ["legacy-job"]
    assert candidates[0]["source_retry_generation"] == 0

    modern_job = _job(
        "legacy-job", "serienstream:sailor-moon-s04e19", status="queued",
    )
    modern_job["source_retry_count"] = 0
    modern_job["wait_reason"] = ""
    assert store.update_from_job(modern_job)

    assert store.legacy_failed_episode_requests() == []
    assert store.recent_for_user("user-a")[0]["source_retry_generation"] == 1


def test_new_failed_episode_request_is_not_treated_as_legacy(tmp_path):
    store = PersonalRequestStore(tmp_path / "personal_requests.json", clock=lambda: 100.0)
    job = _job(
        "modern-job", "serienstream:sailor-moon-s04e20", status="failed",
    )
    job["completed_at"] = 50.0

    created = store.record("user-a", job, source="web")

    assert created["source_retry_generation"] == 1
    assert store.legacy_failed_episode_requests() == []
