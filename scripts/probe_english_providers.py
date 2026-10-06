"""Bounded live smoke check for TMDB keyed sources; no media download.

Run manually with ``python scripts/probe_english_providers.py``. A successful
row means the adapter returned an HLS/MP4/DASH link and a tiny HTTP probe worked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import egress_curl as requests

from providers.tmdb_embeds import VidSrcScraper, VixSrcScraper, VidRiftScraper, VidRockScraper
from providers.moviebox import MovieBoxScraper
from providers.vidlink import VidLinkScraper
from media.extractor import VOEBrowserPool


SAMPLES = (
    ("movie", "693134", "Dune: Part Two", None, None),
    ("movie", "27205", "Inception", None, None),
    ("movie", "17431", "Moon", None, None),
    ("tv", "100088", "The Last of Us", 1, 1),
    ("tv", "1399", "Game of Thrones", 1, 1),
    ("tv", "1399", "Game of Thrones", 2, 3),
    ("tv", "76331", "Succession", 3, 5),
)


class SampleTMDB:
    _titles = {tmdb_id: (title, year) for _kind, tmdb_id, title, _season, _episode, year in (
        ("movie", "693134", "Dune: Part Two", None, None, "2024"),
        ("movie", "27205", "Inception", None, None, "2010"),
        ("movie", "17431", "Moon", None, None, "2009"),
        ("tv", "100088", "The Last of Us", 1, 1, "2023"),
        ("tv", "1399", "Game of Thrones", 1, 1, "2011"),
        ("tv", "76331", "Succession", 3, 5, "2018"),
    )}

    def movie_by_id(self, tmdb_id):
        title, year = self._titles[str(tmdb_id)]
        return {"title": title, "original_title": title, "year": year}

    series_by_id = movie_by_id


def probe(scraper, sample):
    kind, tmdb_id, title, season, episode = sample
    slug = f"{scraper.provider}:{tmdb_id}"
    if kind == "tv":
        slug += f"-s{season}e{episode}"
    movie = scraper.get_movie(slug)
    if not movie or not movie.hosters:
        return {"provider": scraper.provider, "slug": slug, "ok": False, "reason": "no_source"}
    expected = title + (f" S{season:02d}E{episode:02d}" if kind == "tv" else "")
    if movie.title != expected:
        return {"provider": scraper.provider, "slug": slug, "ok": False, "reason": "title_mismatch", "actual": movie.title}
    hoster = movie.hosters[0]
    headers = {"Referer": hoster.referer, "Origin": hoster.origin, **hoster.headers}
    if hoster.stream_type == "mp4":
        headers["Range"] = "bytes=0-0"
    response = requests.get(hoster.url, headers=headers, stream=True, timeout=12, impersonate="chrome")
    try:
        part = next(response.iter_content(chunk_size=512), b"")
        ok = response.status_code in {200, 206} and (
            hoster.stream_type != "hls" or part.startswith(b"#EXTM3U")
        ) and (hoster.stream_type != "dash" or part.lstrip().startswith(b"<?xml"))
    finally:
        response.close()
    return {
        "provider": scraper.provider, "slug": slug, "title": title,
        "episode": f"S{season:02d}E{episode:02d}" if kind == "tv" else "",
        "ok": ok, "status": response.status_code,
        "hoster": hoster.name, "language": hoster.language,
        "quality": hoster.quality, "type": hoster.stream_type,
    }


def main():
    pool = VOEBrowserPool(setup_voe=False)
    try:
        for cls in (VidSrcScraper, VixSrcScraper, VidRiftScraper, VidRockScraper, MovieBoxScraper, VidLinkScraper):
            scraper = cls(tmdb=SampleTMDB(), **({"pool": pool} if cls is VidLinkScraper else {}))
            for sample in SAMPLES:
                try:
                    row = probe(scraper, sample)
                except Exception as exc:
                    row = {"provider": scraper.provider, "slug": str(sample), "ok": False, "reason": type(exc).__name__}
                print(json.dumps(row, ensure_ascii=False), flush=True)
    finally:
        pool.close()


if __name__ == "__main__":
    main()
