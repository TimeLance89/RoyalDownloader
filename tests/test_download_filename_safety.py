import stat
from pathlib import Path

import server as app
from downloader import DownloadJob


def test_normal_filenames_remain_readable_and_compatible():
    assert app.build_movie_filename("The Chronology of Water", "2025") == (
        "The.Chronology.of.Water.2025.mp4"
    )
    assert app.build_filename("Breaking Bad", 1, 3) == "Breaking.Bad.S01E03.mp4"


def test_punctuation_sanitization_stays_readable_without_identity_hashes():
    assert app._sanitize("A/B") == "A B"
    assert app._sanitize("A:B") == "A B"
    assert app._sanitize("Smile - Siehst du es auch?") == "Smile - Siehst du es auch"
    assert "~" not in app.build_movie_filename("Smile - Siehst du es auch?", "")
    assert "~" not in app.build_movie_filename("Transformers 5: The Last Knight", "")


def test_reserved_empty_unicode_and_long_names_are_portable():
    assert app._sanitize("CON") == "_CON"
    assert app._sanitize("\x00\n") == "Media"
    assert app._sanitize("ＡＢＣ") == "ABC"
    filename = app.build_movie_filename("Überlanger Titel " * 80, "2026")
    assert len(filename.encode("utf-8")) <= 240
    assert filename.endswith(".mp4")


def test_commit_never_overwrites_existing_media(tmp_path: Path):
    target = tmp_path / "Film.2026.mp4"
    target.write_bytes(b"existing")
    first_source = tmp_path / "first.part"
    first_source.write_bytes(b"first")
    job = DownloadJob(
        "https://example.com/video.mp4",
        "mp4",
        target,
        queue_slug="movie:42",
    )

    first_target = job._commit_file(first_source, target)

    assert target.read_bytes() == b"existing"
    assert first_target != target
    assert first_target.read_bytes() == b"first"

    second_source = tmp_path / "second.part"
    second_source.write_bytes(b"second")
    second_target = job._commit_file(second_source, target)

    assert target.read_bytes() == b"existing"
    assert first_target.read_bytes() == b"first"
    assert second_target not in {target, first_target}
    assert second_target.read_bytes() == b"second"


def test_committed_media_is_readable_by_jellyfin_user(tmp_path: Path):
    source = tmp_path / "staged.part"
    source.write_bytes(b"movie")
    source.chmod(stat.S_IRUSR | stat.S_IWUSR)
    target = tmp_path / "The.Return.2006.mp4"
    job = DownloadJob("https://example.com/video.mp4", "mp4", target)

    committed = job._commit_file(source, target)

    mode = committed.stat().st_mode
    assert mode & stat.S_IRGRP
    assert mode & stat.S_IROTH


def test_staging_is_isolated_per_attempt(tmp_path: Path):
    first = DownloadJob(
        "https://example.test/video.mp4", "mp4", tmp_path / "movie.mp4",
        job_id="logical-job", attempt_id="attempt-one",
    )
    second = DownloadJob(
        "https://example.test/video.mp4", "mp4", tmp_path / "movie.mp4",
        job_id="logical-job", attempt_id="attempt-two",
    )

    assert first.staging_dir != second.staging_dir
    assert first.staging_dir.name == "attempt-one"
    assert second.staging_dir.name == "attempt-two"
