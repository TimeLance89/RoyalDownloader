"""Measured media quality profiles for local files and resolved streams.

The subscription system must never treat provider labels as authoritative.  This
module turns ffprobe/Jellyfin metadata into a small, serialisable profile and
provides deterministic comparison rules.  Resolution remains the primary tier;
within the same tier HDR, bit depth, codec/bitrate and audio quality decide.
"""

from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path
from typing import Any

from network_guard import UnsafeNetworkTarget, ensure_public_http_url

PROBE_TIMEOUT_SECONDS = 25
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
PROBE_SIZE_BYTES = 5 * 1024 * 1024
ANALYZE_DURATION_US = 5_000_000
SAME_RESOLUTION_MIN_DELTA = 1_000

_VIDEO_CODEC_RANK = {
    "av1": 12,
    "hevc": 11,
    "h265": 11,
    "vp9": 10,
    "h264": 8,
    "avc": 8,
    "mpeg4": 5,
    "mpeg2video": 4,
}
_AUDIO_CODEC_RANK = {
    "truehd": 12,
    "dts-hd ma": 12,
    "dts-hd": 11,
    "eac3": 10,
    "e-ac-3": 10,
    "dts": 9,
    "ac3": 8,
    "flac": 8,
    "aac": 6,
    "opus": 6,
    "mp3": 4,
}
_HDR_RANK = {"": 0, "sdr": 0, "hdr": 1, "hlg": 2, "hdr10": 3, "dolby_vision": 4}


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError, OverflowError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        result = float(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return result if math.isfinite(result) and result >= 0 else 0.0


def _fps(value: Any) -> float:
    text = str(value or "").strip()
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        den = _safe_float(denominator)
        return _safe_float(numerator) / den if den else 0.0
    return _safe_float(text)


def _codec(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().replace("_", "-").split())


def _hdr_label(stream: dict) -> str:
    transfer = _codec(stream.get("color_transfer"))
    side_data = " ".join(
        str(item.get("side_data_type") or "")
        for item in (stream.get("side_data_list") or [])
        if isinstance(item, dict)
    ).casefold()
    profile = str(stream.get("profile") or "").casefold()
    if "dolby vision" in side_data or "dovi" in side_data or "dolby vision" in profile:
        return "dolby_vision"
    if transfer == "smpte2084":
        return "hdr10"
    if transfer == "arib-std-b67":
        return "hlg"
    if transfer or str(stream.get("color_primaries") or "").casefold() == "bt2020":
        return "hdr"
    return "sdr"


def _bit_depth(stream: dict) -> int:
    for key in ("bits_per_raw_sample", "bits_per_sample"):
        value = _safe_int(stream.get(key))
        if value:
            return value
    pix_fmt = str(stream.get("pix_fmt") or "").casefold()
    for depth in (16, 14, 12, 10, 9, 8):
        if str(depth) in pix_fmt:
            return depth
    return 8 if pix_fmt else 0


def normalize_media_profile(profile: dict | None) -> dict:
    raw = profile if isinstance(profile, dict) else {}
    return {
        "width": _safe_int(raw.get("width")),
        "height": _safe_int(raw.get("height")),
        "video_codec": _codec(raw.get("video_codec")),
        "video_bitrate": _safe_int(raw.get("video_bitrate")),
        "bit_depth": _safe_int(raw.get("bit_depth")),
        "hdr": str(raw.get("hdr") or "").strip().casefold(),
        "fps": round(_safe_float(raw.get("fps")), 3),
        "audio_codec": _codec(raw.get("audio_codec")),
        "audio_channels": _safe_int(raw.get("audio_channels")),
        "audio_bitrate": _safe_int(raw.get("audio_bitrate")),
        "audio_sample_rate": _safe_int(raw.get("audio_sample_rate")),
        "audio_language": str(raw.get("audio_language") or "").strip().casefold(),
    }


def media_profile_from_height(height: int) -> dict:
    return normalize_media_profile({"height": _safe_int(height)})


def media_profile_complete(profile: dict | None) -> bool:
    value = normalize_media_profile(profile)
    return value["height"] > 0 and bool(value["video_codec"]) and bool(value["audio_codec"])


def _secondary_known(profile: dict) -> bool:
    return any(
        (
            profile["video_codec"],
            profile["video_bitrate"],
            profile["bit_depth"],
            profile["audio_codec"],
            profile["audio_channels"],
            profile["audio_bitrate"],
        )
    )


def media_quality_score(profile: dict | None) -> int:
    value = normalize_media_profile(profile)
    height = value["height"]
    # Resolution is the stable primary tier.  All secondary contributions stay
    # below 100k, therefore a genuine higher-resolution tier always wins.
    score = height * 100_000
    score += _HDR_RANK.get(value["hdr"], 1 if value["hdr"] else 0) * 12_000
    score += max(0, value["bit_depth"] - 8) * 2_500
    score += _VIDEO_CODEC_RANK.get(value["video_codec"], 3 if value["video_codec"] else 0) * 700
    score += min(30_000, value["video_bitrate"] // 1_000)
    score += min(8, value["audio_channels"]) * 1_000
    score += _AUDIO_CODEC_RANK.get(value["audio_codec"], 2 if value["audio_codec"] else 0) * 350
    score += min(6_000, value["audio_bitrate"] // 1_000)
    score += min(1_000, int(value["fps"] * 10))
    return int(score)


def media_profile_is_better(candidate: dict | None, current: dict | None) -> bool:
    new = normalize_media_profile(candidate)
    old = normalize_media_profile(current)
    if new["height"] <= 0:
        return False
    if old["height"] <= 0:
        return True
    if new["height"] != old["height"]:
        return new["height"] > old["height"]
    # A height-only Jellyfin fallback must not trigger same-resolution churn.
    # Same-tier upgrades require actual technical details on both sides.
    if not _secondary_known(new) or not _secondary_known(old):
        return False
    return media_quality_score(new) >= media_quality_score(old) + SAME_RESOLUTION_MIN_DELTA


def media_profile_within_target(profile: dict | None, target: str) -> bool:
    value = normalize_media_profile(profile)
    if value["height"] <= 0:
        return False
    normalized = str(target or "best").strip().casefold()
    aliases = {"4k": "2160p", "uhd": "2160p"}
    normalized = aliases.get(normalized, normalized)
    ceilings = {"720p": 720, "1080p": 1080, "2160p": 2160, "best": 10_000}
    return value["height"] <= ceilings.get(normalized, 10_000)


def media_profile_label(profile: dict | None) -> str:
    value = normalize_media_profile(profile)
    if value["height"] <= 0:
        return "Qualität unbekannt"
    parts = [f"{value['height']}p"]
    video = value["video_codec"]
    video_labels = {"hevc": "HEVC", "h265": "HEVC", "h264": "H.264", "avc": "H.264", "av1": "AV1", "vp9": "VP9"}
    if video:
        parts.append(video_labels.get(video, video.upper()))
    hdr_labels = {"hdr10": "HDR10", "hlg": "HLG", "dolby_vision": "Dolby Vision", "hdr": "HDR"}
    if value["hdr"] in hdr_labels:
        parts.append(hdr_labels[value["hdr"]])
    if value["bit_depth"] > 8:
        parts.append(f"{value['bit_depth']}-bit")
    audio = value["audio_codec"]
    audio_labels = {"eac3": "E-AC-3", "e-ac-3": "E-AC-3", "ac3": "AC-3", "aac": "AAC", "truehd": "TrueHD", "dts": "DTS", "opus": "Opus"}
    if audio:
        audio_text = audio_labels.get(audio, audio.upper())
        channels = value["audio_channels"]
        if channels >= 8:
            audio_text += " 7.1"
        elif channels >= 6:
            audio_text += " 5.1"
        elif channels >= 2:
            audio_text += " 2.0"
        elif channels == 1:
            audio_text += " Mono"
        parts.append(audio_text)
    return " · ".join(parts)


def media_profile_from_ffprobe(info: dict | None) -> dict:
    data = info if isinstance(info, dict) else {}
    streams = [item for item in (data.get("streams") or []) if isinstance(item, dict)]
    videos = [item for item in streams if str(item.get("codec_type") or "").casefold() == "video"]
    audios = [item for item in streams if str(item.get("codec_type") or "").casefold() == "audio"]
    if not videos:
        return normalize_media_profile({})
    video = max(
        videos,
        key=lambda item: (
            _safe_int(item.get("height")),
            _safe_int(item.get("width")),
            _safe_int(item.get("bit_rate")),
        ),
    )
    audio = max(
        audios,
        key=lambda item: (
            _safe_int(item.get("channels")),
            _safe_int(item.get("bit_rate")),
        ),
        default={},
    )
    format_bitrate = _safe_int((data.get("format") or {}).get("bit_rate"))
    video_bitrate = _safe_int(video.get("bit_rate"))
    audio_bitrate = _safe_int(audio.get("bit_rate"))
    if not video_bitrate and format_bitrate:
        video_bitrate = max(0, format_bitrate - audio_bitrate)
    tags = audio.get("tags") if isinstance(audio.get("tags"), dict) else {}
    return normalize_media_profile({
        "width": video.get("width"),
        "height": video.get("height"),
        "video_codec": video.get("codec_name"),
        "video_bitrate": video_bitrate,
        "bit_depth": _bit_depth(video),
        "hdr": _hdr_label(video),
        "fps": _fps(video.get("avg_frame_rate") or video.get("r_frame_rate")),
        "audio_codec": audio.get("codec_name"),
        "audio_channels": audio.get("channels"),
        "audio_bitrate": audio_bitrate,
        "audio_sample_rate": audio.get("sample_rate"),
        "audio_language": tags.get("language"),
    })


def media_profile_from_jellyfin_item(item: dict | None) -> dict:
    raw = item if isinstance(item, dict) else {}
    profiles = []
    for source in raw.get("MediaSources") or []:
        if not isinstance(source, dict):
            continue
        streams = [stream for stream in (source.get("MediaStreams") or []) if isinstance(stream, dict)]
        video_streams = [stream for stream in streams if str(stream.get("Type") or "").casefold() == "video"]
        audio_streams = [stream for stream in streams if str(stream.get("Type") or "").casefold() == "audio"]
        if not video_streams:
            continue
        video = max(video_streams, key=lambda stream: (_safe_int(stream.get("Height")), _safe_int(stream.get("Width"))))
        audio = max(
            audio_streams,
            key=lambda stream: (_safe_int(stream.get("Channels")), _safe_int(stream.get("BitRate"))),
            default={},
        )
        video_range = str(video.get("VideoRangeType") or video.get("VideoRange") or "").casefold()
        transfer = str(video.get("ColorTransfer") or "").casefold()
        hdr = "sdr"
        if "dovi" in video_range or "dolby" in video_range:
            hdr = "dolby_vision"
        elif "hdr10" in video_range or transfer == "smpte2084":
            hdr = "hdr10"
        elif "hlg" in video_range or transfer == "arib-std-b67":
            hdr = "hlg"
        elif video_range and video_range not in {"sdr", "unknown"}:
            hdr = "hdr"
        profile = normalize_media_profile({
            "width": video.get("Width"),
            "height": video.get("Height"),
            "video_codec": video.get("Codec"),
            "video_bitrate": video.get("BitRate") or source.get("Bitrate"),
            "bit_depth": video.get("BitDepth"),
            "hdr": hdr,
            "fps": video.get("AverageFrameRate") or video.get("RealFrameRate"),
            "audio_codec": audio.get("Codec"),
            "audio_channels": audio.get("Channels"),
            "audio_bitrate": audio.get("BitRate"),
            "audio_sample_rate": audio.get("SampleRate"),
            "audio_language": audio.get("Language"),
        })
        profiles.append(profile)
    return max(profiles, key=media_quality_score, default=normalize_media_profile({}))


def probe_media_profile(
    source: str | Path,
    *,
    referer: str = "",
    origin: str = "",
    timeout: int = PROBE_TIMEOUT_SECONDS,
) -> tuple[dict, str]:
    """Read a bounded ffprobe sample from a local file or resolved stream."""
    value = str(source or "").strip()
    if not value:
        return normalize_media_profile({}), "leere Quelle"
    is_network = value.casefold().startswith(("http://", "https://"))
    if is_network:
        try:
            ensure_public_http_url(value)
        except UnsafeNetworkTarget as exc:
            return normalize_media_profile({}), f"unsicheres Netzwerkziel: {exc}"

    cmd = [
        "ffprobe",
        "-v", "error",
        "-probesize", str(PROBE_SIZE_BYTES),
        "-analyzeduration", str(ANALYZE_DURATION_US),
        "-show_entries",
        "stream=codec_type,codec_name,profile,width,height,pix_fmt,bits_per_raw_sample,bits_per_sample,color_transfer,color_primaries,color_space,avg_frame_rate,r_frame_rate,bit_rate,channels,channel_layout,sample_rate:stream_tags=language:format=bit_rate,duration",
        "-of", "json",
    ]
    if is_network:
        cmd += ["-rw_timeout", "15000000", "-user_agent", BROWSER_USER_AGENT]
        headers = []
        if referer:
            headers.append(f"Referer: {referer}")
        if origin:
            headers.append(f"Origin: {origin}")
        if headers:
            cmd += ["-headers", "\r\n".join(headers) + "\r\n"]
    cmd.append(value)
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(5, int(timeout)),
        )
    except FileNotFoundError:
        return normalize_media_profile({}), "ffprobe fehlt"
    except subprocess.TimeoutExpired:
        return normalize_media_profile({}), "ffprobe-Timeout"
    except OSError as exc:
        return normalize_media_profile({}), f"ffprobe nicht startbar: {exc}"
    if proc.returncode != 0:
        lines = (proc.stderr or "").strip().splitlines()
        return normalize_media_profile({}), (lines[-1][:200] if lines else f"ffprobe Code {proc.returncode}")
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return normalize_media_profile({}), "ffprobe lieferte ungültiges JSON"
    profile = media_profile_from_ffprobe(data)
    if profile["height"] <= 0 or not profile["video_codec"]:
        return profile, "kein verwertbarer Videostream"
    if not profile["audio_codec"]:
        return profile, "kein verwertbarer Audiostream"
    return profile, ""
