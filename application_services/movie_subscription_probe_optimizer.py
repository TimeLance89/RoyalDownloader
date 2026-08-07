"""Efficient manifest-first probing for movie-subscription quality inventory.

The measured inventory remains authoritative, but HLS masters are used as a
cheap first stage. Obvious non-upgrades are rejected from a tiny manifest read,
while plausible upgrades are deep-probed with bounded concurrency. Subscription
downloads also select the measured target height instead of the global 1080p
preference used by normal downloads.
"""

from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from typing import Any
from urllib.parse import urljoin

from curl_cffi import requests as cr

import api_library_router as library_router
import application_services.movie_subscription_stream_quality as stream_quality
import application_services.source_resolution as source_resolution
import downloader
from application_services.runtime import publish_service
from media_quality import (
    media_profile_is_better,
    media_profile_label,
    media_profile_within_target,
    media_quality_score,
    normalize_media_profile,
    probe_media_profile,
)
from network_guard import UnsafeNetworkTarget, request_proxy_kwargs

_MANIFEST_MAX_BYTES = 256 * 1024
_MANIFEST_TIMEOUT_SECONDS = 8
_MAX_PROBE_WORKERS = 4

_ORIGINAL_DOWNLOAD_YTDLP = downloader.DownloadJob._download_ytdlp


def _parse_attrs(value: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    pattern = re.compile(r"([A-Z0-9-]+)=(\"[^\"]*\"|[^,]*)", re.I)
    for match in pattern.finditer(value or ""):
        raw = match.group(2).strip()
        if len(raw) >= 2 and raw[0] == raw[-1] == '"':
            raw = raw[1:-1]
        attrs[match.group(1).upper()] = raw
    return attrs


def _codec_profile(codecs: str) -> tuple[str, str, int, str]:
    video = ""
    audio = ""
    depth = 0
    hdr = ""
    for token in (part.strip().casefold() for part in str(codecs or "").split(",")):
        if not token:
            continue
        if token.startswith(("avc1", "avc3")):
            video = video or "h264"
        elif token.startswith(("hvc1", "hev1")):
            video = video or "hevc"
            if re.match(r"^(?:hvc1|hev1)\.2(?:\.|$)", token):
                depth = max(depth, 10)
        elif token.startswith("av01"):
            video = video or "av1"
        elif token.startswith(("vp09", "vp9")):
            video = video or "vp9"
        elif token.startswith(("dvhe", "dvh1", "dva1", "dvav")):
            video = video or "hevc"
            depth = max(depth, 10)
            hdr = "dolby_vision"
        elif token.startswith("mp4a"):
            audio = audio or "aac"
        elif token.startswith(("ec-3", "ec3")):
            audio = audio or "eac3"
        elif token.startswith(("ac-3", "ac3")):
            audio = audio or "ac3"
        elif token.startswith("opus"):
            audio = audio or "opus"
        elif token.startswith("flac"):
            audio = audio or "flac"
    return video, audio, depth, hdr


def _channels(value: str) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else 0


def _manifest_variants(text: str, base_url: str) -> list[dict[str, Any]]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    audio_groups: dict[str, dict[str, Any]] = {}
    for line in lines:
        if not line.upper().startswith("#EXT-X-MEDIA:"):
            continue
        attrs = _parse_attrs(line.split(":", 1)[1])
        if attrs.get("TYPE", "").upper() != "AUDIO":
            continue
        group = attrs.get("GROUP-ID", "")
        if not group:
            continue
        current = audio_groups.setdefault(group, {})
        current["audio_channels"] = max(
            int(current.get("audio_channels") or 0),
            _channels(attrs.get("CHANNELS", "")),
        )
        if not current.get("audio_language") and attrs.get("LANGUAGE"):
            current["audio_language"] = attrs["LANGUAGE"].casefold()

    variants: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if not line.upper().startswith("#EXT-X-STREAM-INF:"):
            continue
        attrs = _parse_attrs(line.split(":", 1)[1])
        uri = ""
        for following in lines[index + 1 :]:
            if following.startswith("#"):
                continue
            uri = urljoin(base_url, following)
            break
        resolution = attrs.get("RESOLUTION", "")
        match = re.match(r"^(\d+)x(\d+)$", resolution, re.I)
        width = int(match.group(1)) if match else 0
        height = int(match.group(2)) if match else 0
        video_codec, audio_codec, bit_depth, hdr = _codec_profile(attrs.get("CODECS", ""))
        video_range = attrs.get("VIDEO-RANGE", "").strip().upper()
        if video_range == "PQ":
            hdr = "hdr10"
            bit_depth = max(bit_depth, 10)
        elif video_range == "HLG":
            hdr = "hlg"
            bit_depth = max(bit_depth, 10)
        group = audio_groups.get(attrs.get("AUDIO", ""), {})
        try:
            bandwidth = int(attrs.get("AVERAGE-BANDWIDTH") or attrs.get("BANDWIDTH") or 0)
        except (TypeError, ValueError):
            bandwidth = 0
        try:
            fps = float(attrs.get("FRAME-RATE") or 0)
        except (TypeError, ValueError):
            fps = 0.0
        variants.append(
            {
                "uri": uri,
                "profile": normalize_media_profile(
                    {
                        "width": width,
                        "height": height,
                        "video_codec": video_codec,
                        "video_bitrate": bandwidth,
                        "bit_depth": bit_depth,
                        "hdr": hdr or "sdr",
                        "fps": fps,
                        "audio_codec": audio_codec,
                        "audio_channels": int(group.get("audio_channels") or 0),
                        "audio_language": str(group.get("audio_language") or ""),
                    }
                ),
            }
        )
    return variants


def _fetch_hls_manifest(url: str, *, referer: str = "", origin: str = "") -> tuple[str, str]:
    headers = {
        "User-Agent": downloader.BROWSER_USER_AGENT,
        "Accept": "application/vnd.apple.mpegurl,application/x-mpegURL,text/plain,*/*;q=0.8",
        "Range": f"bytes=0-{_MANIFEST_MAX_BYTES - 1}",
    }
    if referer:
        headers["Referer"] = referer
    if origin:
        headers["Origin"] = origin
    try:
        response = cr.get(
            url,
            headers=headers,
            timeout=_MANIFEST_TIMEOUT_SECONDS,
            allow_redirects=True,
            stream=True,
            impersonate="chrome136",
            **request_proxy_kwargs(url),
        )
        response.raise_for_status()
        payload = bytearray()
        try:
            for chunk in response.iter_content(chunk_size=16 * 1024):
                if not chunk:
                    continue
                remaining = _MANIFEST_MAX_BYTES - len(payload)
                if remaining <= 0:
                    break
                payload.extend(chunk[:remaining])
                if len(payload) >= _MANIFEST_MAX_BYTES:
                    break
        finally:
            response.close()
    except UnsafeNetworkTarget as exc:
        return "", f"unsicheres Manifest-Ziel: {exc}"
    except Exception as exc:
        return "", f"Manifest nicht lesbar: {str(exc)[:160]}"
    text = bytes(payload).decode("utf-8", errors="replace")
    if "#EXTM3U" not in text[:2048].upper():
        return "", "kein HLS-Manifest"
    return text, ""


def _manifest_preflight(
    stream_url: str,
    stream_type: str,
    baseline: dict,
    target: str,
    *,
    referer: str = "",
    origin: str = "",
) -> tuple[dict, str, bool]:
    if stream_type != "hls" and ".m3u8" not in stream_url.casefold():
        return {}, "", False
    text, error = _fetch_hls_manifest(stream_url, referer=referer, origin=origin)
    if error:
        return {}, error, False
    variants = _manifest_variants(text, stream_url)
    if not variants:
        return {}, "HLS-Medienplaylist ohne Master-Varianten", False
    eligible = [
        item
        for item in variants
        if media_profile_within_target(item["profile"], target)
    ]
    if not eligible:
        return {}, "Keine HLS-Variante innerhalb der Zielqualität", True
    selected = max(
        eligible,
        key=lambda item: (
            int(item["profile"].get("height") or 0),
            int(item["profile"].get("width") or 0),
            int(item["profile"].get("video_bitrate") or 0),
        ),
    )
    profile = normalize_media_profile(selected["profile"])
    baseline_height = int(normalize_media_profile(baseline).get("height") or 0)
    if baseline_height and int(profile.get("height") or 0) < baseline_height:
        return profile, "HLS-Master eindeutig unter vorhandener Auflösung", True
    return profile, "", False


def _store_manifest_skip(cache: dict, key: str, profile: dict, reason: str) -> None:
    cache[key] = {
        "checked_at": time.time(),
        "ok": True,
        "profile": normalize_media_profile(profile),
        "error": "",
        "manifest_only": True,
        "skip_reason": str(reason or "")[:160],
    }


def _probe_uncached(
    source,
    hoster,
    index: int,
    cache: dict,
    cache_lock: threading.RLock,
    unsupported_domains: set,
    barren: set,
    baseline: dict,
    target: str,
    counters: dict[str, int],
    counter_lock: threading.RLock,
):
    key = stream_quality._candidate_key(source, hoster, index)
    clone = replace(source, hosters=[hoster])
    with stream_quality.state.hoster_extract_lock:
        result = stream_quality._ORIGINAL_EXTRACT_FROM_MOVIE(
            clone,
            unsupported_domains,
            barren_hoster_urls=barren,
        )
    if not result.stream_info:
        with cache_lock:
            stream_quality._store_probe(
                cache,
                key,
                profile=None,
                error="Hoster nicht auflösbar oder nicht ladbar",
            )
        return None

    stream_url, stream_type = result.stream_info
    manifest_profile, manifest_reason, skip_deep = _manifest_preflight(
        stream_url,
        str(stream_type or "").casefold(),
        baseline,
        target,
        referer=result.referer,
        origin=result.origin,
    )
    if manifest_profile or manifest_reason:
        with counter_lock:
            counters["manifest"] += 1
    if skip_deep:
        with cache_lock:
            _store_manifest_skip(cache, key, manifest_profile, manifest_reason)
        with counter_lock:
            counters["manifest_skipped"] += 1
        return None

    with counter_lock:
        counters["deep"] += 1
    profile, error = probe_media_profile(
        stream_url,
        referer=result.referer,
        origin=result.origin,
    )
    if error:
        with cache_lock:
            stream_quality._store_probe(cache, key, profile=None, error=error)
        return None
    profile = normalize_media_profile(profile)
    with cache_lock:
        stream_quality._store_probe(cache, key, profile=profile)
    clone._quality_inventory_candidate = True
    clone._probed_media_profile = profile
    clone._quality_pre_resolved = stream_quality._pre_resolved_payload(result, profile)
    return clone


def _prepare_movie_subscription_upgrade(entry: dict, sources: list):
    """Inventory all provider/hoster slots with bounded selective deep probes."""
    baseline = stream_quality._current_profile(entry)
    target = stream_quality.normalize_movie_quality(entry.get("target_quality"))
    with stream_quality.state.movie_subscriptions_lock:
        entry.pop("_upgrade_candidate_signature", None)
        entry.pop("_upgrade_candidate_from_rank", None)
        entry.pop("_upgrade_candidate_advertised_rank", None)
        raw_cache = entry.get(stream_quality._PROBE_CACHE_FIELD)
        cache = dict(raw_cache) if isinstance(raw_cache, dict) else {}

    cache_lock = threading.RLock()
    counter_lock = threading.RLock()
    counters = {"manifest": 0, "manifest_skipped": 0, "deep": 0}
    unsupported_domains: set = set()
    barren: set = set()
    candidates = []
    provider_count = 0
    hoster_count = 0
    work = []

    for source_index, source in enumerate(sources or []):
        provider_count += 1
        for hoster_index, hoster in enumerate(list(getattr(source, "hosters", []) or [])):
            if not getattr(hoster, "url", ""):
                continue
            hoster_count += 1
            key = stream_quality._candidate_key(source, hoster, hoster_index)
            with cache_lock:
                cached, known = stream_quality._cached_probe(cache, key, time.time())
            if known:
                if cached is None:
                    continue
                clone = replace(source, hosters=[hoster])
                clone._quality_inventory_candidate = True
                clone._probed_media_profile = cached
                candidates.append((source_index, hoster_index, clone))
                continue
            work.append((source_index, hoster_index, source, hoster))

    if work:
        workers = min(_MAX_PROBE_WORKERS, len(work))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="movie-quality") as executor:
            futures = {
                executor.submit(
                    _probe_uncached,
                    source,
                    hoster,
                    hoster_index,
                    cache,
                    cache_lock,
                    unsupported_domains,
                    barren,
                    baseline,
                    target,
                    counters,
                    counter_lock,
                ): (source_index, hoster_index)
                for source_index, hoster_index, source, hoster in work
            }
            for future in as_completed(futures):
                source_index, hoster_index = futures[future]
                try:
                    candidate = future.result()
                except Exception as exc:
                    stream_quality.log(f"Film-Abo: Qualitätsprobe fehlgeschlagen: {exc}", "warn")
                    continue
                if candidate is not None:
                    candidates.append((source_index, hoster_index, candidate))

    ranked = []
    for source_index, hoster_index, candidate in candidates:
        profile = normalize_media_profile(getattr(candidate, "_probed_media_profile", {}))
        if not media_profile_within_target(profile, target):
            continue
        if not media_profile_is_better(profile, baseline):
            continue
        ranked.append(
            (
                media_quality_score(profile),
                -source_index,
                -hoster_index,
                candidate,
                profile,
            )
        )

    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    cache = stream_quality._trim_probe_cache(cache)
    now = time.time()
    with stream_quality.state.movie_subscriptions_lock:
        entry[stream_quality._PROBE_CACHE_FIELD] = cache
        entry[stream_quality._BASELINE_FIELD] = normalize_media_profile(baseline)
        entry[stream_quality._PROBE_CHECKED_AT_FIELD] = now
        entry["upgrade_probe_provider_count"] = provider_count
        entry["upgrade_probe_hoster_count"] = hoster_count
        entry["upgrade_probe_manifest_count"] = counters["manifest"]
        entry["upgrade_probe_manifest_skipped_count"] = counters["manifest_skipped"]
        entry["upgrade_probe_deep_count"] = counters["deep"]
        if ranked:
            entry[stream_quality._AVAILABLE_PROFILE_FIELD] = normalize_media_profile(ranked[0][4])
        else:
            entry.pop(stream_quality._AVAILABLE_PROFILE_FIELD, None)
    if not ranked:
        return None, [], 0, ""

    primary = ranked[0][3]
    fallbacks = [item[3] for item in ranked[1:]]
    best_profile = ranked[0][4]
    label = media_profile_label(best_profile)
    stream_quality.log(
        f"Film-Abo: Qualitätsinventur «{entry.get('title', '')}»: "
        f"{provider_count} Anbieter / {hoster_count} Hoster; "
        f"{counters['manifest']} Manifest-Checks, "
        f"{counters['manifest_skipped']} Tiefenproben eingespart, "
        f"{counters['deep']} Tiefenproben; beste Quelle {label} gegenüber "
        f"{media_profile_label(baseline)}."
    )
    return primary, fallbacks, int(best_profile.get("height") or 0), label


def _subscription_height(job) -> int:
    slug = str(getattr(job, "queue_slug", "") or "")
    if not slug:
        return 0
    with stream_quality.state.movie_subscriptions_lock:
        for entry in stream_quality.state.movie_subscriptions:
            if entry.get("pending_slug") != slug:
                continue
            profile = normalize_media_profile(entry.get(stream_quality._AVAILABLE_PROFILE_FIELD))
            return int(profile.get("height") or 0)
    return 0


def _download_ytdlp_for_height(self, height: int, concurrent_fragments=None):
    if self._cancelled:
        return False, "Abgebrochen"
    self.failure_kind = ""
    self.average_speed_bps = 0.0
    try:
        downloader.ensure_public_http_url(self.stream_url)
    except downloader.UnsafeNetworkTarget as exc:
        return False, f"Unsicheres Netzwerkziel: {exc}"
    fragments = int(concurrent_fragments or downloader.HLS_CONCURRENT_FRAGMENTS)
    prepared, detail = self._prepare_staging()
    if not prepared:
        return False, f"Staging nicht nutzbar: {detail}"
    cmd = [
        downloader.sys.executable,
        "-m",
        "yt_dlp",
        "--no-warnings",
        "--newline",
        "--socket-timeout",
        "15",
        "--retries",
        "2",
        "--fragment-retries",
        "2",
        "--abort-on-unavailable-fragments",
        "--file-access-retries",
        "1",
        "--retry-sleep",
        "1",
        "--concurrent-fragments",
        str(fragments),
        "--progress-delta",
        "1",
        "--output",
        str(self.staging_path),
        "--merge-output-format",
        "mp4",
        "-S",
        f"res:{int(height)},ext:mp4:m4a",
        "--ffmpeg-location",
        "ffmpeg",
        "--extractor-args",
        "generic:impersonate",
        "--user-agent",
        downloader.BROWSER_USER_AGENT,
        "--proxy",
        downloader.safe_proxy_url(),
    ]
    if (
        downloader.MP4_HTTP_CHUNK_SIZE
        and self.stream_type == "mp4"
        and ".m3u8" not in self.stream_url.lower()
    ):
        cmd += ["--http-chunk-size", downloader.MP4_HTTP_CHUNK_SIZE]
    if self.referer:
        cmd += ["--referer", self.referer]
    if self.origin:
        cmd += ["--add-header", f"Origin:{self.origin}"]
    cmd.append(self.stream_url)
    downloader.logger.debug("yt-dlp subscription cmd: %s", " ".join(cmd))
    popen_kwargs = {}
    if os.name == "nt":
        popen_kwargs["creationflags"] = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    else:
        popen_kwargs["start_new_session"] = True
    if self._cancelled:
        return False, "Abgebrochen"
    self._proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        **popen_kwargs,
    )
    output_queue: "queue.Queue[str | None]" = queue.Queue()

    def _read_output():
        try:
            for raw_line in self._proc.stdout:
                output_queue.put(raw_line)
        finally:
            output_queue.put(None)

    threading.Thread(target=_read_output, daemon=True).start()
    last_error = ""
    first_real_error = ""
    fragment_abort = False
    last_output = time.monotonic()
    stalled = False
    slow = False
    speed_watchdog = None if self.allow_slow else downloader._LowSpeedWatchdog()
    while True:
        try:
            raw_line = output_queue.get(timeout=1)
        except queue.Empty:
            if self._cancelled:
                break
            if time.monotonic() - last_output > downloader.NO_OUTPUT_TIMEOUT_SECONDS:
                stalled = True
                self._terminate_process_tree()
                break
            continue
        if raw_line is None:
            break
        last_output = time.monotonic()
        line = raw_line.strip()
        if not line:
            continue
        if self._is_ytdlp_error(line):
            cleaned = self._clean_ytdlp_error(line)
            last_error = cleaned
            low_error = cleaned.casefold()
            if any(marker in low_error for marker in downloader._YTDLP_FRAGMENT_ERROR_MARKERS):
                fragment_abort = True
            if not first_real_error and not any(
                marker in low_error for marker in downloader._YTDLP_NOISE_ERROR_MARKERS
            ):
                first_real_error = cleaned
        speed_bps = self._parse_speed_bps(line)
        if speed_bps is not None:
            self.average_speed_bps = (
                speed_bps
                if self.average_speed_bps <= 0
                else self.average_speed_bps * 0.8 + speed_bps * 0.2
            )
            if speed_watchdog and speed_watchdog.observe(speed_bps):
                slow = True
                self.failure_kind = "slow"
                self.on_progress(
                    self._parse_progress(line),
                    f"Stream zu langsam ({self._format_speed(self.average_speed_bps)}) – wechsle Anbieter …",
                )
                self._terminate_process_tree()
                break
        pct = self._parse_progress(line)
        self._update_progress_metrics(line, pct)
        self.on_progress(pct, self._friendly_ytdlp_message(line))

    try:
        self._proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        self._terminate_process_tree(force=True)
        self._proc.wait()
    if self._cancelled:
        return False, "Abgebrochen"
    if slow:
        return False, f"{downloader.SLOW_FAILURE_PREFIX} ({self._format_speed(self.average_speed_bps)})"
    if stalled:
        return False, "Stream lieferte zu lange keinen Fortschritt"
    if self._proc.returncode == 0:
        return True, "yt-dlp OK"
    if fragment_abort:
        self.failure_kind = "fragment"
    detail = first_real_error or last_error or f"Prozesscode {self._proc.returncode}"
    return False, f"Stream nicht erreichbar: {detail}"


def _quality_aware_download_ytdlp(self, concurrent_fragments=None):
    height = _subscription_height(self)
    if height <= 0 or height == 1080:
        return _ORIGINAL_DOWNLOAD_YTDLP(self, concurrent_fragments=concurrent_fragments)
    return _download_ytdlp_for_height(self, height, concurrent_fragments=concurrent_fragments)


def _install_download_selector() -> None:
    if getattr(downloader.DownloadJob, "_royal_subscription_height_selector", False):
        return
    downloader.DownloadJob._download_ytdlp = _quality_aware_download_ytdlp
    downloader.DownloadJob._royal_subscription_height_selector = True
    source_resolution.DownloadJob = downloader.DownloadJob


library_router._prepare_movie_subscription_upgrade = _prepare_movie_subscription_upgrade
_install_download_selector()

_SERVICE_EXPORTS = ("_prepare_movie_subscription_upgrade",)
publish_service(globals(), _SERVICE_EXPORTS)
