"""Plex PMS adapter using token headers and complete, bounded library reads.

Numeric Plex keys are represented as UUID-compatible hex strings inside the
existing snapshot/playlist contract. Only the authenticated token's playback
context is exposed: passing another Home user's ID does not impersonate them.
"""
import hashlib
import json
import time
from datetime import datetime, timezone
from urllib.parse import quote
from uuid import NAMESPACE_URL, uuid5

from core import egress_requests as requests
from integrations.jellyfin_client import JellyfinClient


class PlexError(RuntimeError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def item_id(value):
    return f"{int(str(value)):032x}"


def rating_key(value):
    return str(int(str(value).replace("-", ""), 16))


class PlexClient(JellyfinClient):
    provider = "plex"

    def __init__(self, base_url="", api_key="", timeout=10, *, libraries=(), server_id=""):
        super().__init__(base_url, api_key, timeout)
        self.libraries = [str(value) for value in libraries]
        self.server_id = server_id
        self.profile_id = hashlib.sha256(self.api_key.encode()).hexdigest()[:32]

    def _request(self, method, path, params=None):
        if not self.configured:
            raise PlexError("Plex-Adresse und Token fehlen.")
        from integrations.media_center import validate_server_url
        validate_server_url(self.base_url)
        try:
            response = requests.request(method, self.base_url + path,
                headers={"Accept": "application/json", "X-Plex-Token": self.api_key,
                         "X-Plex-Product": "RoyalDownloader", "X-Plex-Client-Identifier": "royal-downloader"},
                params=params, timeout=self.timeout, allow_redirects=False)
            if response.status_code in {401, 403}:
                raise PlexError("Plex lehnt den Token ab oder der Zugriff ist nicht erlaubt.")
            if not 200 <= response.status_code < 300:
                raise PlexError(f"Plex antwortet mit HTTP {response.status_code}.", response.status_code)
            payload = response.json() if response.content else {}
            if not isinstance(payload, dict):
                raise PlexError("Plex liefert keine gültige Serverantwort.")
            container = payload.get("MediaContainer", payload)
            if not isinstance(container, dict):
                raise PlexError("Plex liefert keine gültige Serverantwort.")
            return container
        except PlexError:
            raise
        except (requests.RequestException, ValueError):
            # Never include upstream exceptions (URLs may contain secrets).
            raise PlexError("Plex ist nicht erreichbar oder liefert ungültige Daten.") from None

    def server_info(self):
        info = self._request("GET", "/")
        identity = str(info.get("machineIdentifier") or "")
        if not identity:
            raise PlexError("Die Adresse gehört zu keinem Plex Media Server.")
        if self.server_id and identity != self.server_id:
            raise PlexError("Die Serveridentität hat sich geändert. Verbindung erneut einrichten.")
        self.server_id = identity
        return {"id": identity, "name": str(info.get("friendlyName") or "Plex"), "version": str(info.get("version") or "")}

    def list_libraries(self):
        self.server_info()
        payload = self._request("GET", "/library/sections")
        rows = payload.get("Directory", [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise PlexError("Ungültige Plex-Bibliotheksantwort.")
        return [{"id": str(row["key"]), "name": str(row.get("title") or "Bibliothek"),
                 "type": "movie" if row["type"] == "movie" else "series"}
                for row in rows
                if row.get("key") and row.get("type") in {"movie", "show"}]

    def list_users(self):
        try:
            self.server_info()
            return [{"id": self.profile_id, "name": "Plex-Konto dieser Verbindung"}]
        except PlexError:
            return None

    def _pages(self, path, params=None, page_size=500):
        result, start, fingerprints = [], 0, set()
        for _ in range(10000):
            page = self._request("GET", path, {**(params or {}), "X-Plex-Container-Start": start, "X-Plex-Container-Size": page_size})
            rows = page.get("Metadata", [])
            if "Metadata" not in page and page.get("size") != 0:
                raise PlexError("Unvollständige Plex-Bibliotheksantwort.")
            if not isinstance(rows, list) or any(not isinstance(row, dict) or not row.get("ratingKey") for row in rows):
                raise PlexError("Ungültige Plex-Bibliotheksantwort.")
            if rows:
                fingerprint = tuple(str(row.get("ratingKey") or "") for row in rows)
                if fingerprint in fingerprints:
                    raise PlexError("Plex wiederholt eine Bibliotheksseite; Abgleich abgebrochen.")
                fingerprints.add(fingerprint)
            result.extend(rows)
            start += len(rows)
            total = page.get("totalSize")
            if total is not None and (int(total) < 0 or (not rows and start < int(total))):
                raise PlexError("Plex hat eine unvollständige Bibliotheksseite geliefert.")
            if not rows or (total is not None and start >= int(total)) or (total is None and len(rows) < page_size):
                return result
        raise PlexError("Plex-Bibliothek überschreitet das Seitenlimit.")

    @staticmethod
    def _normalize(row):
        kind = {"movie": "Movie", "show": "Series", "episode": "Episode"}.get(row.get("type"))
        if kind is None:
            raise ValueError("Unbekannter Plex-Medientyp.")
        providers = {}
        for guid in [row.get("guid", ""), *[entry.get("id", "") for entry in row.get("Guid", [])]]:
            if str(guid).startswith("tmdb://"):
                providers["Tmdb"] = str(guid).split("tmdb://", 1)[1].split("?")[0]
        sources = []
        for media in row.get("Media", []):
            for part in media.get("Part", []):
                sources.append({"Path": str(part.get("file") or ""), "MediaStreams": [{"Type": "Video", "Height": int(media.get("height") or 0)}]})
        watched_at = row.get("lastViewedAt")
        play_count = max(0, int(row.get("viewCount") or 0))
        if kind == "Series" and not play_count:
            count, viewed = int(row.get("leafCount") or 0), int(row.get("viewedLeafCount") or 0)
            play_count = int(count > 0 and viewed >= count)
        user_data = {"Played": play_count > 0, "PlayCount": play_count}
        if watched_at:
            user_data["LastPlayedDate"] = datetime.fromtimestamp(int(watched_at), timezone.utc).isoformat()
        return {"Id": item_id(row["ratingKey"]), "Type": kind, "Name": str(row.get("title") or ""),
                "OriginalTitle": str(row.get("originalTitle") or ""), "SortName": str(row.get("titleSort") or row.get("title") or ""),
                "ProductionYear": row.get("year"), "ProviderIds": providers, "MediaSources": sources,
                "Path": next((source["Path"] for source in sources if source["Path"]), ""),
                "ParentIndexNumber": row.get("parentIndex"), "IndexNumber": row.get("index"),
                "SeriesName": str(row.get("grandparentTitle") or ""),
                "SeriesId": item_id(row["grandparentRatingKey"]) if row.get("grandparentRatingKey") else "",
                "Genres": [entry["tag"] for entry in row.get("Genre", []) if entry.get("tag")],
                "UserData": user_data, "DateCreated": str(row.get("addedAt") or ""),
                "RunTimeTicks": int(row.get("duration") or 0) * 10000}

    def _list_items(self, params, page_size, label):
        if not self.configured:
            return []
        if params.get("UserId") and params["UserId"] != self.profile_id:
            return None
        types = {"Movie": "1", "Series": "2", "Episode": "4"}
        try:
            libraries = self.list_libraries()
            wanted = set(self.libraries)
            available = {row["id"] for row in libraries}
            if wanted - available:
                return None  # A deleted/inaccessible selected library is not empty.
            result = []
            for library in libraries:
                if wanted and library["id"] not in wanted:
                    continue
                for kind in str(params.get("IncludeItemTypes") or "Movie,Series,Episode").split(","):
                    if kind not in types or (library["type"] == "movie") != (kind == "Movie"):
                        continue
                    rows = self._pages(f"/library/sections/{quote(library['id'], safe='')}/all",
                                       {"type": types[kind], "includeGuids": 1}, min(page_size, 1000))
                    result.extend(self._normalize(row) for row in rows if row.get("ratingKey"))
            return result
        except (PlexError, ValueError, TypeError, KeyError):
            return None

    def _list_endpoint_items(self, endpoint, params, page_size, label):
        if endpoint.startswith("/Shows/") and endpoint.endswith("/Episodes"):
            try:
                series = rating_key(endpoint.split("/")[2])
                return [self._normalize(row) for row in self._pages(f"/library/metadata/{series}/allLeaves", {"includeGuids": 1}, min(page_size, 1000))]
            except (PlexError, ValueError, TypeError, KeyError):
                return None
        return self._list_items(params, page_size, label)

    def active_sessions(self):
        self.server_info()
        payload = self._request("GET", "/status/sessions")
        sessions = payload.get("Metadata", [])
        if (("Metadata" not in payload and payload.get("size") != 0)
                or not isinstance(sessions, list) or any(not isinstance(row, dict)
                    or (row.get("Player") is not None and not isinstance(row["Player"], dict)) for row in sessions)):
            raise PlexError("Ungültige Plex-Wiedergabeantwort.")
        return sessions

    def has_active_playback(self):
        try:
            return bool(self.active_sessions())
        except PlexError:
            return None

    def library_revision(self):
        try:
            self.server_info()
            sections = self._request("GET", "/library/sections").get("Directory", [])
            selected = [row for row in sections if (not self.libraries or str(row.get("key")) in self.libraries)]
            material = [(row.get("key"), row.get("updatedAt"), row.get("scannedAt")) for row in selected]
            # Changes outside the small recent-view sample must also reconcile.
            material.append(("full_refresh_window", int(time.monotonic() // 300)))
            # Seen-state changes do not reliably update a section timestamp.
            for section in selected:
                for kind in ([1] if section.get("type") == "movie" else [4]):
                    page = self._request("GET", f"/library/sections/{quote(str(section['key']), safe='')}/all",
                        {"type": kind, "sort": "lastViewedAt:desc", "X-Plex-Container-Start": 0, "X-Plex-Container-Size": 12})
                    material.append((page.get("totalSize", page.get("size")), [(row.get("ratingKey"), row.get("viewCount"), row.get("lastViewedAt")) for row in page.get("Metadata", [])]))
            return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
        except (PlexError, KeyError, TypeError):
            return None

    def refresh_library(self):
        try:
            for library in self.list_libraries():
                if not self.libraries or library["id"] in self.libraries:
                    self._request("GET", f"/library/sections/{quote(library['id'], safe='')}/refresh")
            return True
        except PlexError:
            return False

    def delete_item(self, item_id):
        # Existing Jellyfin cleanup policies must never start deleting Plex files.
        return False

    def saved_server_id(self):
        return uuid5(NAMESPACE_URL, "plex:" + self.server_info()["id"]).hex

    def saved_library(self, user_id, wishes=()):
        items = self._list_items({"IncludeItemTypes": "Movie,Series", "UserId": user_id}, 500, "Plex-Merkliste")
        if items is None:
            return None
        wanted = {str(wish["tmdb_id"]) for wish in wishes if wish["media_type"] == "tv"}
        for identity in wanted:
            matches = [item for item in items if item["Type"] == "Series" and item["ProviderIds"].get("Tmdb") == identity]
            if len(matches) != 1:
                continue
            episodes = self._list_endpoint_items(f"/Shows/{matches[0]['Id']}/Episodes", {}, 500, "Plex-Merkliste")
            if episodes is None:
                return None
            items.extend(episodes)
        return items

    def create_saved_playlist(self, user_id, ids=()):
        if user_id != self.profile_id:
            raise PlexError("Dieses Plex-Profil gehört nicht zum hinterlegten Token.")
        server = self.server_info()["id"]
        uri = f"server://{server}/com.plexapp.plugins.library/library/metadata/" + ",".join(rating_key(value) for value in ids)
        result = self._request("POST", "/playlists", {"type": "video", "smart": 0, "title": "RD-Merkliste", "uri": uri})
        return item_id(result["Metadata"][0]["ratingKey"])

    def saved_playlist(self, playlist_id, user_id):
        if user_id != self.profile_id:
            raise PlexError("Plex-Profil nicht verfügbar.")
        rows = self._pages(f"/playlists/{rating_key(playlist_id)}/items")
        return {"ItemIds": [item_id(row["ratingKey"]) for row in rows]}

    def delete_saved_playlist(self, playlist_id):
        try:
            self._request("DELETE", f"/playlists/{rating_key(playlist_id)}")
        except PlexError as exc:
            if exc.status_code != 404:
                raise
