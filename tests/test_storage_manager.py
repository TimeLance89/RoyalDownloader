from pathlib import Path
import time

import pytest

import storage_manager as sm


def _write(path: Path, size: int):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.truncate(size)


def test_storage_status_deduplicates_shared_nas_filesystem(tmp_path):
    movies = tmp_path / "movies"
    series = tmp_path / "series"
    movies.mkdir(); series.mkdir()
    payload = sm.storage_status({"movies": str(movies), "series": str(series)}, "nas")
    assert payload["enabled"] is True
    assert payload["summary"]["volume_count"] == 1
    assert all(root["available"] for root in payload["roots"])
    assert all(root["measurement"] == "nas_mount" for root in payload["roots"])


def test_scan_surfaces_large_series_and_outlier_file(tmp_path):
    movies = tmp_path / "movies"
    series = tmp_path / "series"
    movies.mkdir(); series.mkdir()
    _write(movies / "Normal.mkv", 100)
    _write(movies / "Huge.mkv", 800)
    _write(series / "Big Show" / "Season 01" / "E01.mkv", 350)
    _write(series / "Big Show" / "Season 01" / "E02.mkv", 350)
    payload = sm.scan_large_content(
        {"movies": str(movies), "series": str(series)},
        large_file_floor_bytes=200,
        large_folder_floor_bytes=200,
        max_files=1000,
    )
    paths = {(item["root"], item["relative_path"]) for item in payload["candidates"]}
    assert ("movies", "Huge.mkv") in paths
    assert ("series", "Big Show") in paths
    assert payload["truncated"] is False


def test_cleanup_requires_signed_unchanged_candidate(tmp_path):
    movies = tmp_path / "movies"; series = tmp_path / "series"
    movies.mkdir(); series.mkdir()
    target = movies / "Huge.mkv"
    _write(target, 800)
    paths = {"movies": str(movies), "series": str(series)}
    payload = sm.scan_large_content(paths, large_file_floor_bytes=100, large_folder_floor_bytes=100)
    candidate = next(item for item in payload["candidates"] if item["relative_path"] == "Huge.mkv")
    with pytest.raises(ValueError, match="abgelaufen|ungültig"):
        sm.cleanup_candidate(
            paths, root_key="movies", relative_path="Huge.mkv", token="forged",
            expected_size=800, expires_at=candidate["expires_at"],
        )
    result = sm.cleanup_candidate(
        paths, root_key="movies", relative_path="Huge.mkv", token=candidate["token"],
        expected_size=candidate["size_bytes"], expires_at=candidate["expires_at"],
    )
    assert result["freed_bytes"] == 800
    assert not target.exists()


def test_cleanup_rejects_symlink_inside_media_root(tmp_path):
    movies = tmp_path / "movies"; series = tmp_path / "series"; outside = tmp_path / "outside.mkv"
    movies.mkdir(); series.mkdir(); _write(outside, 100)
    link = movies / "linked.mkv"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="Symbolische Links"):
        sm.cleanup_candidate(
            {"movies": str(movies), "series": str(series)}, root_key="movies",
            relative_path="linked.mkv", token="x", expected_size=100,
            expires_at=int(time.time()) + 60,
        )
    assert outside.exists()


def test_cleanup_rejects_candidate_changed_after_scan(tmp_path):
    movies = tmp_path / "movies"; series = tmp_path / "series"
    movies.mkdir(); series.mkdir(); target = movies / "Changing.mkv"; _write(target, 800)
    paths = {"movies": str(movies), "series": str(series)}
    payload = sm.scan_large_content(paths, large_file_floor_bytes=100, large_folder_floor_bytes=100)
    candidate = next(item for item in payload["candidates"] if item["relative_path"] == "Changing.mkv")
    _write(target, 900)
    with pytest.raises(ValueError, match="verändert"):
        sm.cleanup_candidate(
            paths, root_key="movies", relative_path="Changing.mkv", token=candidate["token"],
            expected_size=candidate["size_bytes"], expires_at=candidate["expires_at"],
        )
    assert target.exists()


def test_truncated_series_folder_is_never_cleanup_candidate(tmp_path):
    movies = tmp_path / "movies"; series = tmp_path / "series"
    movies.mkdir(); series.mkdir()
    for index in range(120):
        _write(series / "Huge Show" / f"E{index:03}.mkv", 10)
    payload = sm.scan_large_content(
        {"movies": str(movies), "series": str(series)},
        large_file_floor_bytes=1, large_folder_floor_bytes=1, max_files=100,
    )
    assert payload["truncated"] is True
    assert not any(item["relative_path"] == "Huge Show" for item in payload["candidates"])


def test_scan_deduplicates_identical_movie_and_series_roots(tmp_path):
    media = tmp_path / "media"; media.mkdir(); _write(media / "Large.mkv", 800)
    payload = sm.scan_large_content(
        {"movies": str(media), "series": str(media)},
        large_file_floor_bytes=100, large_folder_floor_bytes=100,
    )
    assert len([item for item in payload["candidates"] if item["relative_path"] == "Large.mkv"]) == 1


def test_cleanup_rejects_expired_scan_token(tmp_path, monkeypatch):
    movies = tmp_path / "movies"; series = tmp_path / "series"
    movies.mkdir(); series.mkdir(); target = movies / "Old.mkv"; _write(target, 800)
    paths = {"movies": str(movies), "series": str(series)}
    payload = sm.scan_large_content(paths, large_file_floor_bytes=100, large_folder_floor_bytes=100)
    candidate = next(item for item in payload["candidates"] if item["relative_path"] == "Old.mkv")
    monkeypatch.setattr(sm.time, "time", lambda: candidate["expires_at"] + 1)
    with pytest.raises(ValueError, match="abgelaufen"):
        sm.cleanup_candidate(
            paths, root_key="movies", relative_path="Old.mkv", token=candidate["token"],
            expected_size=800, expires_at=candidate["expires_at"],
        )
    assert target.exists()


def test_cleanup_rejects_directory_with_active_staging(tmp_path):
    movies = tmp_path / "movies"; series = tmp_path / "series"
    movies.mkdir(); series.mkdir(); _write(series / "Show" / "S01" / "E01.mkv", 800)
    paths = {"movies": str(movies), "series": str(series)}
    payload = sm.scan_large_content(paths, large_file_floor_bytes=100, large_folder_floor_bytes=100)
    candidate = next(item for item in payload["candidates"] if item["relative_path"] == "Show")
    _write(series / "Show" / "S01" / ".downloading" / "job" / "partial.mkv", 20)
    with pytest.raises(ValueError, match="Arbeitsdaten"):
        sm.cleanup_candidate(
            paths, root_key="series", relative_path="Show", token=candidate["token"],
            expected_size=candidate["size_bytes"], expires_at=candidate["expires_at"],
        )
    assert (series / "Show").exists()
