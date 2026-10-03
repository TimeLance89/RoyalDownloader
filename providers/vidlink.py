"""VidLink's browser player yields signed media URLs for RD's download queue."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from core.network_guard import ensure_public_http_url
from media.downloader import probe_stream_url
from media.extractor import VOEBrowserPool
from providers.models import HosterInfo
from providers.tmdb_embeds import TMDBEmbedScraper, _hls_tracks


class VidLinkScraper(TMDBEmbedScraper):
    def __init__(self, progress_cb=None, health=None, tmdb=None, session=None, pool=None):
        super().__init__("vidlink", tmdb, progress_cb, health, session)
        self.pool = pool

    def _vidlink(self, page):
        pool = self.pool or VOEBrowserPool(log_cb=self.log, setup_voe=False)
        try:
            for _attempt in range(2):
                captured = pool.extract(page, wait_seconds=18, referer=page)
                if not captured:
                    continue
                media, kind = captured
                if kind not in {"hls", "dash", "mp4"}:
                    continue
                parsed = urlsplit(media)
                candidates = [media]
                if parsed.hostname == "noon.mooncase.online" and parsed.path.startswith("/sacdn/dash/"):
                    candidates.append(urlunsplit((parsed.scheme, "flood.sourcerrr.online", parsed.path, parsed.query, parsed.fragment)))
                for candidate in candidates:
                    ensure_public_http_url(candidate)
                    ok, _message = probe_stream_url(candidate, referer=page, origin="https://vidlink.pro", timeout=20)
                    if not ok:
                        continue
                    language = ""
                    if kind in {"hls", "dash"}:
                        try:
                            manifest = self._get(candidate, referer=page, origin="https://vidlink.pro").text
                            if kind == "hls":
                                tracks = _hls_tracks(manifest)
                            else:
                                tracks = set(re.findall(r'<(?:\w+:)?AdaptationSet[^>]*\blang="([^"]+)"', manifest))
                            if "en" in tracks or "eng" in tracks:
                                language = "en"
                            elif tracks - {"und"}:
                                language = sorted(tracks - {"und"})[0].split("-")[0]
                        except Exception:
                            pass
                    quality = re.search(r"_(\d{3,4})_h\d+_", urlsplit(candidate).path)
                    return [HosterInfo(
                        "VidLink " + kind.upper(), candidate, language,
                        quality.group(1) + "p" if quality else "", page,
                        "https://vidlink.pro", kind, "en" if language == "en" else "",
                    )]
        except Exception as exc:
            self.log(f"VidLink browser resolution failed: {type(exc).__name__}")
        finally:
            if self.pool is None:
                pool.close()
        return []
