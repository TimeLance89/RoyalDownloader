"""User-scoped playable library reads and private managed video playlists."""

from uuid import UUID

from core import egress_requests as requests
from integrations.jellyfin_auth import jellyfin_auth_headers


def jellyfin_id(value):
    return UUID(str(value)).hex


def playlist_name(user_id):
    return f"RD-Merkliste · {jellyfin_id(user_id)}"


class JellyfinSavedMixin:
    def saved_server_id(self):
        return jellyfin_id(self._saved_request("GET", "/System/Info/Public")["Id"])

    def saved_library(self, user_id, wishes=()):
        endpoint = f"/Users/{jellyfin_id(user_id)}/Items"
        params = {
            "Recursive": "true", "IncludeItemTypes": "Movie,Series", "CollapseBoxSetItems": "false",
            "ExcludeLocationTypes": "Virtual,Offline", "IsMissing": "false",
            "IsPlaceHolder": "false", "Fields": "ProviderIds,MediaSources,Path",
        }
        items = self._list_endpoint_items(endpoint, params, 500, "Persönliche Jellyfin-Merkliste")
        if items is None:
            return None
        wanted = {str(item["tmdb_id"]) for item in wishes if item["media_type"] == "tv"}
        for identity in sorted(wanted):
            matches = [item for item in items if item.get("Type") == "Series"
                       and str((item.get("ProviderIds") or {}).get("Tmdb") or
                               (item.get("ProviderIds") or {}).get("TheMovieDb") or "") == identity]
            if len(matches) != 1:
                continue
            episodes = self._list_endpoint_items(endpoint, {
                **params, "IncludeItemTypes": "Episode", "ParentId": jellyfin_id(matches[0]["Id"]),
            }, 500, "Persönliche Jellyfin-Serienmerkliste")
            if episodes is None:
                return None
            items.extend(episodes)
        return items

    def _saved_request(self, method, path, body=None, params=None):
        response = requests.request(method, f"{self.base_url}{path}",
                                    headers=jellyfin_auth_headers(self.api_key),
                                    json=body, params=params, timeout=self.timeout,
                                    allow_redirects=False)
        response.raise_for_status()
        if response.status_code >= 300:
            raise ValueError("Jellyfin playlist redirect rejected")
        return response.json() if response.content else {}

    def create_saved_playlist(self, user_id, ids=()):
        result = self._saved_request("POST", "/Playlists", {
            "Name": playlist_name(user_id), "Ids": list(ids), "UserId": jellyfin_id(user_id),
            "MediaType": "Video", "IsPublic": False, "Users": [],
        })
        return jellyfin_id(result["Id"])

    def saved_playlist(self, playlist_id, user_id):
        # /Playlists/{id} and its update route use the token's user claim.
        # A dashboard API key has no user claim. The items route explicitly
        # accepts the linked user and therefore works with server API keys.
        items, start = [], 0
        while True:
            page = self._saved_request("GET", f"/Playlists/{jellyfin_id(playlist_id)}/Items", params={
                "UserId": jellyfin_id(user_id), "StartIndex": start, "Limit": 500,
            })
            rows = page.get("Items") or []
            items.extend(rows)
            start += len(rows)
            if not rows or start >= page.get("TotalRecordCount", start):
                return {"ItemIds": [jellyfin_id(item["Id"]) for item in items]}
            if start >= 100_000:
                raise ValueError("Managed Jellyfin playlist exceeds bounded read limit")

    def delete_saved_playlist(self, playlist_id):
        self._saved_request("DELETE", f"/Items/{jellyfin_id(playlist_id)}")
