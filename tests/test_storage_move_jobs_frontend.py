from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_storage_move_job_runtime_is_loaded_after_storage_manager():
    api_js = (ROOT / "web" / "api.js").read_text(encoding="utf-8")
    assert "/storage-move-jobs.js?v=royal-20260817-1" in api_js
    assert "data-royal-storage-move-jobs" in api_js
    assert "loadRoyalStorageMoveJobs" in api_js


def test_storage_move_jobs_are_visible_and_lock_conflicting_actions():
    source = (ROOT / "web" / "storage-move-jobs.js").read_text(encoding="utf-8")
    for marker in (
        'id="storage-move-job-list"',
        'id="storage-move-job-count"',
        "/api/storage/move/jobs",
        "Läuft im Hintergrund",
        "Verschieben wartet",
        "Wird verschoben",
        "data-storage-cleanup",
        "data-storage-move",
        "matchingActiveJob",
        "syncMoveLocks",
    ):
        assert marker in source


def test_storage_move_job_progress_is_indeterminate_while_copying():
    source = (ROOT / "web" / "storage-move-jobs.js").read_text(encoding="utf-8")
    assert "royalStorageMoveJob" in source
    assert "is-active .storage-move-job-bar i" in source
    assert "Läuft im Hintergrund" in source
    assert "100%" not in source
