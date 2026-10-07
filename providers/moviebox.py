"""MovieBox/AoneRoom catalog and playback adapter.

The app signs anonymous API requests. Credentials are created per adapter and
kept in memory; API hosts are retried with a new signature for each request.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from urllib.parse import parse_qsl, urlencode, urlsplit

from core import egress_curl as requests
from core.network_guard import ensure_public_http_url
from providers.catalog import normalize_content_language
from providers.models import FilmpalastMovie, HosterInfo
from providers.tmdb_embeds import TMDBEmbedScraper, _SOURCE


TOKEN_ENDPOINT = "https://apig.inmoviebox.com/wefeed-mobile-bff/tab/ranking-list?tabId=0&categoryType=4516404531735022304&page=1&perPage=1"
API_ROOT = "/wefeed-mobile-bff/subject-api"
APP_NAME = "com.community.mbox.in"
APP_VERSION = 50020130
# Public client signing material, confirmed against AoneRoom's live anonymous
# token endpoint on 2026-10-03. Override when the app rotates its client key.
CLIENT_KEY = base64.b64decode(base64.b64decode(os.environ.get(
    "MOVIEBOX_CLIENT_KEY_B64", "NzZpUmwwN3MweFNOOWpxbUVXQXQ3OUVCSlp1bElRSXNWNjRGWnIyTw==",
)))


def _normal(title):
    return re.sub(r"[^a-z0-9]", "", str(title or "").casefold())


def _kind(url, declared=""):
    value = str(declared or "").casefold()
    if value in {"hls", "mp4", "mkv", "dash"}:
        return value
    path = urlsplit(url).path.casefold()
    return "hls" if path.endswith(".m3u8") else "dash" if path.endswith(".mpd") else "mkv" if path.endswith(".mkv") else "mp4" if path.endswith(".mp4") else ""


def _policy_manifest(cookie):
    match = re.search(r"(?:^|;)\s*CloudFront-Policy=([^;]+)", cookie)
    if not match:
        return ""
    try:
        encoded = match.group(1).replace("-", "+").replace("_", "=").replace("~", "/")
        payload = json.loads(base64.b64decode(encoded + "==="))
        resource = payload["Statement"][0]["Resource"]
        if not resource.startswith("https://"):
            return ""
        stem = resource.rstrip("/*")
        return stem if stem.endswith(".mpd") else stem + "/index.mpd"
    except (ValueError, KeyError, IndexError, TypeError):
        return ""


class MovieBoxScraper(TMDBEmbedScraper):
    def __init__(self, progress_cb=None, health=None, tmdb=None, session=None):
        super().__init__("moviebox", tmdb, progress_cb, health, session)
        self._device = uuid.uuid4().hex
        self._gaid = str(uuid.uuid4())
        self._token = ""
        self._token_exp = 0
        self._preferred_host = self.hosts[0]

    def _headers(self, method, url, body, extra=None):
        stamp = str(int(time.time() * 1000))
        parsed = urlsplit(url)
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        query = "&".join(f"{key}={value}" for key, value in sorted(pairs))
        canonical_url = parsed.path + ("?" + query if query else "")
        content_type = "application/json; charset=utf-8" if body else "application/json"
        plain = "\n".join((
            method.upper(), "application/json", content_type,
            str(len(body.encode())) if body else "", stamp,
            hashlib.md5(body.encode(), usedforsecurity=False).hexdigest() if body else "", canonical_url,
        ))
        signature = base64.b64encode(hmac.new(CLIENT_KEY, plain.encode(), hashlib.md5).digest()).decode()
        info = {
            "package_name": APP_NAME, "version_name": "4.0.03.0920.03", "version_code": APP_VERSION,
            "os": "android", "os_version": "14", "device_id": self._device,
            "install_store": "official", "gaid": self._gaid, "brand": "google", "model": "Pixel 8",
            "system_language": "en", "net": "NETWORK_WIFI", "region": "IN",
            "timezone": "Asia/Calcutta", "sp_code": "",
        }
        headers = {
            "Accept": "application/json", "Content-Type": content_type,
            "x-client-token": stamp + "," + hashlib.md5(stamp[::-1].encode(), usedforsecurity=False).hexdigest(),
            "x-tr-signature": stamp + "|2|" + signature,
            "x-client-info": json.dumps(info, separators=(",", ":")),
            "x-client-status": "0",
            "User-Agent": f"{APP_NAME}/{APP_VERSION} (Linux; U; Android 14; en_IN; Pixel 8; Build/UD1A.230803.041; Cronet/145.0.7582.0)",
        }
        headers.update(extra or {})
        return headers

    def _call(self, method, path_or_url, body=None, extra=None, token_request=False):
        encoded = json.dumps(body, separators=(",", ":"), ensure_ascii=False) if body is not None else ""
        if path_or_url.startswith("https://"):
            urls = (path_or_url,)
        else:
            urls = tuple(base + path_or_url for base in (self._preferred_host, *self.hosts) if base in self.hosts)
            urls = tuple(dict.fromkeys(urls))
        for url in urls:
            ensure_public_http_url(url)
            headers = self._headers(method, url, encoded, extra)
            if not token_request:
                token = self._anonymous_token()
                if token:
                    headers["Authorization"] = "Bearer " + token
            try:
                response = self.session.request(method, url, data=encoded or None, headers=headers, timeout=12)
            except requests.RequestsError:
                continue
            if response.status_code in {403, 429} or response.status_code >= 500:
                continue
            if response.status_code != 200:
                return None
            try:
                payload = response.json()
            except ValueError:
                return None
            if not token_request and payload.get("code") == 441:
                self._token = ""
                continue
            if not token_request and payload.get("code") != 0:
                return None
            if not path_or_url.startswith("https://"):
                self._preferred_host = urlsplit(url).scheme + "://" + urlsplit(url).netloc
            return response if token_request else payload.get("data")
        return None

    def _anonymous_token(self):
        if self._token and self._token_exp > time.time() + 300:
            return self._token
        response = self._call("GET", TOKEN_ENDPOINT, token_request=True)
        try:
            token = json.loads(response.headers.get("x-user") or "{}").get("token")
            body = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==="))
            expiry = int(body.get("exp") or 0)
        except (AttributeError, KeyError, ValueError, IndexError, TypeError):
            return ""
        if expiry > time.time() + 300:
            self._token, self._token_exp = token, expiry
        return self._token

    def _search_subject(self, title, year, media_type):
        response = self._call("POST", API_ROOT + "/search/v2", {
            "page": 1, "perPage": 20, "keyword": title, "restrictKid": 1,
        }) or {}
        groups = response.get("results") or []
        wanted = _normal(title)
        scored = []
        for group in groups:
            for row in group.get("subjects") or []:
                if int(row.get("subjectType") or 0) != (2 if media_type == "tv" else 1):
                    continue
                candidate = _normal(row.get("title"))
                if not candidate:
                    continue
                candidate_year = str(row.get("year") or row.get("releaseDate") or "")[:4]
                exact = candidate == wanted
                season_suffix = media_type == "tv" and candidate.startswith(wanted) and re.fullmatch(r"s\d+", candidate[len(wanted):])
                if not exact and not season_suffix and (candidate not in wanted or len(candidate) < 7):
                    continue
                if year and candidate_year and candidate_year != year:
                    continue
                scored.append((int(exact), int(candidate_year == year), row))
        return max(scored, default=(0, 0, None), key=lambda item: item[:2])[2]

    def get_movie(self, value):
        match = _SOURCE.match(str(value or ""))
        if not match or match.group(1).casefold() != "moviebox" or not self.tmdb:
            return None
        tmdb_id, season, episode = match.group("id", "s", "e")
        is_tv = season is not None and episode is not None
        if is_tv and (int(season) < 1 or int(episode) < 1):
            return None
        meta = self.tmdb.series_by_id(tmdb_id) if is_tv else self.tmdb.movie_by_id(tmdb_id)
        if not meta:
            return None
        titles = tuple(dict.fromkeys(filter(None, (meta.get("title"), meta.get("original_title")))))
        candidate = next((found for title in titles if (found := self._search_subject(title, str(meta.get("year") or ""), "tv" if is_tv else "movie"))), None)
        if not candidate:
            return None
        subject_id = candidate.get("subjectId")
        detail = self._call("GET", API_ROOT + "/get?" + urlencode({"subjectId": subject_id})) or {}
        if not detail:
            return None
        candidates = [(subject_id, detail.get("language") or "")]
        candidates.extend((row.get("subjectId"), row.get("lanName") or "") for row in detail.get("dubs") or [] if row.get("subjectId") and row.get("subjectId") != subject_id)
        hosters = []
        for track_id, label in candidates:
            params = {"subjectId": track_id, "se": int(season or 0), "ep": int(episode or 0), "streamSignType": 1,
                      "supportCodecs[hevc]": 1, "supportCodecs[h264]": 1}
            if detail.get("detailPath"):
                params["detailPath"] = detail["detailPath"]
            payload = self._call("GET", API_ROOT + "/play-info?" + urlencode(params)) or {}
            streams = payload.get("streams") or payload.get("streamList") or []
            for row in streams:
                cookie = row.get("signCookie") or ""
                media = _policy_manifest(cookie) or row.get("url") or row.get("playUrl") or row.get("resourceLink") or row.get("streamUrl")
                if not media or urlsplit(media).scheme != "https":
                    continue
                if "b164fbfb4347792950bdfbfb563d39d9" in media:
                    continue
                kind = _kind(media)
                if not kind:
                    kind = _kind(media, row.get("format"))
                if not kind:
                    continue
                language = normalize_content_language(row.get("language") or label)
                quality = str(row.get("resolutions") or row.get("resolution") or row.get("quality") or "")
                headers = {str(row.get("signHeaderKey") or "Cookie"): cookie} if cookie else {}
                hosters.append(HosterInfo(
                    f"MovieBox {kind.upper()}", media, language, quality,
                    "https://moviebox.ph/", "https://moviebox.ph", kind,
                    "en" if language == "en" and kind == "hls" else "",
                    headers,
                ))
        if not hosters:
            return None
        hosters.sort(key=lambda item: (item.language != "en", item.stream_type not in {"hls", "mp4"}))
        title = meta.get("title") or ""
        if is_tv:
            title += f" S{int(season):02d}E{int(episode):02d}"
        return FilmpalastMovie(
            title=title, year=str(meta.get("year") or ""),
            url=f"moviebox:{tmdb_id}" + (f"-s{season}e{episode}" if is_tv else ""),
            hosters=hosters, provider="moviebox", content_language=hosters[0].language,
        )
