from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_storage_move_job_runtime_is_loaded_after_storage_manager():
    adapter = (ROOT / "web/js/features/storage/index.js").read_text(encoding="utf-8")
    assert 'import { createStorageJobs } from "./jobs.js"' in adapter
    assert "bindView(); jobs.mount();" in adapter
    assert "jobs.accept(result.job)" in adapter



def test_storage_move_jobs_are_visible_and_lock_conflicting_actions():
    source = (ROOT / "web/js/features/storage/jobs.js").read_text(encoding="utf-8")
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
    source = (ROOT / "web/js/features/storage/jobs.js").read_text(encoding="utf-8")
    css = (ROOT / "web/styles/storage-move-jobs.css").read_text(encoding="utf-8")
    assert "@keyframes royalStorageMoveJob" in css
    assert ".storage-move-job.is-active .storage-move-job-bar i" in css
    assert "animation:royalStorageMoveJob" in css
    assert "Läuft im Hintergrund" in source
