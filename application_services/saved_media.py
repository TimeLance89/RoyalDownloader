"""Reconcile wishes with linked users' playable libraries, never download state."""

import logging
import threading
import time

from integrations.jellyfin_saved import jellyfin_id

logger = logging.getLogger(__name__)


def playable(item):
    return (not item.get("IsMissing") and not item.get("IsPlaceHolder")
            and item.get("LocationType") not in {"Virtual", "Offline"}
            and bool(item.get("Path") or any(source.get("Path") for source in item.get("MediaSources") or [])))


def resolve_wishes(wishes, library):
    """Only exact, unambiguous media-type/TMDB matches; series need playable episodes."""
    resolved = {}
    for wish in wishes:
        kind = "Movie" if wish["media_type"] == "movie" else "Series"
        matches = [item for item in library if item.get("Type") == kind
                   and str((item.get("ProviderIds") or {}).get("Tmdb") or
                           (item.get("ProviderIds") or {}).get("TheMovieDb") or "") == str(wish["tmdb_id"])]
        if len(matches) != 1:
            continue
        item = matches[0]
        items = [item] if kind == "Movie" else [episode for episode in library
                 if episode.get("Type") == "Episode" and episode.get("SeriesId") == item.get("Id")]
        ids = sorted({jellyfin_id(candidate["Id"]) for candidate in items if playable(candidate) and candidate.get("Id")})
        if ids:
            resolved[(wish["media_type"], wish["tmdb_id"])] = ids
    return resolved


class SavedMediaSync:
    def __init__(self, store, client, profiles):
        self.store, self.client, self.profiles = store, client, profiles
        self.lock = threading.RLock()
        self.statuses = {}
        self.thread = None
        self.next_run = 0
        self.stopped = False

    def request(self):
        with self.lock:
            self.next_run = 0
            self.statuses.clear()

    def start(self):
        with self.lock:
            self.stopped = False
            self.next_run = 0

    def tick(self):
        with self.lock:
            if self.stopped or time.monotonic() < self.next_run or (self.thread and self.thread.is_alive()):
                return
            self.next_run = time.monotonic() + 30
            self.thread = threading.Thread(target=self.run, daemon=True, name="rd-saved-media")
            self.thread.start()

    def stop(self):
        with self.lock:
            self.stopped = True
            thread = self.thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5)

    def status(self, profile):
        client = self.client()
        jf_user = profile.get("jellyfin_user_id") or ""
        if not jf_user:
            return {"state": "unlinked", "ready": []}
        if not client.configured:
            return {"state": "unconfigured", "ready": []}
        try:
            key = (client.base_url, jellyfin_id(jf_user))
        except ValueError:
            return {"state": "error", "ready": []}
        with self.lock:
            return dict(self.statuses.get(key, {"state": "pending", "ready": []}))

    def _cleanup_retired(self, client, server):
        snapshot = self.store.snapshot()
        active = set(snapshot.get("playlists", {}).get(server, {}).values())
        for identity in snapshot.get("retired_playlists", {}).get(server, []):
            if self.stopped or identity in active:
                continue
            try:
                client.delete_saved_playlist(identity)
            except Exception as exc:
                if getattr(getattr(exc, "response", None), "status_code", None) != 404:
                    logger.warning("Alte RD-Merkliste konnte nicht entfernt werden")
                    continue
            self.store.forget_retired_playlist(server, identity)

    def _publish(self, client, server, user, ids, document, profiles):
        # Publish populated, private generations. Owner-only update endpoints
        # cannot be called with Jellyfin's dashboard API key.
        replacement = client.create_saved_playlist(user, ids) if ids else ""
        try:
            if replacement:
                actual = client.saved_playlist(replacement, user)
                if sorted(jellyfin_id(value) for value in actual["ItemIds"]) != ids:
                    raise RuntimeError("Jellyfin did not publish the expected saved contents")
            current = self.client()
            if (self.stopped or self.store.snapshot()["wishes"] != document["wishes"]
                    or self.profiles() != profiles
                    or (current.base_url, current.api_key) != (client.base_url, client.api_key)):
                self.request()
                raise RuntimeError("Personal Jellyfin profile changed during publication")
            self.store.bind(server, user, replacement, protocol=1)
        except Exception:
            if replacement:
                client.delete_saved_playlist(replacement)
            raise

    def run(self):
        client = self.client()
        if not client.configured:
            return
        document = self.store.snapshot()
        if not document["wishes"] and not document.get("playlists") and not document.get("retired_playlists"):
            return
        try:
            server = client.saved_server_id()
        except Exception:
            logger.warning("Jellyfin-Serveridentität für Merkliste nicht verfügbar")
            with self.lock:
                self.statuses = {key: {"state": "error", "ready": []} for key in self.statuses}
            return
        bindings = document.get("playlists", {}).get(server, {})
        self._cleanup_retired(client, server)
        grouped = {}
        profiles = self.profiles()
        for profile in profiles:
            if not profile.get("enabled") or not profile.get("jellyfin_user_id"):
                continue
            try:
                jf_user = jellyfin_id(profile["jellyfin_user_id"])
            except ValueError:
                continue
            grouped.setdefault(jf_user, []).extend(item for item in document["wishes"] if item["owner"] == profile["id"])
        for jf_user in sorted(set(bindings) | set(grouped)):
            if self.stopped:
                return
            wishes = grouped.get(jf_user, [])
            playlist = bindings.get(jf_user)
            if not wishes and not playlist:
                continue
            try:
                library = client.saved_library(jf_user, wishes) if wishes else []
                if library is None:
                    raise RuntimeError("Jellyfin library unavailable")
                resolved = resolve_wishes(wishes, library)
                desired = sorted({item_id for ids in resolved.values() for item_id in ids})
                current_client = self.client()
                if (self.store.snapshot()["wishes"] != document["wishes"] or self.profiles() != profiles
                        or (current_client.base_url, current_client.api_key) != (client.base_url, client.api_key)):
                    self.request()
                    return
                existing = {"ItemIds": []}
                if playlist:
                    try:
                        existing = client.saved_playlist(playlist, jf_user)
                    except Exception as exc:
                        if getattr(getattr(exc, "response", None), "status_code", None) != 404:
                            raise
                        existing = {"ItemIds": [], "Missing": True}
                current_client = self.client()
                if (self.stopped or self.profiles() != profiles or self.store.snapshot()["wishes"] != document["wishes"]
                        or (current_client.base_url, current_client.api_key) != (client.base_url, client.api_key)):
                    self.request()
                    return
                legacy = document.get("playlist_protocols", {}).get(server, {}).get(jf_user) != 1
                if ((playlist and (legacy or not desired or existing.get("Missing")))
                        or sorted(jellyfin_id(item_id) for item_id in existing.get("ItemIds") or []) != desired
                        or existing.get("OpenAccess") is True or existing.get("Shares")):
                    self._publish(client, server, jf_user, desired, document, profiles)
                    self._cleanup_retired(client, server)
                status = {"state": "synced", "ready": [f"{kind}:{identity}" for kind, identity in resolved]}
            except Exception:
                logger.warning("Persönliche Jellyfin-Merkliste konnte nicht synchronisiert werden", exc_info=True)
                status = {"state": "error", "ready": []}
            with self.lock:
                self.statuses[(client.base_url, jf_user)] = status


_sync = None


def saved_media_sync():
    global _sync
    from application_services.runtime import backend_value
    if _sync is None:
        _sync = SavedMediaSync(backend_value("state").saved_media,
                              lambda: backend_value("get_jellyfin_client")(),
                              lambda: backend_value("USER_STORE").list_jellyfin_profiles())
    return _sync
