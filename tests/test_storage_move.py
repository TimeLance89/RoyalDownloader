from pathlib import Path

import pytest

import storage_manager as sm
import storage_move as mover


def _write(path: Path, size: int, byte: bytes = b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        if size:
            handle.write(byte * size)


def _movie_candidate(root: Path, name: str = "Movie.mkv") -> dict:
    payload = sm.scan_large_content(
        {"movies": str(root), "series": ""},
        large_file_floor_bytes=1,
        large_folder_floor_bytes=1,
        max_files=1000,
    )
    return next(item for item in payload["candidates"] if item["relative_path"] == name)


def _series_file_candidate(root: Path, suffix: str = "Show/Season 01/E01.mkv") -> dict:
    payload = sm.scan_large_content(
        {"movies": "", "series": str(root)},
        large_file_floor_bytes=1,
        large_folder_floor_bytes=1,
        max_files=1000,
    )
    return next(item for item in payload["candidates"] if item["relative_path"] == suffix)


def _different_volumes(monkeypatch, source_root: Path, target_root: Path):
    source_resolved = source_root.resolve()
    target_resolved = target_root.resolve()

    def signature(path: Path):
        resolved = path.resolve()
        if resolved == source_resolved:
            return (101, 10_000)
        if resolved == target_resolved:
            return (202, 20_000)
        return (303, 30_000)

    monkeypatch.setattr(mover, "_volume_signature", signature)
    monkeypatch.setattr(mover, "_MIN_FREE_RESERVE", 0)


def test_movie_move_removes_source_and_creates_only_destination(tmp_path, monkeypatch):
    movies = tmp_path / "movies"
    target = tmp_path / "external"
    series = tmp_path / "series"
    movies.mkdir(); target.mkdir(); series.mkdir()
    source = movies / "Movie.mkv"
    _write(source, 128)
    candidate = _movie_candidate(movies)
    _different_volumes(monkeypatch, movies, target)

    locations = [{"id": "external", "label": "Externe HDD", "path": str(target), "mode": "media"}]
    result = mover.move_candidate(
        {"movies": str(movies), "series": str(series)},
        locations,
        root_key="movies",
        relative_path=candidate["relative_path"],
        token=candidate["token"],
        expected_size=candidate["size_bytes"],
        expires_at=candidate["expires_at"],
        destination_root="location:external",
    )

    assert result["moved"] is True
    assert result["source_kind"] == "movie"
    assert not source.exists()
    assert (target / "Movie.mkv").read_bytes() == b"x" * 128
    assert list(target.glob("Movie*")) == [target / "Movie.mkv"]


def test_series_episode_candidate_moves_complete_series_folder(tmp_path, monkeypatch):
    movies = tmp_path / "movies"
    series = tmp_path / "series"
    target = tmp_path / "external"
    movies.mkdir(); series.mkdir(); target.mkdir()
    _write(series / "Show" / "Season 01" / "E01.mkv", 1000, b"a")
    _write(series / "Show" / "Season 01" / "E02.mkv", 10, b"b")
    _write(series / "Show" / "Season 02" / "E03.mkv", 10, b"c")
    _write(series / "Show" / "Season 02" / "E04.mkv", 10, b"d")
    candidate = _series_file_candidate(series)
    _different_volumes(monkeypatch, series, target)

    locations = [{"id": "external", "label": "Externe HDD", "path": str(target), "mode": "media"}]
    plan = mover.plan_move_candidate(
        {"movies": str(movies), "series": str(series)}, locations,
        root_key="series", relative_path=candidate["relative_path"], token=candidate["token"],
        expected_size=candidate["size_bytes"], expires_at=candidate["expires_at"],
    )
    assert plan["source_kind"] == "series"
    assert plan["source_name"] == "Show"
    assert plan["size_bytes"] == 1030

    result = mover.move_candidate(
        {"movies": str(movies), "series": str(series)}, locations,
        root_key="series", relative_path=candidate["relative_path"], token=candidate["token"],
        expected_size=candidate["size_bytes"], expires_at=candidate["expires_at"],
        destination_root="location:external",
    )
    assert result["source_kind"] == "series"
    assert not (series / "Show").exists()
    assert (target / "Show" / "Season 01" / "E01.mkv").read_bytes() == b"a" * 1000
    assert (target / "Show" / "Season 01" / "E02.mkv").read_bytes() == b"b" * 10
    assert (target / "Show" / "Season 02" / "E03.mkv").read_bytes() == b"c" * 10
    assert (target / "Show" / "Season 02" / "E04.mkv").read_bytes() == b"d" * 10


def test_move_rejects_same_physical_volume(tmp_path, monkeypatch):
    movies = tmp_path / "movies"
    target = tmp_path / "external"
    series = tmp_path / "series"
    movies.mkdir(); target.mkdir(); series.mkdir()
    source = movies / "Movie.mkv"
    _write(source, 64)
    candidate = _movie_candidate(movies)
    monkeypatch.setattr(mover, "_volume_signature", lambda _path: (1, 1000))
    monkeypatch.setattr(mover, "_MIN_FREE_RESERVE", 0)
    locations = [{"id": "external", "label": "External", "path": str(target), "mode": "media"}]

    with pytest.raises(ValueError, match="demselben physischen Volume"):
        mover.move_candidate(
            {"movies": str(movies), "series": str(series)}, locations,
            root_key="movies", relative_path=candidate["relative_path"], token=candidate["token"],
            expected_size=candidate["size_bytes"], expires_at=candidate["expires_at"],
            destination_root="location:external",
        )
    assert source.exists()
    assert not (target / "Movie.mkv").exists()


def test_move_never_overwrites_existing_destination(tmp_path, monkeypatch):
    movies = tmp_path / "movies"
    target = tmp_path / "external"
    series = tmp_path / "series"
    movies.mkdir(); target.mkdir(); series.mkdir()
    source = movies / "Movie.mkv"
    existing = target / "Movie.mkv"
    _write(source, 64, b"s")
    _write(existing, 32, b"d")
    candidate = _movie_candidate(movies)
    _different_volumes(monkeypatch, movies, target)
    locations = [{"id": "external", "label": "External", "path": str(target), "mode": "media"}]

    with pytest.raises(ValueError, match="existiert bereits"):
        mover.move_candidate(
            {"movies": str(movies), "series": str(series)}, locations,
            root_key="movies", relative_path=candidate["relative_path"], token=candidate["token"],
            expected_size=candidate["size_bytes"], expires_at=candidate["expires_at"],
            destination_root="location:external",
        )
    assert source.read_bytes() == b"s" * 64
    assert existing.read_bytes() == b"d" * 32


def test_monitor_location_cannot_be_move_destination(tmp_path, monkeypatch):
    movies = tmp_path / "movies"
    target = tmp_path / "archive"
    series = tmp_path / "series"
    movies.mkdir(); target.mkdir(); series.mkdir()
    _write(movies / "Movie.mkv", 64)
    candidate = _movie_candidate(movies)
    _different_volumes(monkeypatch, movies, target)
    locations = [{"id": "archive", "label": "Archiv", "path": str(target), "mode": "monitor"}]

    plan = mover.plan_move_candidate(
        {"movies": str(movies), "series": str(series)}, locations,
        root_key="movies", relative_path=candidate["relative_path"], token=candidate["token"],
        expected_size=candidate["size_bytes"], expires_at=candidate["expires_at"],
    )
    assert not any(item["root"] == "location:archive" for item in plan["targets"])
    with pytest.raises(ValueError, match="nicht für Medienaktionen freigegeben"):
        mover.move_candidate(
            {"movies": str(movies), "series": str(series)}, locations,
            root_key="movies", relative_path=candidate["relative_path"], token=candidate["token"],
            expected_size=candidate["size_bytes"], expires_at=candidate["expires_at"],
            destination_root="location:archive",
        )
