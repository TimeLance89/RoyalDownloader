import threading
import time

import pytest

from movie_releases import DAY, MONTH_LIMIT, ReleaseService, can_check, normalize_changes


NOW = 1800000000
CONFIG = {"api_key": "test-only-key", "region": "de"}


def payload(kind="upcoming", timestamp=NOW + DAY):
    return {"changes": [{"showId": "1", "showType": "movie", "itemType": "show",
                         "changeType": kind, "timestamp": timestamp,
                         "service": {"id": "netflix", "name": "Netflix"},
                         "streamingOptionType": "subscription"}],
            "shows": {"1": {"showType": "movie", "title": "Example film", "tmdbId": "movie/123"}},
            "hasMore": False}


class Response:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def json(self):
        return self.data


def test_unknown_and_future_dates_never_allow_rd():
    for stamp in (None, 0, "2026-09-09", NOW, NOW + DAY):
        row = normalize_changes(payload(timestamp=stamp), "de", "upcoming")[0]
        assert not can_check(row, NOW)
    row = normalize_changes(payload(timestamp=NOW - 1), "de", "upcoming")[0]
    assert can_check(row, NOW)
    assert row["tmdb_id"] == 123


def test_observation_is_not_a_premiere():
    row = normalize_changes(payload("new", NOW - DAY), "de", "new")[0]
    assert row["date_kind"] == "observed"
    assert row["region"] == "de"


def test_only_movie_subscription_or_free_rows_are_shown():
    for field, value in (("showType", "series"), ("itemType", "episode"),
                         ("streamingOptionType", "rent"), ("changeType", "removed")):
        data = payload()
        data["changes"][0][field] = value
        assert normalize_changes(data, "de", "upcoming") == []


def test_quota_survives_restart_and_key_change(tmp_path):
    service = ReleaseService(tmp_path / "cache.json", clock=lambda: NOW)
    service.doc["requests"] = [NOW] * MONTH_LIMIT
    service._save()
    restarted = ReleaseService(service.path, clock=lambda: NOW)
    with pytest.raises(ValueError):
        restarted._reserve()


def test_snapshot_survives_outage_and_region_isolation(tmp_path):
    service = ReleaseService(tmp_path / "cache.json", request=lambda *a, **k: Response({}), clock=lambda: NOW)
    service.doc["snapshots"] = {"de": {"entries": [{"id": "de:1:netflix", "timestamp": NOW + DAY}],
                                       "updated_at": NOW - 2 * DAY, "attempted_at": NOW}}
    service.refresh(CONFIG)
    restarted = ReleaseService(service.path, clock=lambda: NOW)
    result = restarted.get(CONFIG)
    assert result["entries"] and result["stale"] and result["error"]
    assert restarted.get({"api_key": "", "region": "us"})["entries"] == []


def test_pagination_bounded_and_duplicates_coalesced(tmp_path):
    calls = []
    def request(url, **kwargs):
        calls.append(kwargs)
        kind = kwargs["params"]["change_type"]
        data = payload(kind, NOW - 1 if kind == "new" else NOW + DAY)
        data.update(hasMore=True, nextCursor=str(len(calls)))
        return Response(data)
    service = ReleaseService(tmp_path / "cache.json", request=request, clock=lambda: NOW)
    rows, partial = service._fetch(CONFIG)
    assert len(calls) == 12 and partial
    assert len(rows) == 1 and rows[0]["date_kind"] == "observed"
    assert all(c["allow_redirects"] is False for c in calls)


def test_future_check_rejected_server_side(tmp_path):
    service = ReleaseService(tmp_path / "cache.json", clock=lambda: NOW)
    row = normalize_changes(payload(), "de", "upcoming")[0]
    service.doc["snapshots"] = {"de": {"entries": [row]}}
    with pytest.raises(ValueError):
        service.check(CONFIG, row["id"], lambda _: pytest.fail("Must not search"))


def test_expired_results_and_slow_checks_do_not_claim_availability(tmp_path):
    service = ReleaseService(tmp_path / "cache.json", clock=lambda: NOW)
    row = normalize_changes(payload(timestamp=NOW - DAY), "de", "upcoming")[0]
    service.doc["snapshots"] = {"de": {"entries": [row], "attempted_at": NOW}}
    service.checks[row["id"]] = {"status": "catalog", "checked_at": NOW - 901}
    assert service.get(CONFIG)["entries"][0]["rd"]["status"] == "unchecked"
    service.checking[row["id"]] = NOW - 61
    assert service.get(CONFIG)["entries"][0]["rd"]["status"] == "unknown"


def test_release_settings_persist_without_replacing_other_settings(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "_config_dir", lambda: tmp_path)
    monkeypatch.setattr(config, "_config_file", lambda: tmp_path / "settings.ini")
    assert config._update_all({"unrelated": "keep"}, ensure_save_path=False)
    assert config.save_releases("test-key", "de")
    assert config.load_releases() == {"api_key": "test-key", "region": "de"}
    assert config._read_all()["unrelated"] == "keep"
    assert not config.save_releases("key\ninjected=value", "de")
    assert not config.save_releases("key", "invalid")
    assert config.save_releases("", "at")
    assert config.load_releases() == {"api_key": "", "region": "at"}


def test_rd_requires_exact_identity_and_errors_stay_unknown(tmp_path):
    service = ReleaseService(tmp_path / "cache.json", clock=lambda: NOW)
    row = normalize_changes(payload(timestamp=NOW - DAY), "de", "upcoming")[0]
    service.doc["snapshots"] = {"de": {"entries": [row]}}
    done = threading.Event()
    def search(_):
        done.set()
        return [{"title": "Example film", "tmdb_id": 999}]
    assert service.check(CONFIG, row["id"], search)["status"] == "checking"
    done.wait(2)
    for _ in range(100):
        if row["id"] in service.checks:
            break
        time.sleep(.01)
    assert service.checks[row["id"]]["status"] == "not_found"
    service.checks.clear()
    def fail(_):
        raise RuntimeError("provider outage")
    service.check(CONFIG, row["id"], fail)
    for _ in range(100):
        if row["id"] in service.checks:
            break
        time.sleep(.01)
    assert service.checks[row["id"]]["status"] == "unknown"
