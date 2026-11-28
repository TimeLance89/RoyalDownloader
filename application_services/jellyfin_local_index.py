"""Schedule global membership updates without changing user-specific reads."""

import logging
import os
import threading
import time

from core.runtime_paths import data_dir
from integrations.jellyfin_client import JellyfinClient
from integrations.jellyfin_index import JellyfinIndex, item_key
from integrations.jellyfin_reads import movie_identities, scope_key

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_INDEX_DATASETS = ("movies", "series", "episodes")


def uses_index(client):
    return isinstance(client, JellyfinClient) and getattr(client, "provider", "jellyfin") == "jellyfin"


def local_index(state, client):
    scope = scope_key(client, 0, "ownership")[1].hex()
    with _lock:
        index = getattr(state, "_jellyfin_local_index", None)
        if index is None:
            index = state._jellyfin_local_index = JellyfinIndex(data_dir() / "jellyfin_inventory.sqlite3")
    return index, scope


def full_interval():
    try:
        return max(300, int(os.environ.get("JELLYFIN_INVENTORY_RECONCILE_SECONDS", "21600")))
    except ValueError:
        return 21600


def stored_rows(index, scope):
    return {kind: index.read(scope, kind) for kind in _INDEX_DATASETS}


def publish_rows(state, rows, generation, *, verified, index_scope):
    identities = movie_identities(rows["movies"]) if "movies" in rows else None
    with state.jellyfin_cache_lock:
        if generation != state.jellyfin_config_generation:
            return False
        now = time.time()
        for kind, prefix in (("movies", "jellyfin_library"), ("series", "jellyfin_series"),
                             ("episodes", "jellyfin_episodes")):
            if kind not in rows:
                continue
            setattr(state, prefix, rows[kind])
            setattr(state, prefix + "_time", now if verified else 0.0)
            setattr(state, prefix + "_available", verified)
            setattr(state, prefix + "_retry_after", 0.0)
        if identities is not None:
            state.jellyfin_movie_identities = identities
            state.jellyfin_movie_identities_time = now if verified else 0.0
            state.jellyfin_movie_identities_available = verified
            state.jellyfin_movie_identities_retry_after = 0.0
            state.jellyfin_movie_data_generation += 1
        if "series" in rows or "episodes" in rows:
            state.jellyfin_episode_data_generation += 1
            state.jellyfin_targeted_episodes.clear()
            if "episodes" in rows:
                state._jellyfin_index_episode_snapshot = (generation, rows["episodes"], index_scope)
        return True


def refresh_events(index, scope, client):
    batch = index.pending(scope)
    updated = set()
    failed = False
    for kind in _INDEX_DATASETS:
        requested = {item_id: token for dataset, item_id, token in batch if dataset == kind}
        if not requested:
            continue
        rows = getattr(client, f"list_{kind}")(item_ids=tuple(requested), complete=True)
        if rows is None or any(item_key(row["id"]) not in requested for row in rows):
            logger.warning("Jellyfin item refresh deferred kind=%s", kind)
            failed = True
            continue
        index.apply(scope, kind, requested, rows)
        updated.add(kind)
    return updated, bool(index.pending(scope, limit=1)), failed
