import server  # noqa: F401
from application_services import movie_subscription_probe_optimizer as optimizer
from application_services import movie_subscription_probe_targeting as targeting
from media_quality import normalize_media_profile


def _profile(height: int, *, codec="h264", audio="aac"):
    return normalize_media_profile(
        {
            "width": 3840 if height >= 2160 else 1920 if height >= 1080 else 1280,
            "height": height,
            "video_codec": codec,
            "video_bitrate": 12_000_000 if height >= 2160 else 5_000_000,
            "bit_depth": 10 if height >= 2160 else 8,
            "hdr": "hdr10" if height >= 2160 else "sdr",
            "fps": 24,
            "audio_codec": audio,
            "audio_channels": 6 if audio == "eac3" else 2,
            "audio_bitrate": 640_000 if audio == "eac3" else 192_000,
        }
    )


def test_selected_manifest_variant_respects_1080_target(monkeypatch):
    manifest = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720,CODECS="avc1.64001f,mp4a.40.2"
720.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=5500000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
1080.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=16000000,RESOLUTION=3840x2160,CODECS="hvc1.2.4.L153.B0,ec-3",VIDEO-RANGE=PQ
2160.m3u8
"""
    monkeypatch.setattr(
        optimizer,
        "_fetch_hls_manifest",
        lambda *_args, **_kwargs: (manifest, ""),
    )

    profile, uri, reason, skip = targeting._selected_manifest_variant(
        "https://cdn.example/master.m3u8",
        _profile(720),
        "1080p",
    )

    assert profile["height"] == 1080
    assert uri == "https://cdn.example/1080.m3u8"
    assert reason == ""
    assert skip is False


def test_selected_manifest_variant_can_skip_when_best_allowed_is_worse(monkeypatch):
    manifest = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=5500000,RESOLUTION=1920x1080,CODECS="avc1.640028,mp4a.40.2"
1080.m3u8
"""
    monkeypatch.setattr(
        optimizer,
        "_fetch_hls_manifest",
        lambda *_args, **_kwargs: (manifest, ""),
    )

    profile, uri, reason, skip = targeting._selected_manifest_variant(
        "https://cdn.example/master.m3u8",
        _profile(2160, codec="hevc", audio="eac3"),
        "best",
    )

    assert profile["height"] == 1080
    assert uri == "https://cdn.example/1080.m3u8"
    assert skip is True
    assert "unter vorhandener Auflösung" in reason


def test_merge_profile_keeps_deep_probe_authoritative_and_fills_missing_fields():
    deep = normalize_media_profile(
        {
            "width": 1920,
            "height": 1080,
            "video_codec": "h264",
            "video_bitrate": 6_000_000,
            "fps": 24,
        }
    )
    manifest = normalize_media_profile(
        {
            "width": 1920,
            "height": 1080,
            "video_codec": "hevc",
            "video_bitrate": 5_000_000,
            "bit_depth": 10,
            "hdr": "hdr10",
            "audio_codec": "eac3",
            "audio_channels": 6,
        }
    )

    merged = targeting._merge_profile(deep, manifest)

    assert merged["video_codec"] == "h264"
    assert merged["video_bitrate"] == 6_000_000
    assert merged["audio_codec"] == "eac3"
    assert merged["audio_channels"] == 6
    assert merged["bit_depth"] == 10
    assert merged["hdr"] == "hdr10"
