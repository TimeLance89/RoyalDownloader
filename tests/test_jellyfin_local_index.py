"""Exercise durable Jellyfin ownership through the monitor and webhook route."""
from copy import deepcopy
from uuid import UUID
from urllib.parse import parse_qs, urlsplit
import io
import json
import time

import pytest
from fastapi.testclient import TestClient
import server

import application_services.jellyfin_live as live
from application_services.jellyfin_local_index import refresh_events
from integrations.jellyfin_client import JellyfinClient
from integrations.jellyfin_index import JellyfinIndex
from test_jellyfin_inventory import state


SERIES_ID = UUID(int=1).hex
EPISODE_ID = UUID(int=2).hex
COPY_ID = UUID(int=3).hex
MOVIE_ID = UUID(int=4).hex
WEBHOOK_PATH = "/api/jellyfin/inventory/events"
SECRET = "a-dedicated-webhook-secret-for-tests"


def episode(item_id):
    return {"id": item_id, "series_id": SERIES_ID, "season": 1, "episode": 1}


@pytest.fixture
def inventory(monkeypatch, tmp_path):
    data = state()
    index = JellyfinIndex(tmp_path / "jellyfin_inventory.sqlite3")
    jf = JellyfinClient("http://jellyfin:8096", "key")
    remote = {
        "movies": [{"id": MOVIE_ID, "name": "Movie"}],
        "series": [{"id": SERIES_ID, "name": "Series"}],
        "episodes": [episode(EPISODE_ID), episode(COPY_ID)],
    }
    revision = ["rev-1"]
    calls = []

    def loader(kind):
        def items(*, item_ids=(), complete=False):
            calls.append((kind, item_ids))
            assert complete
            if remote[kind] is None:
                return None
            return [deepcopy(row) for row in remote[kind] if not item_ids or row["id"] in item_ids]
        return items

    for kind in remote:
        monkeypatch.setattr(jf, f"list_{kind}", loader(kind))
    monkeypatch.setattr(live, "state", data)
    data._jellyfin_local_index = index
    monkeypatch.setattr(live, "backend_value", lambda _name: lambda: jf)
    monkeypatch.setattr(live, "_last_revision", "")
    monkeypatch.setattr(live, "_failure_count", 0)
    monkeypatch.setattr(live, "_probe_library_revision", lambda _client: revision[0])
    monkeypatch.setattr(live, "_wake_automation", lambda: None)
    monkeypatch.setattr(live, "_broadcast_live_update", lambda: None)
    monkeypatch.setattr(live, "request_jellyfin_live_refresh", lambda **_kwargs: None)
    _, scope = live.local_index(data, jf)
    return data, index, scope, remote, revision, calls


def test_local_lookup_and_delta_delete_preserve_other_copy(inventory):
    data, index, scope, remote, revision, calls = inventory
    assert live._monitor_cycle() == "refreshed"
    assert data.jellyfin_movie_identities[0]["id"] == MOVIE_ID
    assert set(index.read(scope, "movies")[0]) >= {"id", "name"}
    assert live.get_jellyfin_targeted_episodes({SERIES_ID})[1] is True
    calls.clear()

    remote["episodes"].remove(episode(EPISODE_ID))
    revision[0] = "rev-2"
    assert live.accept_jellyfin_inventory_event("episodes", EPISODE_ID)
    assert live.accept_jellyfin_inventory_event("episodes", EPISODE_ID)
    assert len(index.pending(scope)) == 1
    assert data.jellyfin_live_stale is True
    assert live._monitor_cycle() == "refreshed"
    assert live.get_jellyfin_targeted_episodes({SERIES_ID})[0] == [episode(COPY_ID)]
    assert calls == [("episodes", (EPISODE_ID,))]
    assert not index.pending(scope)
    assert live.get_jellyfin_episodes(force=True) == [episode(COPY_ID)]
    assert calls == [("episodes", (EPISODE_ID,))]


def test_database_restart_and_unavailable_jellyfin_leave_known_rows_in_place(inventory):
    data, index, scope, _, revision, _ = inventory
    assert live._monitor_cycle() == "refreshed"
    reopened = JellyfinIndex(index.path)
    data.jellyfin_library = None
    data.jellyfin_episodes = None
    data._jellyfin_local_index = reopened
    revision[0] = None

    assert live._monitor_cycle() == "unavailable"
    assert data.jellyfin_library[0]["id"] == MOVIE_ID
    assert reopened.last_full(scope) is not None
    assert data.jellyfin_live_stale is True
    assert live.get_jellyfin_targeted_episodes({SERIES_ID})[1:3] == (False, True)
    assert live.wait_for_jellyfin_live_ready(timeout=0) is False


def test_incomplete_reconcile_keeps_previous_rows_then_repairs_missed_change(inventory, monkeypatch):
    data, index, scope, remote, _, calls = inventory
    assert live._monitor_cycle() == "refreshed"
    last_full = index.last_full(scope)
    remote["episodes"] = None
    remote["movies"] = []

    assert live._monitor_cycle(force_full=True) == "stale"
    assert index.read(scope, "movies")[0]["id"] == MOVIE_ID
    assert index.last_full(scope) == last_full
    assert data.jellyfin_library_available is False

    remote["episodes"] = [episode(COPY_ID)]
    monkeypatch.setattr(live, "full_interval", lambda: 0)
    assert live._monitor_cycle() == "stale"
    assert calls.count(("episodes", ())) == 2
    data._jellyfin_index_full_retry = (None, 0.0)
    assert live._monitor_cycle() == "refreshed"
    assert index.read(scope, "movies") == []
    assert index.read(scope, "episodes") == [episode(COPY_ID)]
    assert calls.count(("episodes", ())) == 3


def test_new_notification_arriving_during_delta_keeps_latest_work(inventory):
    _, index, scope, _, _, _ = inventory
    live._monitor_cycle()
    assert index.enqueue(scope, "episodes", EPISODE_ID)

    def fetch(**_kwargs):
        assert index.enqueue(scope, "episodes", EPISODE_ID)
        return []

    jf = JellyfinClient("http://jellyfin:8096", "key")
    jf.list_episodes = fetch
    updated, pending, failed = refresh_events(index, scope, jf)
    assert updated == {"episodes"}
    assert pending is True
    assert failed is False
    assert episode(EPISODE_ID) in index.read(scope, "episodes")
    jf.list_episodes = lambda **_kwargs: [episode(EPISODE_ID)]
    assert refresh_events(index, scope, jf) == ({"episodes"}, False, False)
    assert episode(EPISODE_ID) in index.read(scope, "episodes")


def test_delta_failure_retries_and_never_turns_unavailable_into_deleted(inventory):
    data, index, scope, remote, _, _ = inventory
    live._monitor_cycle()
    data.jellyfin_user_episodes = [{"played": True}]
    data.jellyfin_user_episodes_available = True
    data.jellyfin_user_episodes_time = time.time() - 60
    watched_checked = data.jellyfin_user_episodes_time
    remote["episodes"] = None
    assert live.accept_jellyfin_inventory_event("episodes", EPISODE_ID)
    assert live._monitor_cycle() == "stale"
    assert index.pending(scope)
    assert episode(EPISODE_ID) in index.read(scope, "episodes")

    remote["episodes"] = [episode(COPY_ID)]
    assert live._monitor_cycle() == "refreshed"
    assert index.read(scope, "episodes") == [episode(COPY_ID)]
    assert data.jellyfin_user_episodes_available is True
    assert data.jellyfin_user_episodes_time == watched_checked


def test_successful_full_reconcile_unblocks_a_persistently_failing_delta(inventory, monkeypatch):
    data, index, scope, remote, _, calls = inventory
    live._monitor_cycle()
    original = live.backend_value("get_jellyfin_client")().list_episodes

    def reject_ids(**kwargs):
        if kwargs.get("item_ids"):
            return None
        return original(**kwargs)

    monkeypatch.setattr(live.backend_value("get_jellyfin_client")(), "list_episodes", reject_ids)
    remote["episodes"] = [episode(COPY_ID)]
    assert live.accept_jellyfin_inventory_event("episodes", EPISODE_ID)
    for _ in range(live._INDEX_DELTA_FAILURES_BEFORE_RECONCILE):
        assert live._monitor_cycle() == "stale"
    assert live._monitor_cycle() == "refreshed"
    assert not index.pending(scope)
    assert data.jellyfin_episodes == [episode(COPY_ID)]
    assert calls.count(("episodes", ())) == 2


def test_full_reconcile_does_not_acknowledge_a_newer_event(inventory):
    _, index, scope, remote, _, _ = inventory
    live._monitor_cycle()
    assert index.enqueue(scope, "episodes", EPISODE_ID)
    snapshot = index.pending(scope)
    assert index.enqueue(scope, "episodes", EPISODE_ID)
    assert index.replace(scope, remote, acknowledge=snapshot)
    assert index.pending(scope)[0][2] != snapshot[0][2]


@pytest.mark.parametrize("second_page", [
    {"Items": [], "TotalRecordCount": 2},
    {"Items": [{"Id": MOVIE_ID}], "TotalRecordCount": 2},
    {"Items": [{"Id": COPY_ID}], "TotalRecordCount": 3},
    {"Items": [{"Id": COPY_ID}]},
])
def test_jellyfin_rejects_partial_inventory_pages(monkeypatch, second_page):
    def fetch(req, **_kwargs):
        query = parse_qs(urlsplit(req.full_url).query)
        assert query["EnableUserData"] == ["false"]
        assert query["EnableImages"] == ["false"]
        payload = {"Items": [{"Id": MOVIE_ID}], "TotalRecordCount": 2}
        if query["StartIndex"] != ["0"]:
            payload = second_page
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr("integrations.jellyfin_client.urllib.request.urlopen", fetch)
    assert JellyfinClient("http://jellyfin:8096", "key").list_movies(limit=1, complete=True) is None


def test_webhook_api_requires_secret_and_only_accepts_valid_inventory_changes(monkeypatch):
    accepted = []
    monkeypatch.setattr(server, "accept_jellyfin_inventory_event", lambda *args: accepted.append(args) or True)
    client = TestClient(server.app, base_url="http://localhost")
    event = {"NotificationType": "ItemDeleted", "ItemType": "Episode", "ItemId": str(UUID(hex=EPISODE_ID))}
    monkeypatch.delenv("JELLYFIN_INVENTORY_WEBHOOK_SECRET", raising=False)
    assert client.post(WEBHOOK_PATH, json=event).status_code == 404
    monkeypatch.setenv("JELLYFIN_INVENTORY_WEBHOOK_SECRET", SECRET)
    assert client.post(WEBHOOK_PATH, json=event).status_code == 401
    headers = {"X-Royal-Jellyfin-Secret": SECRET}
    assert client.post(WEBHOOK_PATH, json=event | {"ItemId": "broken"}, headers=headers).status_code == 422
    assert client.post(WEBHOOK_PATH, json=event, headers=headers).status_code == 202
    assert accepted == [("episodes", EPISODE_ID)]
    monkeypatch.setattr(server, "accept_jellyfin_inventory_event", lambda *_args: False)
    assert client.post(WEBHOOK_PATH, json=event, headers=headers).status_code == 503
