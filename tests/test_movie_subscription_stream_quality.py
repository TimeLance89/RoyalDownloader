from dataclasses import replace
from pathlib import Path

import downloader
import server  # noqa: F401
from application_services import movie_subscription_commit_guard as commit_guard
from application_services import movie_subscription_stream_quality as stream_quality
from hoster_intel import HosterIntel
from media_quality import normalize_media_profile
from providers.models import FilmpalastMovie, HosterInfo


def _hoster(name: str, url: str, quality: str) -> HosterInfo:
    return HosterInfo(name=name, url=url, language="Deutsch", quality=quality)


def _source(provider: str, url: str, hosters: list[HosterInfo]) -> FilmpalastMovie:
    return FilmpalastMovie(
        title="Test Movie",
        url=url,
        year="2026",
        provider=provider,
        content_language="de",
        hosters=hosters,
    )


def _profile(height: int, *, codec="h264", hdr="sdr", depth=8, channels=2):
    return normalize_media_profile({
        "width": 3840 if height >= 2160 else 2560 if height >= 1440 else 1920,
        "height": height,
        "video_codec": codec,
        "video_bitrate": 12_000_000 if height >= 2160 else 6_000_000,
        "hdr": hdr,
        "bit_depth": depth,
        "fps": 24,
        "audio_codec": "eac3" if channels >= 6 else "aac",
        "audio_channels": channels,
        "audio_bitrate": 640_000 if channels >= 6 else 192_000,
    })


def test_inventory_considers_every_provider_hoster_and_selects_measured_best(monkeypatch):
    sources = [
        _source(
            "provider-a",
            "https://provider-a.example/movie/test",
            [
                _hoster("A1", "https://a.example/1", "2160p"),
                _hoster("A2", "https://a.example/2", "1080p"),
            ],
        ),
        _source(
            "provider-b",
            "https://provider-b.example/movie/test",
            [
                _hoster("B1", "https://b.example/1", "720p"),
                _hoster("B2", "https://b.example/2", "1080p"),
            ],
        ),
    ]
    measured = {
        "https://a.example/1": _profile(1080),
        "https://a.example/2": _profile(1440, codec="hevc"),
        "https://b.example/1": _profile(2160, codec="hevc", hdr="hdr10", depth=10, channels=6),
        "https://b.example/2": _profile(1080),
    }
    calls = []

    monkeypatch.setattr(stream_quality, "_current_profile", lambda _entry: _profile(1080))

    def fake_probe(source, hoster, index, _cache, _unsupported, _barren):
        calls.append((source.provider, hoster.name, index))
        clone = replace(source, hosters=[hoster])
        clone._quality_inventory_candidate = True
        clone._probed_media_profile = measured[hoster.url]
        return clone

    monkeypatch.setattr(stream_quality, "_probe_hoster", fake_probe)
    monkeypatch.setattr(stream_quality, "log", lambda *_args, **_kwargs: None)
    entry = {
        "title": "Test Movie",
        "current_quality_rank": 1080,
        "target_quality": "2160p",
    }

    primary, fallbacks, rank, label = stream_quality._prepare_movie_subscription_upgrade(
        entry, sources,
    )

    assert len(calls) == 4
    assert {call[:2] for call in calls} == {
        ("provider-a", "A1"),
        ("provider-a", "A2"),
        ("provider-b", "B1"),
        ("provider-b", "B2"),
    }
    assert primary.provider == "provider-b"
    assert primary.hosters[0].name == "B1"
    assert rank == 2160
    assert "HDR10" in label
    assert fallbacks[0].hosters[0].name == "A2"
    assert all(movie.hosters[0].name != "A1" for movie in [primary, *fallbacks])


def test_candidate_identity_ignores_rotating_query_tokens():
    source = _source(
        "provider-a",
        "https://provider.example/movie/test?session=one",
        [_hoster("VOE", "https://voe.example/embed/abc?token=one", "2160p")],
    )
    first = stream_quality._candidate_key(source, source.hosters[0], 0)
    source.url = "https://provider.example/movie/test?session=two"
    source.hosters[0].url = "https://voe.example/embed/abc?token=two"
    second = stream_quality._candidate_key(source, source.hosters[0], 0)
    assert first == second


def test_precommit_guard_rejects_equal_quality_before_publish(monkeypatch):
    monkeypatch.setattr(downloader, "validate_media_file", lambda _path: (True, "ok"))
    monkeypatch.setattr(commit_guard, "probe_media_profile", lambda _path: (_profile(1080), ""))
    job = downloader.DownloadJob(
        "https://cdn.example/movie.mp4",
        "mp4",
        Path("/tmp/Test.Movie.mp4"),
        queue_slug="movie:test",
    )
    job._subscription_quality_baseline = _profile(1080)

    valid, message = job._validate_media(Path("/tmp/staged.mp4"))

    assert valid is False
    assert job.failure_kind == "quality"
    assert "Kein tatsächliches Qualitäts-Upgrade" in message


def test_precommit_guard_accepts_real_upgrade(monkeypatch):
    monkeypatch.setattr(downloader, "validate_media_file", lambda _path: (True, "ok"))
    measured = _profile(2160, codec="hevc", hdr="hdr10", depth=10, channels=6)
    monkeypatch.setattr(commit_guard, "probe_media_profile", lambda _path: (measured, ""))
    job = downloader.DownloadJob(
        "https://cdn.example/movie.mp4",
        "mp4",
        Path("/tmp/Test.Movie.mp4"),
        queue_slug="movie:test",
    )
    job._subscription_quality_baseline = _profile(1080)

    valid, message = job._validate_media(Path("/tmp/staged.mp4"))

    assert valid is True
    assert job._subscription_quality_actual["height"] == 2160
    assert "bestätigt" in message


def test_quality_rejection_does_not_penalize_hoster_health(tmp_path):
    intel = HosterIntel(path=tmp_path / "hoster-intel.json")
    url = "https://cdn.example/video"
    intel.record_download(
        url,
        False,
        hoster_name="VOE",
        speed_bps=5_000_000,
        failure_kind="quality",
    )
    domain = intel.domain(url)
    assert intel.stats[domain].get("download_ok") == 1
    assert not intel.stats[domain].get("download_fail")


def test_commit_records_actual_collision_safe_path(tmp_path):
    source = tmp_path / "staged.mp4"
    source.write_bytes(b"media")
    target = tmp_path / "Movie.mp4"
    job = downloader.DownloadJob(
        "https://cdn.example/movie.mp4",
        "mp4",
        target,
        queue_slug="movie:test-commit",
    )
    job._subscription_quality_actual = _profile(2160, codec="hevc", channels=6)

    committed = job._commit_file(source, target)
    try:
        assert committed == target
        assert commit_guard._committed_paths["movie:test-commit"] == target
        assert commit_guard._committed_profiles["movie:test-commit"]["height"] == 2160
    finally:
        commit_guard._committed_paths.pop("movie:test-commit", None)
        commit_guard._committed_profiles.pop("movie:test-commit", None)
