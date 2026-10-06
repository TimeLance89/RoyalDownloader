"""TMDB keyed embed families with direct media sources.

Only the provider specific request chain lives here. Search, source ordering,
health, probing and downloads remain in RD's shared services.
"""

from __future__ import annotations

import json
import base64
import os
import re
import time
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from core import egress_curl as requests
from core.network_guard import ensure_public_http_url

from providers.models import (
    FilmpalastMovie, FilmpalastSearchResult, FilmpalastSeries,
    FilmpalastSeriesResult, HosterInfo, SeriesEpisode,
)


_SOURCE = re.compile(r"^(vidsrc|vidrift|vixsrc|vidrock|vidlink|moviebox):(?P<id>\d+)(?:-s(?P<s>\d+)e(?P<e>\d+))?$", re.I)
_LANGUAGES = {"eng": "en", "en": "en", "ita": "it", "it": "it", "deu": "de", "ger": "de", "de": "de"}

_VIDSRC_WASM_MAX_BYTES = 128_000
_VIDSRC_WASM_MEMORY_LIMIT = 16 * 1024 * 1024
_VIDSRC_WASM_FUEL = 5_000_000
_VIDSRC_TV_RETRY_DELAY = 0.5



def _decode_vidsrc_wasm(wasm_bytes: bytes, encoded_sources: str) -> list[str]:
    """Run VidSrc's tiny decryptor with strict CPU and memory budgets."""
    if len(wasm_bytes) > _VIDSRC_WASM_MAX_BYTES:
        return []
    try:
        encrypted = base64.b64decode(encoded_sources, validate=True)
    except (ValueError, TypeError):
        return []
    if len(encrypted) > _VIDSRC_WASM_MAX_BYTES:
        return []

    import wasmtime

    try:
        config = wasmtime.Config()
        config.consume_fuel = True
        engine = wasmtime.Engine(config)
        module = wasmtime.Module(engine, wasm_bytes)
        if module.imports:
            return []

        store = wasmtime.Store(engine)
        store.set_limits(
            memory_size=_VIDSRC_WASM_MEMORY_LIMIT,
            table_elements=256,
            instances=1,
            tables=2,
            memories=1,
        )
        store.set_fuel(_VIDSRC_WASM_FUEL)
        exports = wasmtime.Instance(store, module, []).exports(store)
        alloc = exports["alloc"]
        decrypt = exports["decrypt"]
        memory = exports["memory"]

        ptr = alloc(store, len(encrypted))
        if not isinstance(ptr, int) or ptr < 0:
            return []
        memory.write(store, encrypted, ptr)
        length = decrypt(store, ptr, len(encrypted))
        if not isinstance(length, int) or length < 0 or length > _VIDSRC_WASM_MAX_BYTES:
            return []

        start = ptr + 12
        end = start + length
        if end > memory.data_len(store):
            return []
        return bytes(memory.read(store, start, end)).decode().splitlines()
    except (wasmtime.Trap, wasmtime.WasmtimeError, UnicodeDecodeError, KeyError, TypeError, ValueError):
        return []


def _json_assignment(html: str, name: str):
    marker = re.search(r"\b(?:var|let|const)\s+" + re.escape(name) + r"\s*=\s*", html)
    if not marker:
        return None
    try:
        return json.JSONDecoder().raw_decode(html[marker.end():])[0]
    except ValueError:
        return None


def _query(url: str, params: dict[str, str]) -> str:
    parsed = urlsplit(url)
    values = dict(parse_qsl(parsed.query, keep_blank_values=True))
    values.update({key: str(value) for key, value in params.items() if value})
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(values), parsed.fragment))


def _hls_tracks(playlist: str) -> set[str]:
    tracks = set()
    for line in playlist.splitlines():
        if not line.startswith("#EXT-X-MEDIA:TYPE=AUDIO"):
            continue
        match = re.search(r'LANGUAGE="([^"]+)"', line)
        if match:
            tracks.add(_LANGUAGES.get(match.group(1).casefold(), match.group(1).split("-")[0].casefold()))
    return tracks


class TMDBEmbedScraper:
    """Adapter for a single verified TMDB keyed provider family."""

    def __init__(self, provider: str, tmdb, progress_cb=None, health=None, session=None):
        if provider not in {"vidsrc", "vidrift", "vixsrc", "vidrock", "vidlink", "moviebox"}:
            raise ValueError(provider)
        self.provider = provider
        self.tmdb = tmdb
        self.log = progress_cb or (lambda _message: None)
        self.health = health
        self.session = session or requests.Session(impersonate="chrome")
        self.hosts = {
            "vidsrc": ("https://data.vidsrc.sh", "https://data.vidsrcme.ru"),
            "vidrift": ("https://embed.vidrift.net", "https://embed.vidrift.in"),
            "vixsrc": ("https://vixsrc.to",),
            "vidrock": tuple(dict.fromkeys(("https://vidrock.net", *(
                value.strip().rstrip("/") for value in os.environ.get("VIDROCK_MIRRORS", "").split(",") if value.strip().startswith("https://")
            )))),
            "vidlink": ("https://vidlink.pro",),
            "moviebox": ("https://api6.aoneroom.com", "https://api5.aoneroom.com", "https://api4.aoneroom.com", "https://api4sg.aoneroom.com", "https://api3.aoneroom.com"),
        }[provider]

    def probe_session(self):
        return requests.Session(impersonate="chrome")

    def list_movies(self, category="new", page=1):
        # Embed families have no public catalog; Sentinel checks a stable canary.
        return self.search("Inception") if page == 1 else []

    def list_series(self, page=1):
        return self.search_series("Game of Thrones") if page == 1 else []

    def _get(self, url: str, referer: str = "", origin: str = ""):
        ensure_public_http_url(url)
        headers = {"Referer": referer} if referer else {}
        if origin:
            headers["Origin"] = origin
        response = self.session.get(url, headers=headers, timeout=12)
        response.raise_for_status()
        return response

    def _slug(self, tmdb_id, season=None, episode=None):
        base = f"{self.provider}:{int(tmdb_id)}"
        return f"{base}-s{season}e{episode}" if season is not None and episode is not None else base

    def _page_path(self, tmdb_id, season=None, episode=None):
        prefix = "" if self.provider == "vidlink" else "/embed"
        return f"{prefix}/tv/{tmdb_id}/{season}/{episode}" if season is not None else f"{prefix}/movie/{tmdb_id}"

    def search(self, query):
        if not str(query or "").strip() or not self.tmdb:
            return []
        results = self.tmdb.search_movies(query, max_results=12)
        return [FilmpalastSearchResult(
            title=item.get("title") or "", slug=self._slug(item["tmdb_id"]),
            url=self.hosts[0] + self._page_path(item["tmdb_id"]),
            year=str(item.get("year") or ""), provider=self.provider,
            content_language="en", tmdb_id=str(item["tmdb_id"]),
            cover_url=item.get("cover_url") or "",
        ) for item in results if item.get("tmdb_id") and item.get("title")]

    def search_series(self, query):
        if not str(query or "").strip() or not self.tmdb:
            return []
        item = self.tmdb.series_summary(query)
        if not item or not item.get("tmdb_id"):
            return []
        tmdb_id = item["tmdb_id"]
        return [FilmpalastSeriesResult(
            title=item.get("title") or query, base_slug=self._slug(tmdb_id),
            sample_slug=self._slug(tmdb_id),
            sample_url=self.hosts[0] + self._page_path(tmdb_id, 1, 1),
            year=str(item.get("year") or ""), cover_url=item.get("cover_url") or "",
            tmdb_id=str(tmdb_id),
        )]

    def get_series(self, value):
        match = _SOURCE.match(str(value or ""))
        if not match or match.group(1).casefold() != self.provider or not self.tmdb:
            return None
        tmdb_id = match.group("id")
        item = self.tmdb.series_by_id(tmdb_id)
        if not item:
            return None
        seasons = {}
        for season, count in (item.get("season_episode_counts") or {}).items():
            season, count = int(season), int(count)
            if season < 1 or count < 1:
                continue
            seasons[season] = [SeriesEpisode(
                season=season, episode=episode,
                slug=self._slug(tmdb_id, season, episode),
                url=self.hosts[0] + self._page_path(tmdb_id, season, episode),
                content_languages=("en",),
            ) for episode in range(1, min(count, 1000) + 1)]
        return FilmpalastSeries(
            title=item.get("title") or "", base_slug=self._slug(tmdb_id),
            url=self.hosts[0] + self._page_path(tmdb_id, 1, 1),
            cover_url=item.get("cover_url") or "",
            description=item.get("description") or "", seasons=seasons,
        ) if seasons else None

    def get_movie(self, value):
        match = _SOURCE.match(str(value or ""))
        if not match or match.group(1).casefold() != self.provider:
            return None
        tmdb_id, season, episode = match.group("id", "s", "e")
        is_tv = season is not None and episode is not None
        if is_tv and (int(season) < 1 or int(episode) < 1):
            return None
        if self.health is not None and not self.health.request_allowed(self.provider):
            return None
        for base in self.hosts:
            path = f"/embed/tv/{tmdb_id}/{int(season)}/{int(episode)}" if is_tv else f"/embed/movie/{tmdb_id}"
            if self.provider == "vixsrc":
                path = f"/api/tv/{tmdb_id}/{int(season)}/{int(episode)}" if is_tv else f"/api/movie/{tmdb_id}"
            elif self.provider == "vidsrc":
                path = f"/api.php?type=tv&tmdb={tmdb_id}&season={int(season)}&episode={int(episode)}&stream_urls" if is_tv else f"/api.php?type=movie&tmdb={tmdb_id}&stream_urls"
            elif self.provider == "vidrock":
                path = f"/api/tv/{tmdb_id}/{int(season)}/{int(episode)}" if is_tv else f"/api/movie/{tmdb_id}"
            elif self.provider == "vidlink":
                path = f"/tv/{tmdb_id}/{int(season)}/{int(episode)}" if is_tv else f"/movie/{tmdb_id}"
            url = base + path
            try:
                if self.provider == "vidsrc":
                    hosters = self._vidsrc(url)
                elif self.provider == "vidrift":
                    hosters = self._vidrift(url)
                elif self.provider == "vidrock":
                    hosters = self._vidrock(url)
                elif self.provider == "vidlink":
                    hosters = self._vidlink(url)
                else:
                    hosters = self._vixsrc(url)
            except (requests.RequestsError, ValueError, KeyError, TypeError) as exc:
                self.log(f"{self.provider} {url}: {exc}")
                continue
            if hosters:
                if self.health is not None:
                    self.health.mark_success(self.provider)
                meta = self.tmdb.series_by_id(tmdb_id) if is_tv and self.tmdb else self.tmdb.movie_by_id(tmdb_id) if self.tmdb else {}
                meta = meta or {}
                title = meta.get("title") or str(tmdb_id)
                if is_tv:
                    title += f" S{int(season):02d}E{int(episode):02d}"
                return FilmpalastMovie(
                    title=title, url=url, year=str(meta.get("year") or ""),
                    cover_url=meta.get("cover_url") or "", hosters=hosters,
                    provider=self.provider, content_language=hosters[0].language or "",
                )
        return None

    def _vidsrc(self, api_url):
        attempts = 2 if "type=tv" in api_url else 1
        payload = {}
        for attempt in range(attempts):
            try:
                payload = self._get(api_url, referer="https://vidsrc.sh/").json()
            except (requests.RequestsError, ValueError):
                if attempt + 1 >= attempts:
                    raise
                time.sleep(_VIDSRC_TV_RETRY_DELAY)
                continue
            sources = (payload.get("data") or {}).get("stream_urls") or []
            if str(payload.get("status_code")) == "200" and sources:
                break
            if attempt + 1 < attempts:
                time.sleep(_VIDSRC_TV_RETRY_DELAY)

        if str(payload.get("status_code")) != "200":
            return []
        sources = (payload.get("data") or {}).get("stream_urls") or []
        if isinstance(sources, str):
            vs = payload.get("vs") or {}
            wasm_url = str(vs.get("wasm_url") or "")
            if urlsplit(wasm_url).hostname not in {"data.vidsrc.sh", "data.vidsrcme.ru"}:
                return []
            wasm = self._get(wasm_url).content
            sources = _decode_vidsrc_wasm(wasm, sources)
            if not sources:
                return []
        tokens = {}
        verified_hosts = set()
        hosters = []
        for raw in sources:
            parsed = urlsplit(raw)
            if parsed.scheme != "https" or not parsed.hostname:
                continue
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin not in tokens:
                response = self._get(origin + "/generate.php", referer="https://vidsrc.sh/")
                tokens[origin] = response.text.strip() if response.status_code == 200 else ""
            token = tokens[origin]
            if not token or len(token) > 2048:
                continue
            media = raw.replace("__TOKEN__", token) if "__TOKEN__" in raw else _query(raw, {"token": token})
            tracks = set()
            if origin not in verified_hosts:
                try:
                    manifest = self._get(media, referer="https://vidsrc.sh/").text
                except requests.RequestsError:
                    continue
                if not manifest.startswith("#EXTM3U"):
                    continue
                verified_hosts.add(origin)
                tracks = _hls_tracks(manifest)
            language = "en" if "en" in tracks else next(iter(tracks), "")
            hosters.append(HosterInfo(
                f"VidSrc {len(hosters) + 1}", media, language, "", "https://vidsrc.sh/",
                origin, "hls", "en" if "en" in tracks else "",
            ))
        return hosters

    def _vidrock(self, api_url):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        base = api_url.split("/api/", 1)[0]
        keys = getattr(self, "_vidrock_keys", {})
        key = keys.get(base)
        if key is None:
            page = self._get(base + "/movie/27205").text
            asset = re.search(r'<script[^>]+type="module"[^>]+src="([^"]+\.js)"', page)
            if not asset:
                return []
            script = self._get(urljoin(base, asset.group(1))).text
            candidates = re.findall(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", script)
            if len(candidates) != 1:
                return []
            key = bytes.fromhex(candidates[0])
            keys[base] = key
            self._vidrock_keys = keys
        cipher = AESGCM(key)
        payload = self._get(api_url, referer=base + "/").json()
        if not isinstance(payload, dict):
            return []
        hosters = []
        for server, row in payload.items():
            if not isinstance(row, dict) or row.get("type") not in {"hls", "mp4"} or not row.get("url"):
                continue
            try:
                packed = base64.urlsafe_b64decode(row["url"] + "===")
                media = cipher.decrypt(packed[:12], packed[12:], None).decode()
                if urlsplit(media).scheme != "https":
                    continue
                kind = row["type"]
                quality = ""
                if server.casefold() == "astra":
                    variants = self._get(media, referer=base + "/", origin=base).json()
                    variants = [item for item in variants if isinstance(item, dict) and item.get("url")]
                    if not variants:
                        continue
                    best = max(variants, key=lambda item: int(item.get("resolution") or 0))
                    media = best["url"]
                    quality = f"{best.get('resolution')}p"
                else:
                    if kind == "hls":
                        if not self._get(media, referer=base + "/", origin=base).text.startswith("#EXTM3U"):
                            continue
                    else:
                        ensure_public_http_url(media)
                        probe = self.session.get(media, headers={"Referer": base + "/", "Origin": base, "Range": "bytes=0-0"}, stream=True, timeout=12)
                        good = probe.status_code in {200, 206}
                        probe.close()
                        if not good:
                            continue
                language = str(row.get("language") or "").casefold()
                language = "en" if language == "english" else "de" if language == "german" else ""
                hosters.append(HosterInfo(
                    server, media, language, quality, base + "/", base, kind,
                ))
            except (ValueError, KeyError, requests.RequestsError):
                continue
        return sorted(hosters, key=lambda item: item.language != "en")

    def _vidrift(self, url):
        html = self._get(url, referer=url).text
        meta = _json_assignment(html, "embedMeta") or {}
        if meta.get("unreleased"):
            return []
        streams = []
        if meta.get("selfhostUrl"):
            streams.append({"url": meta["selfhostUrl"], "type": meta.get("selfhostKind"), "name": "Selfhost · Original"})
        if meta.get("evionUrl"):
            streams.append({"url": meta["evionUrl"], "type": "hls", "name": "Evion · Original"})
        streams.extend(meta.get("warmStreams") or [])
        streams.extend(meta.get("orionStreams") or [])
        hosters = []
        for row in streams:
            if not isinstance(row, dict) or not row.get("url"):
                continue
            media = urljoin(url, row["url"])
            kind = row.get("type") or ("hls" if ".m3u8" in media else "mp4" if ".mp4" in media else "")
            if kind not in {"hls", "mp4", "dash"}:
                continue
            name = str(row.get("name") or row.get("provider") or "VidRift")
            label = name.split("·")[-1].strip().casefold()
            language = {"english": "en", "hindi": "hi", "tamil": "ta", "telugu": "te", "french": "fr", "russian": "ru", "spanish": "es"}.get(label, "")
            rungs = row.get("rungs") or []
            quality = f"{max(int(r.get('height') or 0) for r in rungs)}p" if rungs else ""
            audio_language = ""
            if kind == "hls" and label == "original":
                try:
                    tracks = _hls_tracks(self._get(media, referer=url).text)
                    if "en" in tracks:
                        language = audio_language = "en"
                    elif tracks:
                        language = next(iter(tracks))
                except requests.RequestsError:
                    pass
            hosters.append(HosterInfo(name, media, language, quality, url, urlsplit(url).scheme + "://" + urlsplit(url).netloc, kind, audio_language))
        return sorted(hosters, key=lambda item: (item.language != "en", item.name.casefold().startswith("orion")))

    def _vixsrc(self, api_url):
        payload = self._get(api_url, referer=self.hosts[0] + "/").json()
        embed = urljoin(api_url, payload.get("src") or "")
        if embed == api_url:
            return []
        html = self._get(embed, referer=api_url).text
        streams = _json_assignment(html, "window.streams")
        if streams is None:
            match = re.search(r"window\.streams\s*=\s*", html)
            streams = json.JSONDecoder().raw_decode(html[match.end():])[0] if match else []
        token = re.search(r"['\"]token['\"]\s*:\s*['\"]([^'\"]+)", html)
        expires = re.search(r"['\"]expires['\"]\s*:\s*['\"]([^'\"]+)", html)
        if not token or not expires:
            return []
        can_fhd = "canPlayFHD=1" in embed
        hosters = []
        for row in streams:
            media = _query(row["url"].replace("\\/", "/"), {
                "token": token.group(1), "expires": expires.group(1),
                "h": "1" if can_fhd else "",
            })
            response = self._get(media, referer=embed)
            if not response.text.startswith("#EXTM3U"):
                continue
            tracks = _hls_tracks(response.text)
            language = "en" if "en" in tracks else next(iter(tracks), "")
            hosters.append(HosterInfo(
                row.get("name") or "VixSrc", media, language, "FHD" if can_fhd else "HD",
                embed, self.hosts[0], "hls", "en" if "en" in tracks else "",
            ))
        return hosters


class VidRiftScraper(TMDBEmbedScraper):
    def __init__(self, progress_cb=None, health=None, tmdb=None, session=None):
        super().__init__("vidrift", tmdb, progress_cb, health, session)


class VixSrcScraper(TMDBEmbedScraper):
    def __init__(self, progress_cb=None, health=None, tmdb=None, session=None):
        super().__init__("vixsrc", tmdb, progress_cb, health, session)


class VidSrcScraper(TMDBEmbedScraper):
    def __init__(self, progress_cb=None, health=None, tmdb=None, session=None):
        super().__init__("vidsrc", tmdb, progress_cb, health, session)


class VidRockScraper(TMDBEmbedScraper):
    def __init__(self, progress_cb=None, health=None, tmdb=None, session=None):
        super().__init__("vidrock", tmdb, progress_cb, health, session)
