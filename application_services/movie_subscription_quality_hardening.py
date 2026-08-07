"""Final hardening for measured movie-subscription quality.

This layer closes the remaining edge cases around language-aware audio ranking,
HLS variant selection, outbound ffprobe safety, stale-baseline races and bounded
quality inventories.  It deliberately patches only the subscription quality
seams that were introduced by the preceding runtime modules.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import api_library_router as library_router
import downloader
import media_quality
import application_services.movie_subscription_commit_guard as commit_guard
import application_services.movie_subscription_probe_optimizer as optimizer
import application_services.movie_subscription_probe_targeting as targeting
import application_services.movie_subscription_stream_quality as stream_quality
from network_guard import UnsafeNetworkTarget, ensure_public_http_url, safe_proxy_url

_LANGUAGE_ALIASES = {
    "de": "de",
    "deu": "de",
    "ger": "de",
    "german": "de",
    "deutsch": "de",
    "en": "en",
    "eng": "en",
    "english": "en",
    "englisch": "en",
    "ja": "ja",
    "jpn": "ja",
    "japanese": "ja",
    "japanisch": "ja",
}
_PROBE_BUDGET_SECONDS = max(
    20.0,
    min(300.0, float(os.environ.get("MOVIE_SUBSCRIPTION_PROBE_BUDGET_SECONDS", "75") or 75)),
)
_context = threading.local()
_inventory_lock = threading.RLock()
_inventory_deadline = 0.0

_ORIGINAL_CURRENT_PROFILE = stream_quality._current_profile
_ORIGINAL_PREPARE_UPGRADE = optimizer._prepare_movie_subscription_upgrade
_ORIGINAL_TARGETED_PROBE = targeting._probe_uncached
_ORIGINAL_VALIDATE_MEDIA = downloader.DownloadJob._validate_media
_ORIGINAL_COMMIT_FILE = downloader.DownloadJob._commit_file


def _language(value: str) -> str:
    raw = str(value or "").strip().casefold().replace("_", "-")
    if not raw:
        return ""
    head = raw.split("-", 1)[0]
    return _LANGUAGE_ALIASES.get(raw, _LANGUAGE_ALIASES.get(head, head))


def _entry_language(entry: dict | None) -> str:
    raw = entry if isinstance(entry, dict) else {}
    return _language(
        raw.get("preferred_audio_language")
        or raw.get("content_language")
        or raw.get("language")
        or "de"
    )


def _candidate_language(source, hoster=None) -> str:
    return _language(
        getattr(source, "content_language", "")
        or getattr(hoster, "language", "")
        or "de"
    )


@contextmanager
def _preferred_language(value: str):
    previous = getattr(_context, "preferred_language", "")
    _context.preferred_language = _language(value)
    try:
        yield
    finally:
        _context.preferred_language = previous


def _active_language(explicit: str = "") -> str:
    return _language(explicit) or _language(getattr(_context, "preferred_language", ""))


def _audio_language(stream: dict) -> str:
    tags = stream.get("tags") if isinstance(stream.get("tags"), dict) else {}
    return _language(tags.get("language") or stream.get("language") or "")


def _profile_from_ffprobe(info: dict | None, preferred_language: str = "") -> dict:
    data = info if isinstance(info, dict) else {}
    streams = [item for item in (data.get("streams") or []) if isinstance(item, dict)]
    videos = [
        item for item in streams
        if str(item.get("codec_type") or "").casefold() == "video"
    ]
    audios = [
        item for item in streams
        if str(item.get("codec_type") or "").casefold() == "audio"
    ]
    if not videos:
        return media_quality.normalize_media_profile({})

    video = max(
        videos,
        key=lambda item: (
            media_quality._safe_int(item.get("height")),
            media_quality._safe_int(item.get("width")),
            media_quality._safe_int(item.get("bit_rate")),
        ),
    )
    wanted = _language(preferred_language)
    audio = max(
        audios,
        key=lambda item: (
            1 if wanted and _audio_language(item) == wanted else 0,
            media_quality._safe_int(item.get("channels")),
            media_quality._AUDIO_CODEC_RANK.get(
                media_quality._codec(item.get("codec_name")),
                2 if item.get("codec_name") else 0,
            ),
            media_quality._safe_int(item.get("bit_rate")),
        ),
        default={},
    )

    format_bitrate = media_quality._safe_int((data.get("format") or {}).get("bit_rate"))
    video_bitrate = media_quality._safe_int(video.get("bit_rate"))
    audio_bitrate = media_quality._safe_int(audio.get("bit_rate"))
    if not video_bitrate and format_bitrate:
        video_bitrate = max(0, format_bitrate - audio_bitrate)
    return media_quality.normalize_media_profile(
        {
            "width": video.get("width"),
            "height": video.get("height"),
            "video_codec": video.get("codec_name"),
            "video_bitrate": video_bitrate,
            "bit_depth": media_quality._bit_depth(video),
            "hdr": media_quality._hdr_label(video),
            "fps": media_quality._fps(
                video.get("avg_frame_rate") or video.get("r_frame_rate")
            ),
            "audio_codec": audio.get("codec_name"),
            "audio_channels": audio.get("channels"),
            "audio_bitrate": audio_bitrate,
            "audio_sample_rate": audio.get("sample_rate"),
            "audio_language": _audio_language(audio),
        }
    )


def _profile_from_jellyfin(item: dict | None, preferred_language: str = "") -> dict:
    raw = item if isinstance(item, dict) else {}
    wanted = _language(preferred_language)
    profiles = []
    for source in raw.get("MediaSources") or []:
        if not isinstance(source, dict):
            continue
        streams = [
            stream for stream in (source.get("MediaStreams") or [])
            if isinstance(stream, dict)
        ]
        videos = [
            stream for stream in streams
            if str(stream.get("Type") or "").casefold() == "video"
        ]
        audios = [
            stream for stream in streams
            if str(stream.get("Type") or "").casefold() == "audio"
        ]
        if not videos:
            continue
        video = max(
            videos,
            key=lambda stream: (
                media_quality._safe_int(stream.get("Height")),
                media_quality._safe_int(stream.get("Width")),
                media_quality._safe_int(stream.get("BitRate")),
            ),
        )
        audio = max(
            audios,
            key=lambda stream: (
                1 if wanted and _language(stream.get("Language")) == wanted else 0,
                media_quality._safe_int(stream.get("Channels")),
                media_quality._AUDIO_CODEC_RANK.get(
                    media_quality._codec(stream.get("Codec")),
                    2 if stream.get("Codec") else 0,
                ),
                media_quality._safe_int(stream.get("BitRate")),
            ),
            default={},
        )
        video_range = str(
            video.get("VideoRangeType") or video.get("VideoRange") or ""
        ).casefold()
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
        profiles.append(
            media_quality.normalize_media_profile(
                {
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
                    "audio_language": _language(audio.get("Language")),
                }
            )
        )
    return max(
        profiles,
        key=media_quality.media_quality_score,
        default=media_quality.normalize_media_profile({}),
    )


def probe_media_profile(
    source: str | Path,
    *,
    referer: str = "",
    origin: str = "",
    timeout: int = media_quality.PROBE_TIMEOUT_SECONDS,
    preferred_language: str = "",
) -> tuple[dict, str]:
    """Probe a local file or stream with language-aware audio and safe proxying."""
    value = str(source or "").strip()
    if not value:
        return media_quality.normalize_media_profile({}), "leere Quelle"
    is_network = value.casefold().startswith(("http://", "https://"))
    env = os.environ.copy()
    if is_network:
        try:
            ensure_public_http_url(value)
        except UnsafeNetworkTarget as exc:
            return media_quality.normalize_media_profile({}), f"unsicheres Netzwerkziel: {exc}"
        proxy = safe_proxy_url()
        env.update(
            {
                "http_proxy": proxy,
                "https_proxy": proxy,
                "HTTP_PROXY": proxy,
                "HTTPS_PROXY": proxy,
                "NO_PROXY": "",
                "no_proxy": "",
            }
        )

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-probesize",
        str(media_quality.PROBE_SIZE_BYTES),
        "-analyzeduration",
        str(media_quality.ANALYZE_DURATION_US),
        "-show_entries",
        "stream=codec_type,codec_name,profile,width,height,pix_fmt,bits_per_raw_sample,bits_per_sample,color_transfer,color_primaries,color_space,avg_frame_rate,r_frame_rate,bit_rate,channels,channel_layout,sample_rate:stream_tags=language:format=bit_rate,duration",
        "-of",
        "json",
    ]
    if is_network:
        cmd += [
            "-rw_timeout",
            "15000000",
            "-user_agent",
            media_quality.BROWSER_USER_AGENT,
        ]
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
            env=env,
        )
    except FileNotFoundError:
        return media_quality.normalize_media_profile({}), "ffprobe fehlt"
    except subprocess.TimeoutExpired:
        return media_quality.normalize_media_profile({}), "ffprobe-Timeout"
    except OSError as exc:
        return media_quality.normalize_media_profile({}), f"ffprobe nicht startbar: {exc}"
    if proc.returncode != 0:
        lines = (proc.stderr or "").strip().splitlines()
        return media_quality.normalize_media_profile({}), (
            lines[-1][:200] if lines else f"ffprobe Code {proc.returncode}"
        )
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return media_quality.normalize_media_profile({}), "ffprobe lieferte ungültiges JSON"

    profile = _profile_from_ffprobe(data, _active_language(preferred_language))
    if profile["height"] <= 0 or not profile["video_codec"]:
        return profile, "kein verwertbarer Videostream"
    if not profile["audio_codec"]:
        return profile, "kein verwertbarer Audiostream"
    return profile, ""


def media_profile_from_jellyfin_item(item: dict | None) -> dict:
    return _profile_from_jellyfin(item, _active_language())


def _candidate_key(source, hoster, index: int) -> str:
    """Stable identity across hoster reordering and rotating signed query tokens."""
    del index
    payload = {
        "policy_version": 2,
        "provider": str(
            getattr(source, "provider", "")
            or stream_quality._movie_provider(source)
        ).casefold(),
        "source": stream_quality._stable_url(getattr(source, "url", "")),
        "hoster_url": stream_quality._stable_url(getattr(hoster, "url", "")),
        "hoster_name": str(getattr(hoster, "name", "") or "").strip().casefold(),
        "advertised_quality": str(
            getattr(hoster, "quality", "") or ""
        ).strip().casefold(),
        "language": _language(getattr(hoster, "language", "")),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return stream_quality.hashlib.sha256(encoded).hexdigest()


def _manifest_variants(text: str, base_url: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    audio_groups: dict[str, list[dict[str, Any]]] = {}
    for line in lines:
        if not line.upper().startswith("#EXT-X-MEDIA:"):
            continue
        attrs = optimizer._parse_attrs(line.split(":", 1)[1])
        if attrs.get("TYPE", "").upper() != "AUDIO":
            continue
        group = attrs.get("GROUP-ID", "")
        if not group:
            continue
        audio_groups.setdefault(group, []).append(
            {
                "audio_channels": optimizer._channels(attrs.get("CHANNELS", "")),
                "audio_language": _language(attrs.get("LANGUAGE", "")),
                "name": attrs.get("NAME", ""),
            }
        )

    wanted = _active_language()
    variants = []
    for index, line in enumerate(lines):
        if not line.upper().startswith("#EXT-X-STREAM-INF:"):
            continue
        attrs = optimizer._parse_attrs(line.split(":", 1)[1])
        uri = ""
        for following in lines[index + 1 :]:
            if following.startswith("#"):
                continue
            uri = optimizer.urljoin(base_url, following)
            break
        resolution = attrs.get("RESOLUTION", "")
        match = optimizer.re.match(r"^(\d+)x(\d+)$", resolution, optimizer.re.I)
        width = int(match.group(1)) if match else 0
        height = int(match.group(2)) if match else 0
        video_codec, audio_codec, bit_depth, hdr = optimizer._codec_profile(
            attrs.get("CODECS", "")
        )
        video_range = attrs.get("VIDEO-RANGE", "").strip().upper()
        if video_range == "PQ":
            hdr = "hdr10"
            bit_depth = max(bit_depth, 10)
        elif video_range == "HLG":
            hdr = "hlg"
            bit_depth = max(bit_depth, 10)

        renditions = audio_groups.get(attrs.get("AUDIO", ""), [])
        audio = max(
            renditions,
            key=lambda item: (
                1 if wanted and item.get("audio_language") == wanted else 0,
                int(item.get("audio_channels") or 0),
            ),
            default={},
        )
        try:
            bandwidth = int(
                attrs.get("AVERAGE-BANDWIDTH") or attrs.get("BANDWIDTH") or 0
            )
        except (TypeError, ValueError):
            bandwidth = 0
        try:
            fps = float(attrs.get("FRAME-RATE") or 0)
        except (TypeError, ValueError):
            fps = 0.0
        variants.append(
            {
                "uri": uri,
                "profile": media_quality.normalize_media_profile(
                    {
                        "width": width,
                        "height": height,
                        "video_codec": video_codec,
                        "video_bitrate": bandwidth,
                        "bit_depth": bit_depth,
                        "hdr": hdr or "sdr",
                        "fps": fps,
                        "audio_codec": audio_codec,
                        "audio_channels": int(audio.get("audio_channels") or 0),
                        "audio_language": str(audio.get("audio_language") or ""),
                    }
                ),
            }
        )
    return variants


def _selected_manifest_variant(
    stream_url: str,
    baseline: dict,
    target: str,
    *,
    referer: str = "",
    origin: str = "",
):
    text, error = optimizer._fetch_hls_manifest(
        stream_url,
        referer=referer,
        origin=origin,
    )
    if error:
        return {}, "", error, False
    variants = optimizer._manifest_variants(text, stream_url)
    if not variants:
        return {}, "", "HLS-Medienplaylist ohne Master-Varianten", False
    eligible = [
        item
        for item in variants
        if media_quality.media_profile_within_target(item["profile"], target)
    ]
    if not eligible:
        return {}, "", "Keine HLS-Variante innerhalb der Zielqualität", True
    selected = max(
        eligible,
        key=lambda item: (
            int(item["profile"].get("height") or 0),
            media_quality.media_quality_score(item["profile"]),
            int(item["profile"].get("width") or 0),
            int(item["profile"].get("video_bitrate") or 0),
        ),
    )
    profile = media_quality.normalize_media_profile(selected["profile"])
    baseline_height = int(
        media_quality.normalize_media_profile(baseline).get("height") or 0
    )
    if baseline_height and int(profile.get("height") or 0) < baseline_height:
        return (
            profile,
            str(selected.get("uri") or ""),
            "HLS-Master eindeutig unter vorhandener Auflösung",
            True,
        )
    return profile, str(selected.get("uri") or ""), "", False


def _budget_expired() -> bool:
    with _inventory_lock:
        return bool(_inventory_deadline and time.monotonic() >= _inventory_deadline)


def _probe_uncached(*args, **kwargs):
    source = args[0] if args else kwargs.get("source")
    hoster = args[1] if len(args) > 1 else kwargs.get("hoster")
    if _budget_expired():
        return None
    language = _candidate_language(source, hoster)
    with _preferred_language(language):
        result = _ORIGINAL_TARGETED_PROBE(*args, **kwargs)
    if _budget_expired():
        return None
    return result


def _prepare_movie_subscription_upgrade(entry: dict, sources: list):
    global _inventory_deadline
    with _inventory_lock:
        _inventory_deadline = time.monotonic() + _PROBE_BUDGET_SECONDS
    try:
        result = _ORIGINAL_PREPARE_UPGRADE(entry, sources)
        primary = result[0] if result else None
        if primary is not None:
            with stream_quality.state.movie_subscriptions_lock:
                entry["preferred_audio_language"] = _candidate_language(
                    primary,
                    primary.hosters[0] if getattr(primary, "hosters", None) else None,
                )
        return result
    finally:
        with _inventory_lock:
            _inventory_deadline = 0.0


def _current_profile(entry: dict) -> dict:
    with _preferred_language(_entry_language(entry)):
        return _ORIGINAL_CURRENT_PROFILE(entry)


def _subscription_entry(slug: str) -> dict | None:
    if not slug:
        return None
    with stream_quality.state.movie_subscriptions_lock:
        return next(
            (
                entry
                for entry in stream_quality.state.movie_subscriptions
                if entry.get("pending_slug") == slug
                or entry.get("source_slug") == slug
                or entry.get("key") == slug
            ),
            None,
        )


def _stronger_profile(first: dict, second: dict) -> dict:
    a = media_quality.normalize_media_profile(first)
    b = media_quality.normalize_media_profile(second)
    if not a.get("height"):
        return b
    if not b.get("height"):
        return a
    return b if media_quality.media_profile_is_better(b, a) else a


def _validate_media(self, path: Path):
    entry = _subscription_entry(str(self.queue_slug or ""))
    if entry is not None and getattr(self, "_subscription_quality_baseline", None):
        fresh = _current_profile(entry)
        self._subscription_quality_baseline = _stronger_profile(
            getattr(self, "_subscription_quality_baseline", {}),
            fresh,
        )
    with _preferred_language(
        self.content_language
        or _entry_language(entry)
        if entry is not None
        else self.content_language
    ):
        return _ORIGINAL_VALIDATE_MEDIA(self, path)


def _commit_file(self, source: Path, target: Path):
    entry = _subscription_entry(str(self.queue_slug or ""))
    baseline = media_quality.normalize_media_profile(
        getattr(self, "_subscription_quality_baseline", {})
    )
    if entry is not None and baseline.get("height"):
        fresh = _current_profile(entry)
        baseline = _stronger_profile(baseline, fresh)
        candidate = media_quality.normalize_media_profile(
            getattr(self, "_subscription_quality_actual", {})
        )
        if not candidate.get("height"):
            with _preferred_language(self.content_language or _entry_language(entry)):
                candidate, error = probe_media_profile(source)
            if error:
                raise RuntimeError(
                    f"Qualitätsprüfung direkt vor Veröffentlichung fehlgeschlagen: {error}"
                )
        if not media_quality.media_profile_is_better(candidate, baseline):
            self.failure_kind = "quality"
            raise RuntimeError(
                "Kein tatsächliches Qualitäts-Upgrade gegenüber der aktuell "
                f"vorhandenen Datei: {media_quality.media_profile_label(candidate)} "
                f"ist nicht besser als {media_quality.media_profile_label(baseline)}"
            )
        self._subscription_quality_baseline = baseline
        self._subscription_quality_actual = candidate
    return _ORIGINAL_COMMIT_FILE(self, source, target)


# Patch the exact module globals used by the existing subscription layers.
media_quality.probe_media_profile = probe_media_profile
stream_quality.probe_media_profile = probe_media_profile
stream_quality.media_profile_from_jellyfin_item = media_profile_from_jellyfin_item
stream_quality._current_profile = _current_profile
stream_quality._candidate_key = _candidate_key
optimizer._manifest_variants = _manifest_variants
targeting._selected_manifest_variant = _selected_manifest_variant
targeting.probe_media_profile = probe_media_profile
targeting._probe_uncached = _probe_uncached
optimizer._probe_uncached = _probe_uncached
optimizer._prepare_movie_subscription_upgrade = _prepare_movie_subscription_upgrade
commit_guard.probe_media_profile = probe_media_profile

if not getattr(downloader.DownloadJob, "_royal_quality_hardening_patched", False):
    downloader.DownloadJob._validate_media = _validate_media
    downloader.DownloadJob._commit_file = _commit_file
    downloader.DownloadJob._royal_quality_hardening_patched = True

# The router keeps local globals for these functions, so update them explicitly.
library_router._prepare_movie_subscription_upgrade = _prepare_movie_subscription_upgrade
