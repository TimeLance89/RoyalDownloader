import json

import pytest

import storage_move as mover


def _reset_jobs(monkeypatch, tmp_path):
    monkeypatch.setattr(mover, "_MOVE_JOB_PATH", tmp_path / "storage_move_jobs.json")
    with mover._MOVE_JOB_LOCK:
        mover._MOVE_ACTIVE_JOBS.clear()
        mover._MOVE_JOB_HISTORY.clear()


def _plan():
    return {
        "source_root": "series",
        "source_label": "Serien",
        "source_name": "The Show",
        "source_kind": "series",
        "source_path": "/media/series/The Show",
        "size_bytes": 1234,
        "targets": [
            {
                "root": "location:archive",
                "label": "Archiv",
                "path": "/archive",
                "destination": "/archive/The Show",
                "eligible": True,
                "reason": "",
            }
        ],
        "eligible_target_count": 1,
    }


def _create(monkeypatch):
    monkeypatch.setattr(mover, "plan_move_candidate", lambda *args, **kwargs: _plan())
    queued = []
    monkeypatch.setattr(mover, "_enqueue_move_job", lambda job_id, kwargs: queued.append((job_id, kwargs)))
    job = mover.create_move_job(
        {"movies": "/movies", "series": "/series"},
        [{"id": "archive", "label": "Archiv", "path": "/archive", "mode": "media"}],
        root_key="series",
        relative_path="The Show/Season 01/E01.mkv",
        token="signed-secret-that-must-not-be-persisted",
        expected_size=100,
        expires_at=9999999999,
        destination_root="location:archive",
    )
    return job, queued


def test_move_job_is_visible_immediately_and_blocks_duplicate(monkeypatch, tmp_path):
    _reset_jobs(monkeypatch, tmp_path)
    job, queued = _create(monkeypatch)

    snapshot = mover.list_move_jobs()
    assert job["status"] == "queued"
    assert snapshot["active_count"] == 1
    assert snapshot["jobs"][0]["job_id"] == job["job_id"]
    assert snapshot["jobs"][0]["source_name"] == "The Show"
    assert len(queued) == 1

    with pytest.raises(ValueError, match="bereits ein Verschiebe-Job"):
        mover.create_move_job(
            {"movies": "/movies", "series": "/series"},
            [],
            root_key="series",
            relative_path="The Show/Season 02/E02.mkv",
            token="another-token",
            expected_size=100,
            expires_at=9999999999,
            destination_root="location:archive",
        )


def test_move_job_transitions_to_completed_history(monkeypatch, tmp_path):
    _reset_jobs(monkeypatch, tmp_path)
    job, queued = _create(monkeypatch)
    job_id, move_kwargs = queued[0]
    monkeypatch.setattr(
        mover,
        "move_candidate",
        lambda **kwargs: {
            "moved": True,
            "moved_bytes": 1234,
            "destination_path": "/archive/The Show",
        },
    )

    mover._run_move_job(job_id, move_kwargs)

    snapshot = mover.list_move_jobs()
    assert snapshot["active_count"] == 0
    assert snapshot["history"][0]["job_id"] == job["job_id"]
    assert snapshot["history"][0]["status"] == "completed"
    assert snapshot["history"][0]["progress"] == 100.0
    assert snapshot["history"][0]["moved_bytes"] == 1234


def test_move_job_failure_releases_lock_and_keeps_error_history(monkeypatch, tmp_path):
    _reset_jobs(monkeypatch, tmp_path)
    job, queued = _create(monkeypatch)
    job_id, move_kwargs = queued[0]

    def fail(**kwargs):
        raise OSError("Datenträger getrennt")

    monkeypatch.setattr(mover, "move_candidate", fail)
    mover._run_move_job(job_id, move_kwargs)

    snapshot = mover.list_move_jobs()
    assert snapshot["active_count"] == 0
    assert snapshot["history"][0]["job_id"] == job["job_id"]
    assert snapshot["history"][0]["status"] == "failed"
    assert "Datenträger getrennt" in snapshot["history"][0]["error"]


def test_persisted_move_job_never_contains_replay_token(monkeypatch, tmp_path):
    _reset_jobs(monkeypatch, tmp_path)
    _create(monkeypatch)

    persisted = json.loads(mover._MOVE_JOB_PATH.read_text(encoding="utf-8"))
    serialized = json.dumps(persisted)
    assert "signed-secret-that-must-not-be-persisted" not in serialized
    assert persisted["jobs"][0]["status"] == "queued"
    assert persisted["jobs"][0]["candidate_path"] == "The Show/Season 01/E01.mkv"
