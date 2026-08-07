"""Authoritative quality handling for subscribed movie upgrades.

Provider quality labels are useful for choosing candidates, but they are not
allowed to become permanent truth about the file that actually reached the
library.  Jellyfin and ffprobe provide the observed resolution and can correct
stale or optimistic provider metadata on subsequent checks.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import unicodedata
from pathlib import Path

from application_services.runtime import (
    backend_value,
    import_backend_namespace,
    publish_service,
)
from providers.filmpalast import FilmpalastScraper

# Runtime service publication is intentionally invisible to static name resolution.
# ruff: noqa: F821

globals().update(import_backend_namespace())

_ORIGINAL_CHECK_MOVIE_SUBSCRIPTIONS = backend_value("check_movie_subscriptions")
_ORIGINAL_MOVIE_SUBSCRIPTION_FINISHED = backend_value("_movie_subscription_download_finished")
_ORIGINAL_FILMPALAST_PARSE_HOSTER_TEXT = FilmpalastScraper._parse_hoster_text


def _quality_label_from_text(value: str) -> str:
    """Return the strongest explicit resolution marker in arbitrary provider text."""
    text = " ".join(str(value or "").split()).upper()
    if not text:
        return ""
    if re.search(r"\b(?:2160P?|4K|UHD)\b", text):
        return "2160p"
    if re.search(r"\b(?:1440P?|QHD)\b", text):
        return "1440p"
    if re.search(r"\b(?:1080P?|FULL[ ._-]*HD|FHD)\b", text):
        return "1080p"
    if re.search(r"\b720P?\b", text):
        return "720p"
    if re.search(r"(?<!FULL[ ._-])\bHD\b", text):
        return "HD"
    if re.search(r"\b576P?\b", text):
        return "576p"
    if re.search(r"\b(?:480P?|SD|DVD)\b", text):
        return "480p"
    if re.search(r"\bCAM\b", text):
        return "CAM"
    if re.search(r"\bTS\b", text):
        return "TS"
    heights = [int(match) for match in re.findall(r"(?<!\d)(\d{3,4})\s*P?\b", text)]
    return f"{max(heights)}p" if heights else ""


def _filmpalast_parse_hoster_text(text: str):
    """Prefer explicit 4K/1080p markers over the generic word ``HD``."""
    name, old_quality, language = _ORIGINAL_FILMPALAST_PARSE_HOSTER_TEXT(text)
    return name, (_quality_label_from_text(text) or old_quality), language


# Filmpalast historically checked "HD" before "1080p" while parsing one
# hoster label.  Patch the class once at startup so subscriptions and manual
# downloads see the same corrected quality metadata.
FilmpalastScraper._parse_hoster_text = staticmethod(_filmpalast_parse_hoster_text)


def _norm_identity_title(value: str) -> str:
    try:
        normalized = _norm_title(value)
        if normalized:
            return normalized
    except Exception:
        pass
    ascii_title = (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "", ascii_title.casefold())


def _jellyfin_item_for_subscription(entry: dict, items: list[dict]) -> dict | None:
    tmdb_id = str(entry.get("tmdb_id") or "").strip()
    if tmdb_id:
        exact = next(
            (item for item in items if str(item.get("tmdb_id") or "").strip() == tmdb_id),
            None,
        )
        if exact:
            return exact

    wanted = _norm_identity_title(entry.get("title", ""))
    wanted_year = str(entry.get("year") or "").strip()
    if not wanted:
        return None
    for item in items:
        aliases = {
            _norm_identity_title(value)
            for value in (
                item.get("name", ""),
                item.get("original_title", ""),
                item.get("sort_name", ""),
            )
            if value
        }
        if wanted not in aliases:
            continue
        item_year = str(item.get("year") or "").strip()
        if wanted_year and item_year and wanted_year != item_year:
            continue
        return item
    return None


def _synchronize_observed_jellyfin_quality(entries: list[dict] | None) -> None:
    """Replace stale advertised ranks with Jellyfin's observed video height."""
    jf_client = get_jellyfin_client()
    if not jf_client.configured:
        return
    try:
        items = get_jellyfin_library(force=True)
    except Exception as exc:
        log(f"Film-Abo: Jellyfin-Qualität konnte nicht aktualisiert werden: {exc}", "warn")
        return
    if items is None:
        return

    with state.movie_subscriptions_lock:
        selected = list(entries if entries is not None else state.movie_subscriptions)
        for entry in selected:
            if not any(current is entry for current in state.movie_subscriptions):
                continue
            item = _jellyfin_item_for_subscription(entry, items)
            if not item:
                continue
            try:
                observed_rank = max(0, int(item.get("quality_rank") or 0))
            except (TypeError, ValueError):
                observed_rank = 0
            if observed_rank <= 0:
                continue
            old_rank = max(0, int(entry.get("current_quality_rank") or 0))
            if old_rank != observed_rank:
                log(
                    f"Film-Abo: korrigiere gespeicherte Qualität für «{entry.get('title', '')}» "
                    f"von {old_rank or '?'}p auf gemessene {observed_rank}p."
                )
            entry["current_quality_rank"] = observed_rank
            entry["current_quality"] = f"{observed_rank}p"
            entry["quality_source"] = "jellyfin"
            entry["quality_observed_at"] = time.time()
            if item.get("path"):
                entry["existing_path"] = str(item.get("path") or "")


def _probe_committed_file_quality(path: Path) -> tuple[int, str]:
    """Read the committed file instead of trusting the provider's advertised tag."""
    candidate = Path(path)
    if not candidate.is_file():
        try:
            siblings = [
                item for item in candidate.parent.glob(candidate.stem + ".*")
                if item.is_file()
                and item.suffix.casefold() in {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}
            ]
            if siblings:
                candidate = max(siblings, key=lambda item: item.stat().st_mtime_ns)
        except OSError:
            return 0, ""
    if not candidate.is_file():
        return 0, ""

    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=height,codec_name,pix_fmt,color_transfer",
        "-of", "json",
        str(candidate),
    ]
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return 0, ""
    if proc.returncode != 0:
        return 0, ""
    try:
        streams = (json.loads(proc.stdout or "{}") or {}).get("streams") or []
        stream = streams[0] if streams else {}
        height = max(0, int(stream.get("height") or 0))
    except (TypeError, ValueError, json.JSONDecodeError, IndexError):
        return 0, ""
    if height <= 0:
        return 0, ""

    parts = [f"{height}p"]
    codec = str(stream.get("codec_name") or "").strip().casefold()
    if codec in {"hevc", "h265"}:
        parts.append("HEVC")
    elif codec in {"av1"}:
        parts.append("AV1")
    elif codec in {"h264", "avc"}:
        parts.append("H.264")
    transfer = str(stream.get("color_transfer") or "").strip().casefold()
    if transfer == "smpte2084":
        parts.append("HDR")
    elif transfer == "arib-std-b67":
        parts.append("HLG")
    pix_fmt = str(stream.get("pix_fmt") or "").casefold()
    if "10" in pix_fmt:
        parts.append("10-bit")
    return height, " · ".join(parts)


def check_movie_subscriptions(entries: list[dict] | None = None) -> int:
    """Correct stale provider ranks before running the existing upgrade policy."""
    _synchronize_observed_jellyfin_quality(entries)
    return _ORIGINAL_CHECK_MOVIE_SUBSCRIPTIONS(entries)


def _movie_subscription_download_finished(movie_slug: str, out_path: Path, quality: str) -> None:
    """Book an upgrade from the committed file's real resolution whenever possible."""
    observed_rank, observed_label = _probe_committed_file_quality(Path(out_path))
    if observed_rank > 0:
        with state.movie_subscriptions_lock:
            for entry in state.movie_subscriptions:
                if (
                    entry.get("pending_slug") == movie_slug
                    or entry.get("source_slug") == movie_slug
                ):
                    entry["current_quality_rank"] = observed_rank
                    entry["current_quality"] = observed_label or f"{observed_rank}p"
                    entry["quality_source"] = "ffprobe"
                    entry["quality_observed_at"] = time.time()
                    break
        quality = f"{observed_rank}p"
    _ORIGINAL_MOVIE_SUBSCRIPTION_FINISHED(movie_slug, out_path, quality)
    if observed_rank > 0:
        with state.movie_subscriptions_lock:
            for entry in state.movie_subscriptions:
                if (
                    entry.get("source_slug") == movie_slug
                    or str(entry.get("existing_path") or "") == str(out_path)
                ):
                    entry["current_quality_rank"] = observed_rank
                    entry["current_quality"] = observed_label or f"{observed_rank}p"
                    entry["quality_source"] = "ffprobe"
                    entry["quality_observed_at"] = time.time()
                    break
        _persist_movie_subscriptions_background()


_SERVICE_EXPORTS = (
    "check_movie_subscriptions",
    "_movie_subscription_download_finished",
)
publish_service(globals(), _SERVICE_EXPORTS)
