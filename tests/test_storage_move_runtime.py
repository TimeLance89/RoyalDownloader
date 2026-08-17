import json
import time
from pathlib import Path

import storage_move_runtime as runtime


def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "JOB_PATH", tmp_path / "storage_move_jobs.json")
    monkeypatch.setattr(runtime, "_same_volume", lambda source, target: False)
    monkeypatch.setattr(runtime, "_enqueue", lambda job_id: None)
    with runtime._LOCK:
        runtime._ACTIVE.clear()
        runtime._HISTORY.clear()


def _movie_plan(source: Path, target: Path):
    return {
        "source_root": "movies",
        "source_label": "Filme",
        "source_name": source.name,
        "source_kind": "movie",
        "source_path": str(source),
        "size_bytes": source.stat().st_size,
        "targets": [
            {
                "root": "location:archive",
                "label": "Archiv",
                "path": str(target),
                "destination": str(target / source.name),
                "eligible": True,
                "reason": "",
            }
        ],
        "eligible_target_count": 1,
    }


def _series_plan(source: Path, target: Path):
    size = sum(path.stat().st_size for path in source.rglob("*") if path.is_file())
    return {
        "source_root": "series",
        "source_label": "Serien",
        "source_name": source.name,
        "source_kind": "series",
        "source_path": str(source),
        "size_bytes": size,
        "targets": [
            {
                "root": "location:archive",
                "label": "Archiv",
                "path": str(target),
                "destination": str(target / source.name),
                "eligible": True,
                "reason": "",
            }
        ],
        "eligible_target_count": 1,
    }


def _create_job(monkeypatch, plan):
    monkeypatch.setattr(runtime, "plan_move_candidate", lambda *args, **kwargs: plan)
    return runtime.create_move_job(
        {"movies": "/movies", "series": "/series"},
        [],
        root_key=plan["source_root"],
        relative_path=plan["source_name"],
        token="signed-secret-that-must-not-be-persisted",
        expected_size=plan["size_bytes"],
        expires_at=9999999999,
        destination_root="location:archive",
    )


def test_move_job_persists_resume_descriptor_but_never_scan_token(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    source_dir = tmp_path / "movies"; source_dir.mkdir()
    target = tmp_path / "target"; target.mkdir()
    source = source_dir / "Movie.mkv"
    source.write_bytes(b"x" * 1024)

    job = _create_job(monkeypatch, _movie_plan(source, target))
    persisted = json.loads(runtime.JOB_PATH.read_text(encoding="utf-8"))
    serialized = json.dumps(persisted)

    assert persisted["schema_version"] == 2
    assert "signed-secret-that-must-not-be-persisted" not in serialized
    assert persisted["jobs"][0]["job_id"] == job["job_id"]
    assert persisted["jobs"][0]["resume"]["work_path"].endswith(".partial")
    public = runtime.list_move_jobs()["jobs"][0]
    assert "resume" not in public
    assert "work_path" not in public


def test_movie_transfer_resumes_existing_partial_bytes(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    source_dir = tmp_path / "movies"; source_dir.mkdir()
    target = tmp_path / "target"; target.mkdir()
    source = source_dir / "Movie.mkv"
    payload = bytes(range(256)) * 16
    source.write_bytes(payload)

    job = _create_job(monkeypatch, _movie_plan(source, target))
    with runtime._LOCK:
        work = Path(runtime._ACTIVE[job["job_id"]]["_resume"]["work_path"])
    work.write_bytes(payload[:777])

    runtime._run(job["job_id"])

    assert not source.exists()
    assert (target / "Movie.mkv").read_bytes() == payload
    snapshot = runtime.list_move_jobs()
    assert snapshot["active_count"] == 0
    assert snapshot["history"][0]["status"] == "completed"
    assert snapshot["history"][0]["progress"] == 100.0


def test_v2_job_is_revived_after_restart_and_keeps_partial_progress(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    source_dir = tmp_path / "movies"; source_dir.mkdir()
    target = tmp_path / "target"; target.mkdir()
    source = source_dir / "Movie.mkv"
    payload = b"resume-me" * 400
    source.write_bytes(payload)

    job = _create_job(monkeypatch, _movie_plan(source, target))
    persisted = json.loads(runtime.JOB_PATH.read_text(encoding="utf-8"))
    entry = persisted["jobs"][0]
    work = Path(entry["resume"]["work_path"])
    work.write_bytes(payload[:900])

    # storage_move.py from an older build converts an interrupted active job to
    # failed history before this v2 runtime is imported.  The resume descriptor
    # survives that conversion and must be revived instead of shown as failed.
    entry["status"] = "failed"
    entry["error"] = runtime.RESTART_ERROR
    entry["completed_at"] = time.time()
    runtime.JOB_PATH.write_text(json.dumps({
        "schema_version": 1,
        "jobs": [],
        "history": [entry],
    }), encoding="utf-8")
    with runtime._LOCK:
        runtime._ACTIVE.clear()
        runtime._HISTORY.clear()
    enqueued = []
    monkeypatch.setattr(runtime, "_enqueue", lambda job_id: enqueued.append(job_id))

    runtime._recover()

    snapshot = runtime.list_move_jobs()
    assert snapshot["active_count"] == 1
    assert snapshot["jobs"][0]["status"] == "queued"
    assert snapshot["jobs"][0]["recovered_after_restart"] is True
    assert snapshot["jobs"][0]["moved_bytes"] >= 900
    assert enqueued == [job["job_id"]]

    runtime._run(job["job_id"])
    assert not source.exists()
    assert (target / "Movie.mkv").read_bytes() == payload
    assert runtime.list_move_jobs()["history"][0]["status"] == "completed"


def test_legacy_interrupted_series_partial_is_adopted_and_completed(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    source_root = tmp_path / "series"; source_root.mkdir()
    target = tmp_path / "target"; target.mkdir()
    source = source_root / "American Horror Story"
    source.mkdir()
    first = b"a" * 1200
    second = b"b" * 1800
    (source / "E01.mkv").write_bytes(first)
    (source / "E02.mkv").write_bytes(second)
    plan = _series_plan(source, target)

    old_work = target / ".royal-move-old-random.partial"
    old_work.mkdir()
    (old_work / "E01.mkv").write_bytes(first)
    (old_work / "E02.mkv").write_bytes(second[:500])
    now = time.time()
    old_job = {
        "job_id": "legacy-series-job",
        "operation": "move",
        "status": "failed",
        "source_root": "series",
        "source_label": "Serien",
        "source_path": str(source),
        "source_name": source.name,
        "source_kind": "series",
        "candidate_path": "American Horror Story/E01.mkv",
        "size_bytes": plan["size_bytes"],
        "destination_root": "location:archive",
        "destination_label": "Archiv",
        "destination_path": str(target / source.name),
        "created_at": now - 60,
        "started_at": now - 50,
        "completed_at": now,
        "progress": 0.0,
        "moved_bytes": 0,
        "error": runtime.RESTART_ERROR,
    }
    runtime.JOB_PATH.write_text(json.dumps({
        "schema_version": 1,
        "jobs": [],
        "history": [old_job],
    }), encoding="utf-8")
    enqueued = []
    monkeypatch.setattr(runtime, "_enqueue", lambda job_id: enqueued.append(job_id))

    runtime._recover()

    snapshot = runtime.list_move_jobs()
    assert snapshot["active_count"] == 1
    assert snapshot["jobs"][0]["job_id"] == "legacy-series-job"
    assert snapshot["jobs"][0]["recovered_after_restart"] is True
    assert snapshot["jobs"][0]["moved_bytes"] == len(first) + 500
    assert enqueued == ["legacy-series-job"]

    runtime._run("legacy-series-job")

    destination = target / source.name
    assert not source.exists()
    assert (destination / "E01.mkv").read_bytes() == first
    assert (destination / "E02.mkv").read_bytes() == second
    history = runtime.list_move_jobs()["history"]
    assert history[0]["job_id"] == "legacy-series-job"
    assert history[0]["status"] == "completed"


def test_source_change_aborts_before_source_is_deleted(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path)
    source_dir = tmp_path / "movies"; source_dir.mkdir()
    target = tmp_path / "target"; target.mkdir()
    source = source_dir / "Movie.mkv"
    source.write_bytes(b"a" * 1024)
    job = _create_job(monkeypatch, _movie_plan(source, target))

    source.write_bytes(b"b" * 1025)
    runtime._run(job["job_id"])

    assert source.exists()
    assert not (target / "Movie.mkv").exists()
    history = runtime.list_move_jobs()["history"]
    assert history[0]["status"] == "failed"
    assert "verändert" in history[0]["error"]
