import asyncio
import threading
from copy import deepcopy
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import api_library_router
import server  # noqa: F401
from application_services import persistence


@pytest.fixture
def inbox_payload(monkeypatch):
    def build(entry, pending=(), queued=()):
        entry = {"base_slug": "series", **entry}
        fake_state = SimpleNamespace(
            watchlist=[entry],
            watchlist_new_slugs={"series": set(pending)},
            picked=set(queued),
            queue_claim_lock=threading.RLock(),
            watchlist_lock=threading.RLock(),
            automation={"auto_download": False},
            jellyfin_cfg={},
            watchlist_global_error="",
        )
        monkeypatch.setattr(persistence, "state", fake_state)
        monkeypatch.setattr(persistence, "_persistence_status", lambda _: {"ok": True})
        return persistence.watchlist_payload.__wrapped__()["watchlist"][0]

    return build


def test_retry_is_planned_instead_of_still_failed(inbox_payload):
    item = inbox_payload(
        {"failed_downloads": {"retry": {"message": "old failure"}}},
        pending={"retry"},
        queued={"retry"},
    )

    assert item["new_count"] == 1
    assert item["queued_count"] == 1
    assert item["open_count"] == item["failed_count"] == 0
    assert item["status"] == "queued"
    assert item["failed_downloads"]["retry"]["message"] == "old failure"


def test_open_includes_unplanned_failures_even_when_check_is_blocked(inbox_payload):
    item = inbox_payload(
        {
            "last_error": "Provider unavailable",
            "failed_downloads": {"failed": {}, "retry": {}, "stale": {}},
            "waiting_release_slugs": ["unreleased"],
        },
        pending={"ready", "failed", "retry", "unreleased"},
        queued={"retry"},
    )

    assert item["new_count"] == 3
    assert item["open_count"] == 2
    assert item["queued_count"] == 1
    assert item["failed_count"] == item["waiting_release_count"] == 1
    assert item["status"] == "blocked"
    assert item["new_count"] == item["open_count"] + item["queued_count"]


def test_queued_attempt_supersedes_stale_waiting_release_marker(inbox_payload):
    item = inbox_payload(
        {"waiting_release_slugs": ["retry", "waiting"]},
        pending={"retry", "waiting"},
        queued={"retry", "not-in-subscription"},
    )

    assert item["new_count"] == item["queued_count"] == 1
    assert item["open_count"] == 0
    assert item["waiting_release_count"] == 1
    assert item["status"] == "queued"


def test_unread_download_label_matches_unread_event_and_keeps_other_states(inbox_payload):
    item = inbox_payload(
        {
            "failed_downloads": {"failed": {}},
            "downloaded_episode_notifications": [
                {"slug": "older", "downloaded_at": 1, "read": False},
                {"slug": "latest", "downloaded_at": 3, "read": True},
                {"slug": "unread", "downloaded_at": 2, "read": False},
            ],
        },
        pending={"failed"},
    )

    assert item["status"] == "failed"
    assert item["open_count"] == item["failed_count"] == 1
    assert item["downloaded_count"] == 2
    assert item["last_unread_downloaded_episode"]["slug"] == "unread"
    assert item["last_downloaded_episode"]["slug"] == "latest"


def test_read_download_history_does_not_create_an_unread_label(inbox_payload):
    item = inbox_payload({
        "downloaded_episode_notifications": [
            {"slug": "read", "downloaded_at": 1, "read": True},
        ],
    })

    assert item["downloaded_count"] == 0
    assert item["last_unread_downloaded_episode"] is None
    assert item["status"] == "current"


@pytest.mark.parametrize(("cutoff", "expected_read"), [
    (2, {"older", "displayed"}),
    (0, set()),
])
def test_acknowledgement_preserves_downloads_outside_displayed_snapshot(
    monkeypatch, cutoff, expected_read,
):
    notifications = [
        {"slug": "older", "downloaded_at": 1, "read": False},
        {"slug": "displayed", "downloaded_at": 2, "read": False},
        {"slug": "arrived-after-render", "downloaded_at": 3, "read": False},
        {"slug": "unknown-time", "read": False},
        {"slug": "invalid-time", "downloaded_at": "unknown", "read": False},
    ]
    entry = {"base_slug": "series", "downloaded_episode_notifications": notifications}
    fake_state = SimpleNamespace(watchlist=[entry], watchlist_lock=threading.RLock())
    snapshots, events = [], []
    monkeypatch.setattr(api_library_router, "state", fake_state)
    monkeypatch.setattr(api_library_router, "watchlist_lookup", lambda _: entry)
    monkeypatch.setattr(
        api_library_router, "watchlist_payload",
        lambda: {"watchlist": deepcopy(fake_state.watchlist)},
    )
    monkeypatch.setattr(
        api_library_router, "_require_persistent_snapshot",
        lambda resource, snapshot: snapshots.append((resource, snapshot)),
    )
    monkeypatch.setattr(api_library_router, "broadcast", events.append)

    response = asyncio.run(api_library_router.api_watchlist_downloads_read(
        api_library_router.WatchlistDownloadsReadBody(
            base_slug="series", downloaded_before=cutoff,
        ),
    ))

    assert {item["slug"] for item in notifications if item["read"]} == expected_read
    assert snapshots == [("watchlist", response["watchlist"])]
    assert events == [{"type": "watchlist_update", **response}]


@pytest.mark.parametrize("cutoff", [-1, float("nan"), float("inf")])
def test_acknowledgement_rejects_invalid_cutoff(cutoff):
    with pytest.raises(ValidationError):
        api_library_router.WatchlistDownloadsReadBody(
            base_slug="series", downloaded_before=cutoff,
        )


@pytest.fixture
def open_subscription(monkeypatch):
    entry = {
        "base_slug": "series",
        "title": "Series",
        "sample_url": "https://provider.example/series",
        "last_error": "Previous check failed",
    }
    series = SimpleNamespace(all_episodes=[SimpleNamespace(slug="new")])
    fake_state = SimpleNamespace(
        watchlist=[entry],
        watchlist_lock=threading.RLock(),
        watchlist_new_slugs={"series": {"old", "new"}},
        series_cache={"series": series},
        jellyfin_cache_lock=threading.RLock(),
        jellyfin_config_generation=1,
        jellyfin_episode_data_generation=1,
        jellyfin_episodes_available=False,
        jellyfin_series_available=False,
        jellyfin_user_episodes_available=False,
    )
    events, saved, withdrawn = [], [], []
    monkeypatch.setattr(api_library_router, "state", fake_state)
    monkeypatch.setattr(api_library_router, "watchlist_lookup", lambda _: entry)
    monkeypatch.setattr(
        api_library_router, "watchlist_payload",
        lambda: {"watchlist": deepcopy(fake_state.watchlist)},
    )
    monkeypatch.setattr(api_library_router, "broadcast", events.append)
    monkeypatch.setattr(api_library_router, "series_to_dict", lambda *_: {"title": "Series"})
    monkeypatch.setattr(
        api_library_router, "get_jellyfin_client",
        lambda: SimpleNamespace(configured=False),
    )
    monkeypatch.setattr(
        api_library_router, "_calculate_watchlist_entry_state",
        lambda *_: {
            "mode": "latest_season", "cleanup_mode": "keep",
            "known_slugs": ["new"], "missing_slugs": {"new"}, "cleanup_items": [],
        },
    )
    monkeypatch.setattr(
        api_library_router, "_persist_watchlist_background",
        lambda: saved.append(deepcopy(entry)),
    )
    monkeypatch.setattr(
        api_library_router, "_cancel_withdrawn_watchlist_slugs",
        lambda slugs, _: withdrawn.append(slugs),
    )
    return fake_state, entry, events, saved, withdrawn


def test_open_publishes_reconciled_subscription_state(open_subscription):
    fake_state, entry, events, saved, withdrawn = open_subscription

    response = asyncio.run(api_library_router.api_watchlist_open(
        api_library_router.WatchlistOpenBody(base_slug="series"),
    ))

    assert response["preselect_slugs"] == ["new"]
    assert fake_state.watchlist_new_slugs["series"] == {"new"}
    assert withdrawn == [{"old"}]
    assert entry["last_error"] == ""
    assert entry["check_in_progress"] is False
    assert saved[-1] == entry
    assert events == [{"type": "watchlist_update", "watchlist": [entry]}]


def test_open_publishes_provider_failure_instead_of_leaving_clients_stale(
    monkeypatch, open_subscription,
):
    fake_state, entry, events, saved, _ = open_subscription
    fake_state.series_cache.clear()
    monkeypatch.setattr(api_library_router, "get_series_for_value", lambda *_: None)

    with pytest.raises(HTTPException) as raised:
        asyncio.run(api_library_router.api_watchlist_open(
            api_library_router.WatchlistOpenBody(base_slug="series"),
        ))

    assert raised.value.status_code == 500
    assert entry["last_error"] == "Serie beim Anbieter nicht abrufbar"
    assert entry["check_in_progress"] is False
    assert saved[-1] == entry
    assert events == [{"type": "watchlist_update", "watchlist": [entry]}]
