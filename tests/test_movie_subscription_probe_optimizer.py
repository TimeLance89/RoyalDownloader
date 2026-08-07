import threading
import time
from dataclasses import replace
from pathlib import Path

import downloader
import server  # noqa: F401
from application_services import movie_subscription_probe_optimizer as optimizer
from application_services import movie_subscription_stream_quality as stream_quality
from media_quality import normalize_media_profile
from providers.models import FilmpalastMovie, HosterInfo


def _profile(height: int, *, codec="h264", channels=2):
    return normalize_media_profile(
        {
            "width": 3840 if height >= 2160 else 1920,
            "height": height,
            "video_codec": codec,
            "video_bitrate": 12_000_000 if height >= 2160 else 5_000_000,
            "bit_depth": 10 if height >= 2160 else 8,
            "hdr": "hdr10" if height >= 2160 else "sdr",
            "fps": 24,
            "audio_codec": "eac3" if channels >= 6 else "aac",
            "audio_channels": channels,
            "audio_bitrate": 640_000 if channels >= 6 else 192_000,
        }
    )


def _source(hoster_count: int = 1):
    return FilmpalastMovie(
        title="Probe Movie",
        url="https://provider.example/movie/probe",
        year="2026",
        provider="provider-a",
        content_language="de",
        hosters=[
            HosterInfo(
                name=f"Hoster-{index}",
                url=f"https://hoster.example/embed/{index}",
                language="Deutsch",
                quality="2160p",
            )
            for index in range(hoster_count)
        ],
    )


def test_manifest_parser_reads_resolution_codecs_hdr_and_audio_group():
    text = """#EXTM3U
#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="aud",LANGUAGE="de",CHANNELS="6",URI="audio.m3u8"
#EXT-X-STREAM-INF:BANDWIDTH=5500000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2",AUDIO="aud",FRAME-RATE=24
1080.m3u8
#EXT-X-STREAM-INF:AVERAGE-BANDWIDTH=16000000,RESOLUTION=3840x2160,CODECS="hvc1.2.4.L153.B0,ec-3",VIDEO-RANGE=PQ,AUDIO="aud",FRAME-RATE=23.976
2160.m3u8
"""

    variants = optimizer._manifest_variants(text, "https://cdn.example/master.m3u8")

    assert len(variants) == 2
    best = max(variants, key=lambda item: item["profile"]["height"])
    assert best["uri"] == "https://cdn.example/2160.m3u8"
    assert best["profile"]["height"] == 2160
    assert best["profile"]["video_codec"] == "hevc"
    assert best["profile"]["bit_depth"] == 10
    assert best["profile"]["hdr"] == "hdr10"
    assert best["profile"]["audio_codec"] == "eac3"
    assert best["profile"]["audio_channels"] == 6


def test_manifest_preflight_skips_deep_probe_when_master_is_clearly_worse(monkeypatch):
    text = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
1080.m3u8
"""
    monkeypatch.setattr(optimizer, "_fetch_hls_manifest", lambda *_args, **_kwargs: (text, ""))

    profile, reason, skip = optimizer._manifest_preflight(
        "https://cdn.example/master.m3u8",
        "hls",
        _profile(2160, codec="hevc", channels=6),
        "best",
    )

    assert profile["height"] == 1080
    assert skip is True
    assert "unter vorhandener Auflösung" in reason


def test_manifest_preflight_keeps_potential_upgrade_for_deep_probe(monkeypatch):
    text = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=16000000,RESOLUTION=3840x2160,CODECS="hvc1.2.4.L153.B0,ec-3",VIDEO-RANGE=PQ
2160.m3u8
"""
    monkeypatch.setattr(optimizer, "_fetch_hls_manifest", lambda *_args, **_kwargs: (text, ""))

    profile, reason, skip = optimizer._manifest_preflight(
        "https://cdn.example/master.m3u8",
        "hls",
        _profile(1080),
        "2160p",
    )

    assert profile["height"] == 2160
    assert reason == ""
    assert skip is False


def test_inventory_deep_probes_with_bounded_parallelism(monkeypatch):
    source = _source(8)
    entry = {
        "title": "Probe Movie",
        "current_quality_rank": 1080,
        "target_quality": "2160p",
    }
    active = 0
    maximum = 0
    lock = threading.Lock()

    monkeypatch.setattr(stream_quality, "_current_profile", lambda _entry: _profile(1080))
    monkeypatch.setattr(stream_quality, "log", lambda *_args, **_kwargs: None)

    def fake_probe(source, hoster, index, cache, cache_lock, unsupported, barren, baseline, target, counters, counter_lock):
        nonlocal active, maximum
        del cache, cache_lock, unsupported, barren, baseline, target, counters, counter_lock
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            time.sleep(0.04)
            clone = replace(source, hosters=[hoster])
            clone._quality_inventory_candidate = True
            clone._probed_media_profile = _profile(2160, codec="hevc", channels=6)
            return clone
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(optimizer, "_probe_uncached", fake_probe)

    primary, fallbacks, rank, _label = optimizer._prepare_movie_subscription_upgrade(entry, [source])

    assert primary is not None
    assert len(fallbacks) == 7
    assert rank == 2160
    assert 2 <= maximum <= optimizer._MAX_PROBE_WORKERS


def test_subscription_ytdlp_uses_measured_upgrade_height(monkeypatch, tmp_path):
    captured = {}

    class FakeProcess:
        def __init__(self, cmd, **_kwargs):
            captured["cmd"] = list(cmd)
            self.stdout = []
            self.returncode = 0

        def wait(self, timeout=None):
            del timeout
            return 0

        def poll(self):
            return self.returncode

    monkeypatch.setattr(downloader, "ensure_public_http_url", lambda _url: None)
    monkeypatch.setattr(downloader, "safe_proxy_url", lambda: "http://127.0.0.1:9999")
    monkeypatch.setattr(optimizer.subprocess, "Popen", FakeProcess)

    job = downloader.DownloadJob(
        "https://cdn.example/master.m3u8",
        "hls",
        Path(tmp_path) / "Movie.mp4",
        queue_slug="movie:quality-test",
    )
    monkeypatch.setattr(job, "_prepare_staging", lambda: (True, ""))

    ok, _message = optimizer._download_ytdlp_for_height(job, 2160)

    assert ok is True
    sort_index = captured["cmd"].index("-S")
    assert captured["cmd"][sort_index + 1] == "res:2160,ext:mp4:m4a"
