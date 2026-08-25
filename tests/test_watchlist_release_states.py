import asyncio
import threading
from types import SimpleNamespace

import server  # noqa: F401
import api_library_router
import api_queue_router
import config
from application_services import automation
from providers.models import FilmpalastMovie, FilmpalastSeries, SeriesEpisode
from queue_jobs import new_job


class _JellyfinClient:
    configured = True

    def series_ids_for(self, *_args, **_kwargs):
        return {"series-1"}

    def episodes_for_series(self, *_args, **_kwargs):
        return {(1, 1), (1, 2)}


def test_provider_gaps_are_not_blockers_when_jellyfin_is_complete(monkeypatch):
    entry = {
        "base_slug": "legacy-series",
        "title": "Complete Series",
        "known_slugs": ["old-s00e01", "old-s01e01", "old-s01e02"],
        "download_mode": "all",
        "cleanup_mode": "keep",
        "tmdb_id": 1,
    }
    series = FilmpalastSeries(
        title="Complete Series",
        base_slug="new-series",
        url="https://provider.example/series",
        seasons={
            1: [SeriesEpisode(1, 2, "new-s01e02", "https://provider.example/e2")],
        },
    )
    monkeypatch.setattr(api_library_router, "parse_episode_slug", lambda slug: (
        ("old", 0, 1) if "s00" in slug
        else (("old", 1, 1) if slug.endswith("e01") else ("old", 1, 2))
    ))
    monkeypatch.setattr(api_library_router, "compute_downloaded_episodes", lambda _series: set())
    monkeypatch.setattr(api_library_router, "_unreleased_episode_keys", lambda *_args: set())
    monkeypatch.setattr(api_library_router, "_unreleased_episode_slugs", lambda *_args: set())

    result = api_library_router._calculate_watchlist_entry_state(
        entry,
        series,
        _JellyfinClient(),
        [{"season": 1, "episode": 1}, {"season": 1, "episode": 2}],
        None,
        [{"id": "series-1"}],
    )

    assert result["missing_slugs"] == set()


def test_episode_without_any_hoster_waits_instead_of_becoming_a_job(monkeypatch):
    slug = "serienstream:new-show-s01e08"
    entry = {
        "base_slug": "serienstream:new-show",
        "title": "New Show",
        "aliases": [],
    }
    fake_state = SimpleNamespace(
        watchlist=[entry],
        watchlist_new_slugs={entry["base_slug"]: {slug}},
        watchlist_lock=threading.RLock(),
    )
    monkeypatch.setattr(automation, "state", fake_state)
    monkeypatch.setattr(automation, "find_episode_fallbacks", lambda *_args, **_kwargs: [])
    primary = FilmpalastMovie(
        title="New Show S01E08",
        url="https://serienstream.to/episode-8",
        hosters=[],
    )

    result = automation._playable_episode_source.__wrapped__(slug, primary)

    assert result is None


def test_season_zero_is_absent_from_series_and_direct_queue_requests():
    series = FilmpalastSeries(
        title="Series",
        base_slug="series",
        url="https://provider.example/series",
        seasons={
            0: [SeriesEpisode(0, 1, "series-s00e01", "https://example/special")],
            1: [SeriesEpisode(1, 1, "series-s01e01", "https://example/regular")],
        },
    )

    assert series.season_numbers == [1]
    assert [episode.slug for episode in series.all_episodes] == ["series-s01e01"]
    assert api_queue_router._scheduled_episode_reason("series-s00e01") == (
        "Staffel 0 wird nicht unterstützt"
    )


def test_persisted_season_zero_state_is_removed_on_load(monkeypatch, tmp_path):
    watchlist_path = tmp_path / "watchlist.json"
    watchlist_path.write_text(
        """[{
          "base_slug": "series", "title": "Series", "sample_url": "https://example/series",
          "known_slugs": ["series-s00e01", "series-s01e01"],
          "waiting_release_slugs": ["series-s00e02", "series-s01e02"],
          "failed_downloads": {"series-s00e03": {}, "series-s01e03": {}},
          "downloaded_episode_notifications": [
            {"slug": "series-s00e04", "downloaded_at": 3, "read": false},
            {"slug": "series-s01e04", "downloaded_at": 2, "read": false},
            {"slug": "series-s01e04", "downloaded_at": 1, "read": true}
          ],
          "cleanup_history": ["0:4", "1:4"],
          "season_episode_counts": {"0": 4, "1": 4}
        }]""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "_watchlist_file", lambda: watchlist_path)

    entry = config.load_watchlist()[0]

    assert entry["known_slugs"] == ["series-s01e01"]
    assert entry["waiting_release_slugs"] == ["series-s01e02"]
    assert set(entry["failed_downloads"]) == {"series-s01e03"}
    assert entry["downloaded_episode_notifications"] == [{
        "slug": "series-s01e04",
        "season": 1,
        "episode": 4,
        "downloaded_at": 2.0,
        "read": False,
    }]
    assert entry["cleanup_history"] == ["1:4"]
    assert entry["season_episode_counts"] == {"1": 4}


def test_persisted_season_zero_queue_and_history_are_removed(monkeypatch, tmp_path):
    queue_path = tmp_path / "queue.json"
    monkeypatch.setattr(config, "_queue_file", lambda: queue_path)
    regular = new_job("series-s01e01")
    special = new_job("series-s00e01")
    completed_special = new_job("series-s00e02")
    completed_special.update({"status": "completed", "completed_at": 1.0})
    document = {
        "schema_version": 3,
        "revision": 1,
        "jobs": [regular, special],
        "history": [completed_special],
    }
    assert config.save_queue_state(document)

    loaded, migrated = config.load_queue_state()

    assert [job["slug"] for job in loaded["jobs"]] == ["series-s01e01"]
    assert loaded["history"] == []
    assert migrated is True


def test_download_notification_is_marked_read_and_persisted(monkeypatch):
    entry = {
        "base_slug": "series",
        "downloaded_episode_notifications": [
            {"slug": "series-s01e02", "read": False},
            {"slug": "series-s01e03", "read": False},
        ],
    }
    fake_state = SimpleNamespace(
        watchlist=[entry],
        watchlist_lock=threading.RLock(),
    )
    snapshots = []
    events = []
    monkeypatch.setattr(api_library_router, "state", fake_state)
    monkeypatch.setattr(
        api_library_router, "watchlist_lookup",
        lambda base_slug: entry if base_slug == "series" else None,
    )
    monkeypatch.setattr(
        api_library_router, "_require_persistent_snapshot",
        lambda resource, value: snapshots.append((resource, value)),
    )
    monkeypatch.setattr(
        api_library_router, "watchlist_payload",
        lambda: {"watchlist": fake_state.watchlist},
    )
    monkeypatch.setattr(api_library_router, "broadcast", events.append)

    response = asyncio.run(api_library_router.api_watchlist_downloads_read(
        api_library_router.WatchlistDownloadsReadBody(base_slug="series"),
    ))

    assert all(item["read"] for item in entry["downloaded_episode_notifications"])
    assert snapshots[0][0] == "watchlist"
    assert response["watchlist"] == [entry]
    assert events[-1]["type"] == "watchlist_update"
