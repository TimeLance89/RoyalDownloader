from pathlib import Path
from types import SimpleNamespace

import pytest

import downloader
import server  # noqa: F401
from application_services import download_storage_guard as storage_guard
from application_services import movie_subscription_quality_hardening as quality_hardening
from application_services import movie_subscription_runtime_hardening as runtime_hardening
from application_services import movie_subscription_probe_optimizer as optimizer
from media_quality import normalize_media_profile


def _profile(height: int, *, hdr="sdr", codec="h264", channels=2, language="de"):
    return normalize_media_profile(
        {
            "width": 3840 if height >= 2160 else 1920,
            "height": height,
            "video_codec": codec,
            "video_bitrate": 14_000_000 if height >= 2160 else 6_000_000,
            "bit_depth": 10 if hdr != "sdr" else 8,
            "hdr": hdr,
            "fps": 24,
            "audio_codec": "eac3" if channels >= 6 else "aac",
            "audio_channels": channels,
            "audio_bitrate": 640_000 if channels >= 6 else 192_000,
            "audio_language": language,
        }
    )


def test_ffprobe_audio_ranking_prefers_requested_language_over_stronger_foreign_track():
    info = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 3840,
                "height": 2160,
                "pix_fmt": "yuv420p10le",
                "color_transfer": "smpte2084",
                "avg_frame_rate": "24/1",
                "bit_rate": "15000000",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "bit_rate": "192000",
                "sample_rate": "48000",
                "tags": {"language": "deu"},
            },
            {
                "codec_type": "audio",
                "codec_name": "truehd",
                "channels": 8,
                "bit_rate": "3000000",
                "sample_rate": "48000",
                "tags": {"language": "eng"},
            },
        ]
    }

    profile = quality_hardening._profile_from_ffprobe(info, "de")

    assert profile["audio_language"] == "de"
    assert profile["audio_codec"] == "aac"
    assert profile["audio_channels"] == 2


def test_jellyfin_audio_ranking_prefers_requested_language():
    item = {
        "MediaSources": [
            {
                "MediaStreams": [
                    {
                        "Type": "Video",
                        "Codec": "hevc",
                        "Width": 3840,
                        "Height": 2160,
                        "BitDepth": 10,
                        "VideoRangeType": "HDR10",
                    },
                    {
                        "Type": "Audio",
                        "Codec": "aac",
                        "Channels": 2,
                        "BitRate": 192000,
                        "Language": "deu",
                    },
                    {
                        "Type": "Audio",
                        "Codec": "truehd",
                        "Channels": 8,
                        "BitRate": 3000000,
                        "Language": "eng",
                    },
                ]
            }
        ]
    }

    profile = quality_hardening._profile_from_jellyfin(item, "de")

    assert profile["audio_language"] == "de"
    assert profile["audio_codec"] == "aac"
    assert profile["audio_channels"] == 2


def test_manifest_audio_group_does_not_merge_foreign_channel_count():
    text = """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",LANGUAGE="de",CHANNELS="2",NAME="Deutsch",URI="de.m3u8"
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",LANGUAGE="en",CHANNELS="6",NAME="English",URI="en.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=12000000,RESOLUTION=3840x2160,CODECS="hvc1.2.4.L153.B0,ec-3",AUDIO="aud"
2160.m3u8
"""
    with quality_hardening._preferred_language("de"):
        variants = quality_hardening._manifest_variants(
            text,
            "https://cdn.example/master.m3u8",
        )

    assert variants[0]["profile"]["audio_language"] == "de"
    assert variants[0]["profile"]["audio_channels"] == 2


def test_same_resolution_manifest_prefers_better_hdr_profile(monkeypatch):
    text = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=20000000,RESOLUTION=3840x2160,CODECS="avc1.640033,mp4a.40.2",VIDEO-RANGE=SDR
sdr.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=18000000,RESOLUTION=3840x2160,CODECS="hvc1.2.4.L153.B0,ec-3",VIDEO-RANGE=PQ
hdr.m3u8
"""
    monkeypatch.setattr(
        optimizer,
        "_fetch_hls_manifest",
        lambda *_args, **_kwargs: (text, ""),
    )

    with quality_hardening._preferred_language("de"):
        profile, uri, error, skip = quality_hardening._selected_manifest_variant(
            "https://cdn.example/master.m3u8",
            _profile(1080),
            "2160p",
        )

    assert error == ""
    assert skip is False
    assert uri.endswith("/hdr.m3u8")
    assert profile["hdr"] == "hdr10"
    assert profile["video_codec"] == "hevc"


def test_public_subscription_payload_hides_probe_cache(monkeypatch):
    monkeypatch.setattr(
        runtime_hardening,
        "_ORIGINAL_MOVIE_SUBSCRIPTIONS_PAYLOAD",
        lambda: {
            "movie_subscriptions": [
                {
                    "key": "tmdb:1",
                    "title": "Movie",
                    "quality_probe_cache": {"a": {}, "b": {}},
                    "upgrade_probe_baseline_profile": {"height": 1080},
                    "upgrade_available_profile": {"height": 2160},
                    "_upgrade_candidate_signature": "secret-internal",
                }
            ],
            "persistence": {"ok": True},
        },
    )

    payload = runtime_hardening.movie_subscriptions_payload()
    item = payload["movie_subscriptions"][0]

    assert item["quality_probe_cache_entries"] == 2
    assert "quality_probe_cache" not in item
    assert "upgrade_probe_baseline_profile" not in item
    assert "upgrade_available_profile" not in item
    assert "_upgrade_candidate_signature" not in item


def test_overlapping_movie_checks_are_coalesced(monkeypatch):
    first = {"key": "tmdb:1"}
    second = {"key": "tmdb:2"}
    fake_state = SimpleNamespace(
        movie_subscriptions=[first, second],
        movie_subscriptions_lock=runtime_hardening.threading.RLock(),
    )
    monkeypatch.setattr(runtime_hardening, "state", fake_state)
    runtime_hardening._pending_keys.clear()
    runtime_hardening._pending_all = False
    runtime_hardening._check_runner_active = False
    calls = []

    def fake_check(entries):
        calls.append(None if entries is None else [entry["key"] for entry in entries])
        if len(calls) == 1:
            assert runtime_hardening.check_movie_subscriptions([second]) == 0
        return 1

    monkeypatch.setattr(runtime_hardening, "_ORIGINAL_CHECK_MOVIE_SUBSCRIPTIONS", fake_check)

    checked = runtime_hardening.check_movie_subscriptions([first])

    assert checked == 2
    assert calls == [["tmdb:1"], ["tmdb:2"]]


def test_commit_rechecks_fresh_baseline_before_publication(monkeypatch, tmp_path):
    entry = {"key": "tmdb:1"}
    monkeypatch.setattr(quality_hardening, "_subscription_entry", lambda _slug: entry)
    monkeypatch.setattr(
        quality_hardening,
        "_current_profile",
        lambda _entry: _profile(2160, hdr="hdr10", codec="hevc", channels=6),
    )
    called = []
    monkeypatch.setattr(
        quality_hardening,
        "_ORIGINAL_COMMIT_FILE",
        lambda *_args, **_kwargs: called.append(True) or Path(tmp_path) / "published.mp4",
    )

    job = downloader.DownloadJob(
        "https://cdn.example/movie.mp4",
        "mp4",
        Path(tmp_path) / "Movie.mp4",
        queue_slug="tmdb:1",
    )
    job._subscription_quality_baseline = _profile(1080)
    job._subscription_quality_actual = _profile(2160, hdr="sdr", codec="h264", channels=2)

    with pytest.raises(RuntimeError, match="aktuell vorhandenen Datei"):
        quality_hardening._commit_file(
            job,
            Path(tmp_path) / "staged.mp4",
            Path(tmp_path) / "Movie.mp4",
        )

    assert called == []


def test_storage_guard_blocks_download_before_staging_when_reserve_is_exhausted(
    monkeypatch,
    tmp_path,
):
    if storage_guard._MIN_FREE_BYTES <= 0:
        pytest.skip("storage reserve disabled by environment")
    monkeypatch.setattr(
        storage_guard.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(total=10, used=9, free=1),
    )
    job = downloader.DownloadJob(
        "https://cdn.example/movie.mp4",
        "mp4",
        tmp_path / "Movie.mp4",
    )

    ok, message = storage_guard._prepare_staging(job)

    assert ok is False
    assert job.failure_kind == "storage"
    assert "freier Speicherplatz" in message
