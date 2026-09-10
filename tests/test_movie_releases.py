import threading
import time

import pytest
import requests

from movie_releases import (
    API_CONTRACT_VERSION,
    DAY,
    MONTH_LIMIT,
    ReleaseService,
    can_check,
    catalogs_for_country,
    normalize_changes,
)


NOW = 1800000000
CONFIG = {"api_key": "test-only-key", "region": "de"}


def payload(kind="upcoming", timestamp=NOW + DAY, show_type="movie"):
    tmdb_prefix = "tv" if show_type == "series" else "movie"
    show = {
        "showType": show_type,
        "title": "Example series" if show_type == "series" else "Example film",
        "tmdbId": f"{tmdb_prefix}/123",
    }
    show["firstAirYear" if show_type == "series" else "releaseYear"] = 2026
    return {"changes": [{"showId": "1", "showType": show_type, "itemType": "show",
                         "changeType": kind, "timestamp": timestamp,
                         "service": {"id": "netflix", "name": "Netflix"},
                         "streamingOptionType": "subscription"}],
            "shows": {"1": show},
            "hasMore": False}


def country_payload():
    return {"countryCode": "de", "services": [
        {"id": "netflix", "streamingOptionTypes": {
            "subscription": True, "free": False, "rent": False, "buy": False,
        }},
        {"id": "prime", "streamingOptionTypes": {
            "subscription": True, "free": True, "rent": True, "buy": True,
        }},
    ]}


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


class UnauthorizedResponse(Response):
    status_code = 401


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


def test_series_are_normalized_with_tv_identity_and_first_air_year():
    row = normalize_changes(payload(show_type="series"), "de", "upcoming")[0]

    assert row["media_type"] == "series"
    assert row["tmdb_id"] == 123
    assert row["year"] == "2026"


def test_only_supported_shows_with_subscription_or_free_rows_are_shown():
    for field, value in (("showType", "person"), ("itemType", "episode"),
                         ("streamingOptionType", "rent"), ("changeType", "removed")):
        data = payload()
        data["changes"][0][field] = value
        assert normalize_changes(data, "de", "upcoming") == []


def test_catalog_filter_uses_only_supported_free_and_subscription_catalogs():
    upcoming = catalogs_for_country(country_payload(), "upcoming").split(",")
    assert upcoming == ["netflix.subscription", "prime.subscription", "prime.free"]
    assert all("rent" not in catalog and "buy" not in catalog for catalog in upcoming)


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


def test_changed_api_contract_retries_old_failure_immediately(tmp_path):
    started = threading.Event()

    def request(*_args, **_kwargs):
        started.set()
        return Response(payload())

    service = ReleaseService(tmp_path / "cache.json", request=request, clock=lambda: NOW)
    service.doc["snapshots"] = {"de": {
        "attempted_at": NOW,
        "api_contract_version": API_CONTRACT_VERSION - 1,
        "error": "old contract failure",
    }}
    assert service.get(CONFIG)["loading"]
    assert started.wait(2)
    assert service.doc["snapshots"]["de"]["api_contract_version"] == API_CONTRACT_VERSION


def test_auth_failure_keeps_a_safe_actionable_error(tmp_path):
    service = ReleaseService(
        tmp_path / "cache.json",
        request=lambda *_args, **_kwargs: UnauthorizedResponse({}),
        clock=lambda: NOW,
    )
    service.refresh(CONFIG)
    error = service.doc["snapshots"]["de"]["error"]
    assert "API-Key" in error
    assert CONFIG["api_key"] not in error


def test_pagination_bounded_and_duplicates_coalesced(tmp_path):
    calls = []
    def request(url, **kwargs):
        calls.append((url, kwargs))
        if "/countries/" in url:
            return Response(country_payload())
        kind = kwargs["params"]["change_type"]
        data = payload(kind, NOW - 1 if kind == "new" else NOW + DAY)
        data.update(hasMore=True, nextCursor=str(len(calls)))
        return Response(data)
    service = ReleaseService(tmp_path / "cache.json", request=request, clock=lambda: NOW)
    rows, partial = service._fetch(CONFIG)
    change_calls = [kwargs for url, kwargs in calls if "/changes" in url]
    assert len(calls) == 13 and partial
    assert len(rows) == 1 and rows[0]["date_kind"] == "observed"
    assert all(kwargs["allow_redirects"] is False for _, kwargs in calls)
    assert all(c["params"]["output_language"] == "en" for c in change_calls)
    assert all(c["params"]["catalogs"] for c in change_calls)


def test_completed_category_survives_another_category_timeout(tmp_path):
    def request(url, **kwargs):
        if "/countries/" in url:
            return Response(country_payload())
        if kwargs["params"]["change_type"] == "new":
            raise requests.ReadTimeout("provider too slow")
        return Response(payload("upcoming"))

    service = ReleaseService(tmp_path / "cache.json", request=request, clock=lambda: NOW)
    rows, partial = service._fetch(CONFIG)
    assert partial
    assert len(rows) == 1
    assert rows[0]["date_kind"] == "announced"


def test_successful_page_survives_later_timeouts_in_both_categories(tmp_path):
    upcoming_calls = 0

    def request(url, **kwargs):
        nonlocal upcoming_calls
        if "/countries/" in url:
            return Response(country_payload())
        if kwargs["params"]["change_type"] == "upcoming":
            upcoming_calls += 1
            if upcoming_calls == 1:
                data = payload("upcoming")
                data.update(hasMore=True, nextCursor="next")
                return Response(data)
        raise requests.ReadTimeout("provider too slow")

    service = ReleaseService(tmp_path / "cache.json", request=request, clock=lambda: NOW)
    rows, partial = service._fetch(CONFIG)
    assert partial
    assert len(rows) == 1


def test_future_check_rejected_server_side(tmp_path):
    service = ReleaseService(tmp_path / "cache.json", clock=lambda: NOW)
    row = normalize_changes(payload(), "de", "upcoming")[0]
    service.doc["snapshots"] = {"de": {"entries": [row]}}
    with pytest.raises(ValueError):
        service.check(CONFIG, row["id"], lambda _: pytest.fail("Must not search"))


def test_past_announced_series_is_checkable_like_already_started(tmp_path):
    service = ReleaseService(tmp_path / "cache.json", clock=lambda: NOW)
    row = normalize_changes(
        payload(timestamp=NOW - 1, show_type="series"), "de", "upcoming"
    )[0]
    service.doc["snapshots"] = {"de": {"entries": [row]}}
    searched = threading.Event()

    def search(entry):
        assert entry["media_type"] == "series"
        searched.set()
        return [{"title": entry["title"], "tmdb_id": entry["tmdb_id"]}]

    assert service.get(CONFIG)["entries"][0]["can_check"] is True
    assert service.check(CONFIG, row["id"], search)["status"] == "checking"
    assert searched.wait(2)
    for _ in range(100):
        if row["id"] in service.checks:
            break
        time.sleep(.01)
    assert service.checks[row["id"]]["status"] == "catalog"


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
