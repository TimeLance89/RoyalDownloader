import os
import time

from media.downloader import cleanup_stale_staging


def artifact(root, identity, *, foreign=False):
    path = root / identity
    path.mkdir(parents=True)
    (path / ".royal-downloader-job").write_text(identity, encoding="ascii")
    (path / "download.mp4.part").write_bytes(b"Royal partial")
    if foreign:
        (path / "backup.zip").write_bytes(b"foreign backup")
    old = time.time() - 8 * 86400
    os.utime(path, (old, old))
    return path


def test_preview_never_deletes_and_foreign_file_disqualifies_entire_directory(tmp_path):
    good = artifact(tmp_path, "a" * 32)
    foreign = artifact(tmp_path, "b" * 32, foreign=True)
    preview = cleanup_stale_staging(staging_roots=[tmp_path], strict=True, preview=True,
                                    older_than_seconds=7 * 86400)
    assert [item["path"] for item in preview] == [str(good)]
    assert good.exists() and foreign.exists()
    assert cleanup_stale_staging(staging_roots=[tmp_path], strict=True, older_than_seconds=7 * 86400) == 1
    assert not good.exists()
    assert (foreign / "backup.zip").read_bytes() == b"foreign backup"


def test_active_attempt_and_unmarked_directory_never_deleted(tmp_path):
    active = artifact(tmp_path, "a" * 32)
    unmarked = tmp_path / ("b" * 32)
    unmarked.mkdir()
    (unmarked / "download.mp4").write_bytes(b"unknown")
    assert cleanup_stale_staging(staging_roots=[tmp_path], strict=True,
                                  protected_attempts={active.name}, older_than_seconds=0) == 0
    assert active.exists() and unmarked.exists()


def test_recent_attempt_is_not_an_orphan(tmp_path):
    path = artifact(tmp_path, "c" * 32)
    os.utime(path, None)
    assert cleanup_stale_staging(staging_roots=[tmp_path], strict=True, older_than_seconds=7 * 86400) == 0
    assert path.exists()


def test_symlink_is_never_followed(tmp_path):
    import pytest
    outside = tmp_path / "outside"
    outside.mkdir()
    data = outside / "backup.zip"
    data.write_bytes(b"safe")
    root = tmp_path / "staging"
    root.mkdir()
    path = artifact(root, "a" * 32)
    try:
        (path / "download.mp4").symlink_to(data)
    except OSError:
        pytest.skip("Symlink privileges unavailable")
    assert cleanup_stale_staging(staging_roots=[root], strict=True, older_than_seconds=0) == 0
    assert data.read_bytes() == b"safe"
