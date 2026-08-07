from media_quality import (
    media_profile_from_ffprobe,
    media_profile_from_jellyfin_item,
    media_profile_from_height,
    media_profile_is_better,
    media_profile_label,
    media_profile_within_target,
    media_quality_score,
)


def _profile(height=1080, *, codec="h264", bitrate=5_000_000, hdr="sdr", depth=8,
             audio="aac", channels=2, audio_bitrate=192_000):
    return {
        "width": 3840 if height >= 2160 else 1920,
        "height": height,
        "video_codec": codec,
        "video_bitrate": bitrate,
        "hdr": hdr,
        "bit_depth": depth,
        "audio_codec": audio,
        "audio_channels": channels,
        "audio_bitrate": audio_bitrate,
        "fps": 24,
    }


def test_resolution_is_primary_quality_tier():
    rich_1080 = _profile(
        1080,
        codec="av1",
        bitrate=20_000_000,
        hdr="hdr10",
        depth=10,
        audio="truehd",
        channels=8,
        audio_bitrate=2_000_000,
    )
    modest_2160 = _profile(2160, codec="h264", bitrate=4_000_000)
    assert media_quality_score(modest_2160) > media_quality_score(rich_1080)
    assert media_profile_is_better(modest_2160, rich_1080)


def test_same_resolution_can_upgrade_on_real_picture_and_audio_quality():
    current = _profile(1080, codec="h264", bitrate=4_000_000, audio="aac", channels=2)
    candidate = _profile(
        1080,
        codec="hevc",
        bitrate=7_000_000,
        hdr="hdr10",
        depth=10,
        audio="eac3",
        channels=6,
        audio_bitrate=640_000,
    )
    assert media_profile_is_better(candidate, current)
    assert "HDR10" in media_profile_label(candidate)
    assert "5.1" in media_profile_label(candidate)


def test_height_only_baseline_does_not_trigger_same_resolution_churn():
    assert not media_profile_is_better(_profile(1080), media_profile_from_height(1080))
    assert media_profile_is_better(_profile(2160), media_profile_from_height(1080))


def test_target_ceiling_uses_measured_height_not_provider_label():
    assert media_profile_within_target(_profile(1080), "1080p")
    assert not media_profile_within_target(_profile(2160), "1080p")
    assert media_profile_within_target(_profile(2160), "best")


def test_ffprobe_profile_reads_video_and_audio_details():
    profile = media_profile_from_ffprobe({
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 3840,
                "height": 2160,
                "pix_fmt": "yuv420p10le",
                "color_transfer": "smpte2084",
                "avg_frame_rate": "24000/1001",
                "bit_rate": "16000000",
            },
            {
                "codec_type": "audio",
                "codec_name": "eac3",
                "channels": 6,
                "sample_rate": "48000",
                "bit_rate": "640000",
                "tags": {"language": "deu"},
            },
        ],
        "format": {"bit_rate": "16640000"},
    })
    assert profile["height"] == 2160
    assert profile["video_codec"] == "hevc"
    assert profile["bit_depth"] == 10
    assert profile["hdr"] == "hdr10"
    assert profile["audio_codec"] == "eac3"
    assert profile["audio_channels"] == 6
    assert profile["audio_language"] == "deu"


def test_jellyfin_media_sources_produce_comparable_profile():
    profile = media_profile_from_jellyfin_item({
        "MediaSources": [{
            "Bitrate": 12_000_000,
            "MediaStreams": [
                {
                    "Type": "Video",
                    "Codec": "hevc",
                    "Width": 3840,
                    "Height": 2160,
                    "BitDepth": 10,
                    "VideoRangeType": "HDR10",
                    "BitRate": 11_000_000,
                    "AverageFrameRate": 23.976,
                },
                {
                    "Type": "Audio",
                    "Codec": "eac3",
                    "Channels": 6,
                    "BitRate": 640_000,
                    "SampleRate": 48_000,
                    "Language": "deu",
                },
            ],
        }],
    })
    assert profile["height"] == 2160
    assert profile["hdr"] == "hdr10"
    assert profile["audio_channels"] == 6
