"""Canonical media identity, legacy matching, and filesystem naming.

Royal historically used provider display titles directly for TMDB lookups,
Jellyfin matching, and final filenames.  That made harmless filesystem
sanitization (``?``, ``:``, ``/``) leak a ``~<hash>`` suffix into Jellyfin and
made localized/provider-specific titles unnecessarily fragile.

This post-service policy keeps the existing public contracts intact while
centralizing three concerns:

* resilient TMDB title aliases for provider/localized names,
* backwards-compatible recognition of Royal's old ``~<hash>`` filenames,
* readable media filenames that only add an identity suffix for real length or
  collision constraints, never merely because punctuation had to be removed.
"""

from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path
from typing import Iterable, Optional

import downloader as _downloader_module
import jellyfin_client as _jellyfin_module
import tmdb_client as _tmdb_module

from application_services.runtime import import_backend_namespace, publish_service


globals().update(import_backend_namespace())


_VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"}
_LEGACY_ID_SUFFIX_RE = re.compile(r"~[0-9a-f]{8}(?:-\d+)?$", re.IGNORECASE)
_MEDIA_EXTENSION_RE = re.compile(r"\.(?:mp4|mkv|webm|avi|mov|m4v)$", re.IGNORECASE)
_SOURCE_SUFFIX_RE = re.compile(r"\s*\[[^\]]+\]\s*$")
_TRAILING_YEAR_RE = re.compile(r"\s*[\(\[]?(?:19|20)\d{2}[\)\]]?\s*$")
_QUALITY_SUFFIX_RE = re.compile(
    r"(?:[. _-]+(?:2160p|1080p|720p|576p|480p|4k|uhd|full[. _-]*hd|"
    r"bluray|blu[. _-]*ray|web[. _-]*dl|webrip|hdr|dv|dolby(?:vision|sr)?|"
    r"x26[45]|h26[45]|hevc|av1|remux))+$",
    re.IGNORECASE,
)
_INVALID_FILENAME_CHARS = set('\\/:*?"<>|')
_WINDOWS_RESERVED_NAMES = {
    "con", "prn", "aux", "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
_FILENAME_COMPONENT_MAX_BYTES = 180


_ORIGINAL_BUILD_FILENAME = _downloader_module.build_filename
_ORIGINAL_BUILD_MOVIE_FILENAME = _downloader_module.build_movie_filename
_ORIGINAL_JELLYFIN_NORMALIZE = _jellyfin_module._normalize
_ORIGINAL_JELLYFIN_TITLE_TOKENS = _jellyfin_module._title_tokens
_ORIGINAL_MOVIE_SUMMARY = _tmdb_module.TMDBClient.movie_summary
_ORIGINAL_SERIES_SUMMARY = _tmdb_module.TMDBClient.series_summary
_ORIGINAL_SERIES = _tmdb_module.TMDBClient.series
_ORIGINAL_SERIES_MATCHES_ID = _tmdb_module.TMDBClient.series_matches_id


def strip_legacy_identity_suffix(value: str) -> str:
    """Remove Royal's historical collision/sanitization suffix from a title."""
    text = str(value or "").strip()
    text = _MEDIA_EXTENSION_RE.sub("", text)
    return _LEGACY_ID_SUFFIX_RE.sub("", text).rstrip(" ._-~")


def _path_stem(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return Path(text).stem
    except (OSError, ValueError):
        return text


def normalize_media_identity_title(value: str) -> str:
    """Stable comparison key for provider, TMDB, Jellyfin, and legacy paths."""
    text = strip_legacy_identity_suffix(_path_stem(value))
    text = _SOURCE_SUFFIX_RE.sub("", text)
    text = _QUALITY_SUFFIX_RE.sub("", text)
    text = _TRAILING_YEAR_RE.sub("", text)
    ascii_text = (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "", ascii_text.casefold())


def _clean_query_seed(title: str, media_type: str) -> str:
    value = " ".join(str(title or "").split()).strip()
    value = _SOURCE_SUFFIX_RE.sub("", value).strip()
    value = strip_legacy_identity_suffix(value)
    value = _MEDIA_EXTENSION_RE.sub("", value).strip()
    if media_type == "movie":
        try:
            value = clean_movie_title(value)
        except Exception:
            pass
    value = re.sub(
        r"^(?:english|englisch|german|deutsch|multi(?:language)?|ov|o-ton)"
        r"(?:\s+(?:dub|sub|dl))?\s*[\\/|:_-]+\s*",
        "",
        value,
        flags=re.IGNORECASE,
    ).strip()
    if media_type == "series":
        value = re.sub(
            r"\s+(?:staffel|season)\s*\d+\s*$", "", value, flags=re.IGNORECASE,
        ).strip()
    value = _TRAILING_YEAR_RE.sub("", value).strip()
    return value


def media_title_variants(title: str, media_type: str = "movie") -> tuple[str, ...]:
    """Return conservative aliases used only when the provider title misses.

    The original title is always tried first.  Later variants repair common
    provider/localization forms such as ``Sayara - Der Racheengel`` and
    ``Transformers 5: The Last Knight`` without hard-coding individual media.
    """
    seed = _clean_query_seed(title, media_type)
    variants: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        candidate = " ".join(str(value or "").split()).strip(" -:|_/\\")
        key = candidate.casefold()
        if len(candidate) < 2 or key in seen:
            return
        seen.add(key)
        variants.append(candidate)

    add(seed)

    numbered = re.match(r"^(.+?)\s+([1-9]|10)\s*:\s*(.+)$", seed)
    if numbered:
        franchise, _number, subtitle = numbered.groups()
        add(f"{franchise}: {subtitle}")
        if len(subtitle) >= 4:
            add(subtitle)

    dash_parts = re.split(r"\s+[\-–—]\s+", seed, maxsplit=1)
    if len(dash_parts) == 2:
        left, right = (part.strip() for part in dash_parts)
        add(f"{left}: {right}")
        if len(left) >= 4:
            add(left)
        if len(right) >= 4:
            add(right)

    if ":" in seed:
        left, right = (part.strip() for part in seed.split(":", 1))
        add(f"{left} - {right}")
        if len(left) >= 4:
            add(left)
        if len(right) >= 4:
            add(right)

    # A provider may simply omit punctuation around a franchise subtitle.
    punctuation_flat = re.sub(r"\s*[:|]\s*", " ", seed)
    add(punctuation_flat)

    return tuple(variants[:8])


def _cached_summary(client, cache_name: str, key):
    cache = getattr(client, cache_name, None)
    if not isinstance(cache, dict):
        return None
    with client._lock:
        return cache.get(key)


def _remember_summary(client, cache_name: str, key, value) -> None:
    cache = getattr(client, cache_name, None)
    if not isinstance(cache, dict):
        return
    with client._lock:
        cache[key] = value


def _identity_movie_summary(self, title: str, year: str = "") -> Optional[dict]:
    original_key = (_tmdb_module._normalize(_clean_query_seed(title, "movie")), str(year or ""))
    cached = _cached_summary(self, "_movie_summary_cache", original_key)
    if cached is not None:
        return cached
    for variant in media_title_variants(title, "movie"):
        result = _ORIGINAL_MOVIE_SUMMARY(self, variant, year)
        if result:
            _remember_summary(self, "_movie_summary_cache", original_key, result)
            return result
    return None


def _identity_series_summary(self, title: str, year: str = "") -> Optional[dict]:
    original_key = (_tmdb_module._normalize(_clean_query_seed(title, "series")), str(year or ""))
    cached = _cached_summary(self, "_series_summary_cache", original_key)
    if cached is not None:
        return cached
    for variant in media_title_variants(title, "series"):
        result = _ORIGINAL_SERIES_SUMMARY(self, variant, year)
        if result:
            _remember_summary(self, "_series_summary_cache", original_key, result)
            return result
    return None


def _identity_series(self, title: str, force: bool = False) -> Optional[dict]:
    original_key = _tmdb_module._normalize(_clean_query_seed(title, "series"))
    now = time.time()
    with self._lock:
        cached = self._series_cache.get(original_key)
        if cached and not force and now - cached[0] < _tmdb_module._series_cache_ttl(cached[1]):
            return cached[1]

    result = None
    for variant in media_title_variants(title, "series"):
        result = _ORIGINAL_SERIES(self, variant, force=force)
        if result:
            break
    with self._lock:
        self._series_cache[original_key] = (now, result)
    return result


def _identity_series_matches_id(self, title: str, tmdb_id, year: str = "") -> bool:
    for variant in media_title_variants(title, "series"):
        if _ORIGINAL_SERIES_MATCHES_ID(self, variant, tmdb_id, year):
            return True
    return False


def _legacy_jellyfin_normalize(title: str) -> str:
    return _ORIGINAL_JELLYFIN_NORMALIZE(strip_legacy_identity_suffix(title))


def _legacy_jellyfin_title_tokens(title: str):
    return _ORIGINAL_JELLYFIN_TITLE_TOKENS(strip_legacy_identity_suffix(title))


def _item_has_legacy_royal_identity(item: dict, exact_wanted: str) -> bool:
    for raw in (
        item.get("name"), item.get("original_title"), item.get("sort_name"),
        item.get("path"),
    ):
        text = str(raw or "")
        stem = _path_stem(text)
        if not _LEGACY_ID_SUFFIX_RE.search(_MEDIA_EXTENSION_RE.sub("", stem)):
            continue
        if normalize_media_identity_title(stem) == exact_wanted:
            return True
    return False


def _identity_jellyfin_match(
    self, title: str, year: str = "", items: Optional[list[dict]] = None, tmdb_id="",
) -> bool:
    """Match stable IDs first, but recover media created by older Royal builds."""
    candidates = items if items is not None else self.list_movies()
    if candidates is None:
        return False

    wanted_tmdb = str(tmdb_id or "").strip()
    if wanted_tmdb and any(
        str(item.get("tmdb_id") or "").strip() == wanted_tmdb
        for item in candidates
    ):
        return True

    exact_wanted = normalize_media_identity_title(title)
    wanted_titles = {
        normalize_media_identity_title(variant)
        for variant in media_title_variants(title, "movie")
        if normalize_media_identity_title(variant)
    }
    if exact_wanted:
        wanted_titles.add(exact_wanted)
    if not wanted_titles:
        return False

    matches: list[dict] = []
    for item in candidates:
        aliases = (item.get("name"), item.get("original_title"), item.get("sort_name"))
        alias_keys = {
            normalize_media_identity_title(alias)
            for alias in aliases if alias
        }
        if wanted_titles & alias_keys or any(
            _jellyfin_module._same_installment_title(title, alias)
            for alias in aliases if alias
        ):
            matches.append(item)
            continue
        path_key = normalize_media_identity_title(item.get("path") or "")
        if path_key and path_key in wanted_titles:
            matches.append(item)

    if not matches:
        return False

    # A historical Royal filename is stronger evidence than Jellyfin metadata
    # that may have been inferred incorrectly from that very filename.  This is
    # deliberately restricted to an exact requested-title match with Royal's
    # old deterministic suffix, so remakes/nearby franchise titles stay apart.
    legacy_exact = [
        item for item in matches
        if exact_wanted and _item_has_legacy_royal_identity(item, exact_wanted)
    ]
    if legacy_exact:
        return True

    if year:
        exact_year = [
            item for item in matches
            if item.get("year") is not None and str(item.get("year")) == str(year)
        ]
        if exact_year:
            matches = exact_year
        elif any(item.get("year") is not None for item in matches):
            return False
        else:
            return False

    if wanted_tmdb and any(str(item.get("tmdb_id") or "").strip() for item in matches):
        # Stable IDs disagree and there is no legacy-Royal filename evidence.
        return False
    return True


def _sanitize(name: str, max_bytes: int = _FILENAME_COMPONENT_MAX_BYTES) -> str:
    """Readable, portable media component without punctuation-triggered hashes."""
    original = str(name or "")
    normalized = unicodedata.normalize("NFKC", original)
    chars: list[str] = []
    for char in normalized:
        if char in _INVALID_FILENAME_CHARS or unicodedata.category(char).startswith("C"):
            chars.append(" ")
        else:
            chars.append(char)
    cleaned = " ".join("".join(chars).split()).strip(" .")
    if not cleaned:
        return "Media"
    if cleaned.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"

    if len(cleaned.encode("utf-8")) <= max_bytes:
        return cleaned
    suffix = f"~{_downloader_module._stable_suffix(original)}"
    available = max(1, int(max_bytes) - len(suffix.encode("utf-8")))
    shortened = _downloader_module._truncate_utf8(cleaned, available)
    return f"{shortened or 'Media'}{suffix}"


def sanitize_filename(name: str) -> str:
    """Directory-safe display title used for series folders."""
    return _sanitize(name)


def _canonical_movie_fields(title: str, year: str = "") -> tuple[str, str]:
    clean_title = _clean_query_seed(title, "movie") or str(title or "").strip()
    clean_year = str(year or "").strip()
    try:
        client = get_tmdb_client()
        summary = client.movie_summary(clean_title, clean_year) if client.configured else None
    except Exception:
        summary = None
    if summary:
        clean_title = str(summary.get("title") or clean_title).strip()
        clean_year = str(summary.get("year") or clean_year).strip()
    return clean_title, clean_year


def _canonical_series_title(title: str) -> str:
    clean_title = _clean_query_seed(title, "series") or str(title or "").strip()
    try:
        client = get_tmdb_client()
        summary = client.series_summary(clean_title) if client.configured else None
    except Exception:
        summary = None
    return str((summary or {}).get("title") or clean_title).strip()


def build_movie_filename(movie_title: str, year: str = "") -> str:
    """Create a Jellyfin-friendly canonical filename without legacy hash noise."""
    title, canonical_year = _canonical_movie_fields(movie_title, year)
    base = _sanitize(title).replace(" ", ".")
    year_part = f".{canonical_year}" if canonical_year else ""
    stem = f"{base}{year_part}"
    return _downloader_module._bounded_filename(
        stem, ".mp4", f"movie:{title}:{canonical_year}",
    )


def build_filename(
    series_title: str, season: int, episode: int, ep_title: str = "",
) -> str:
    """Create a canonical series episode filename while preserving SxxExx."""
    canonical_title = _canonical_series_title(series_title)
    base = _sanitize(canonical_title).replace(" ", ".")
    code = f"S{season:02d}E{episode:02d}"
    title_part = f".{_sanitize(ep_title).replace(' ', '.')}" if ep_title else ""
    stem = f"{base}.{code}{title_part}"
    return _downloader_module._bounded_filename(
        stem,
        ".mp4",
        f"series:{canonical_title}:{season}:{episode}:{ep_title}",
    )


def _norm_title(title: str) -> str:
    return normalize_media_identity_title(title)


def _series_folder_key(name: str) -> str:
    return normalize_media_identity_title(name)


def _candidate_year(path: Path) -> str:
    stem = strip_legacy_identity_suffix(path.stem)
    match = re.search(r"(?:^|[. _-])((?:19|20)\d{2})(?:$|[. _-])", stem)
    return match.group(1) if match else ""


def _movie_aliases(movie) -> tuple[str, ...]:
    title = str(getattr(movie, "title", "") or "")
    year = str(getattr(movie, "year", "") or "")
    try:
        cleaned = clean_movie_title(title)
    except Exception:
        cleaned = title
    aliases: list[str] = [cleaned, title]
    try:
        client = get_tmdb_client()
        summary = client.movie_summary(cleaned, year) if client.configured else None
    except Exception:
        summary = None
    if summary:
        aliases.extend((
            str(summary.get("title") or ""),
            str(summary.get("original_title") or ""),
        ))
    expanded: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        for variant in media_title_variants(alias, "movie"):
            key = normalize_media_identity_title(variant)
            if key and key not in seen:
                seen.add(key)
                expanded.append(variant)
    return tuple(expanded)


def _existing_valid_movie_path(out_root: Path, movie) -> Optional[Path]:
    """Find new canonical files plus old Royal ``~hash`` media safely."""
    out_root = Path(out_root)
    if not out_root.is_dir():
        return None
    aliases = _movie_aliases(movie)
    wanted = {normalize_media_identity_title(alias) for alias in aliases}
    wanted.discard("")
    if not wanted:
        return None
    requested_year = str(getattr(movie, "year", "") or "").strip()

    candidates: list[Path] = []
    seen_paths: set[Path] = set()

    def add(path: Path) -> None:
        if path in seen_paths or not path.is_file() or path.suffix.casefold() not in _VIDEO_SUFFIXES:
            return
        seen_paths.add(path)
        candidates.append(path)

    try:
        expected = out_root / build_movie_filename(
            str(getattr(movie, "title", "") or ""), requested_year,
        )
        for path in expected.parent.glob(expected.stem + ".*"):
            add(path)

        # Exact historical names are cheap to probe and avoid a full NAS scan in
        # the common upgrade path.
        for alias in (str(getattr(movie, "title", "") or ""), *aliases):
            legacy_name = _ORIGINAL_BUILD_MOVIE_FILENAME(alias, requested_year)
            legacy = out_root / legacy_name
            add(legacy)
            for path in out_root.glob(Path(legacy_name).stem + ".*"):
                add(path)

        # Last-resort identity scan handles canonical Jellyfin names, alternate
        # extensions, and quality suffixes from pre-existing libraries.
        for path in out_root.iterdir():
            add(path)
    except OSError:
        return None

    for candidate in candidates:
        candidate_key = normalize_media_identity_title(candidate.stem)
        if candidate_key not in wanted:
            continue
        candidate_year = _candidate_year(candidate)
        if requested_year and candidate_year and candidate_year != requested_year:
            continue
        valid, detail = validate_media_file(candidate)
        if valid:
            try:
                log(f"  Bereits vollständig vorhanden: {candidate.name} ({detail})")
            except Exception:
                pass
            return candidate
        try:
            log(
                f"  Vorhandene Datei ist ungültig und wird ersetzt: {candidate.name} ({detail})",
                "warn",
            )
        except Exception:
            pass
    return None


def _install_runtime_patches() -> None:
    if not getattr(_tmdb_module.TMDBClient, "_royal_media_identity_v2", False):
        _tmdb_module.TMDBClient.movie_summary = _identity_movie_summary
        _tmdb_module.TMDBClient.series_summary = _identity_series_summary
        _tmdb_module.TMDBClient.series = _identity_series
        _tmdb_module.TMDBClient.series_matches_id = _identity_series_matches_id
        _tmdb_module.TMDBClient._royal_media_identity_v2 = True

    if not getattr(_jellyfin_module.JellyfinClient, "_royal_media_identity_v2", False):
        _jellyfin_module._normalize = _legacy_jellyfin_normalize
        _jellyfin_module._title_tokens = _legacy_jellyfin_title_tokens
        _jellyfin_module.JellyfinClient.match = _identity_jellyfin_match
        _jellyfin_module.JellyfinClient._royal_media_identity_v2 = True

    _downloader_module._sanitize = _sanitize
    _downloader_module.build_filename = build_filename
    _downloader_module.build_movie_filename = build_movie_filename


_install_runtime_patches()


_SERVICE_EXPORTS = (
    "strip_legacy_identity_suffix",
    "normalize_media_identity_title",
    "media_title_variants",
    "_sanitize",
    "sanitize_filename",
    "build_filename",
    "build_movie_filename",
    "_norm_title",
    "_series_folder_key",
    "_existing_valid_movie_path",
)
publish_service(globals(), _SERVICE_EXPORTS)
