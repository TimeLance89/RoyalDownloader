from __future__ import annotations

import types

import downloader
import smart_automation as smart


def _policy(**overrides):
    base = {
        "auto_download": True,
        "weekday_window_start": 0,
        "weekday_window_end": 6,
        "weekend_window_start": None,
        "weekend_window_end": None,
        "max_parallel_downloads": 2,
        "max_bandwidth_mbps": 20.0,
        "min_free_space_gb": 50.0,
        "jellyfin_throttle_enabled": True,
        "jellyfin_streaming_bandwidth_mbps": 5.0,
        "movie_upgrades_night_only": True,
        "movie_upgrade_window_start": 0,
        "movie_upgrade_window_end": 6,
    }
    base.update(overrides)
    return base


def _clock(weekday: int, hour: int):
    return types.SimpleNamespace(tm_wday=weekday, tm_hour=hour)


def test_weekday_and_weekend_windows_are_independent():
    policy = _policy()
    assert smart.schedule_is_open(policy, 0, 2) is True
    assert smart.schedule_is_open(policy, 4, 5) is True
    assert smart.schedule_is_open(policy, 2, 9) is False
    assert smart.schedule_is_open(policy, 5, 9) is True
    assert smart.schedule_is_open(policy, 6, 23) is True


def test_overnight_window_wraps_midnight():
    assert smart.window_contains(23, 22, 4) is True
    assert smart.window_contains(2, 22, 4) is True
    assert smart.window_contains(12, 22, 4) is False
    assert smart.window_contains(12, None, None) is True
    assert smart.window_contains(12, 4, 4) is True


def test_legacy_window_is_preserved_for_all_days_until_new_policy(monkeypatch):
    monkeypatch.setattr(
        smart,
        "_ORIGINAL_LOAD_AUTOMATION",
        lambda: {
            "auto_download": True,
            "check_interval_min": 30,
            "dl_window_start": 1,
            "dl_window_end": 5,
        },
    )
    monkeypatch.setattr(smart.appconfig, "_read_all", lambda: {})
    policy = smart.load_automation_policy()
    assert (policy["weekday_window_start"], policy["weekday_window_end"]) == (1, 5)
    assert (policy["weekend_window_start"], policy["weekend_window_end"]) == (1, 5)


def test_extended_policy_persists_legacy_mirror_and_weekend_anytime(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        smart.appconfig,
        "_update_all",
        lambda values: captured.update(values) or True,
    )
    assert smart.save_automation_policy(
        auto_download=True,
        check_interval_min=15,
        weekday_window_start=0,
        weekday_window_end=6,
        weekend_window_start=None,
        weekend_window_end=None,
        max_parallel_downloads=4,
        max_bandwidth_mbps=20,
        min_free_space_gb=50,
        jellyfin_throttle_enabled=True,
        jellyfin_streaming_bandwidth_mbps=5,
        movie_upgrades_night_only=True,
        movie_upgrade_window_start=0,
        movie_upgrade_window_end=6,
    )
    assert captured["dl_window_start"] == "0"
    assert captured["dl_window_end"] == "6"
    assert captured["weekday_window_start"] == "0"
    assert captured["weekend_window_start"] == ""
    assert captured["max_parallel_downloads"] == "4"
    assert captured["max_bandwidth_mbps"] == "20"
    assert captured["min_free_space_gb"] == "50"


def test_queue_parallel_limit_updates_live_without_cancelling_queue():
    queue = downloader.DownloadQueue(max_parallel=2)
    assert queue.set_max_parallel(4) == 4
    assert queue._max_parallel == 4
    assert queue.set_max_parallel(99) == 4
    assert queue.set_max_parallel(0) == 1


def test_yt_dlp_command_gets_per_transfer_rate_limit():
    calls = []

    class FakeSubprocess:
        def Popen(self, command, *args, **kwargs):
            calls.append(command)
            return object()

    proxy = smart._SubprocessProxy(FakeSubprocess())
    smart._RATE_LOCAL.bps = 5 * 1024 * 1024
    try:
        proxy.Popen([
            "python", "-m", "yt_dlp", "--newline", "https://example.invalid/video",
        ])
    finally:
        del smart._RATE_LOCAL.bps
    assert calls
    command = calls[0]
    index = command.index("--limit-rate")
    assert command[index + 1] == str(5 * 1024 * 1024)
    assert command[-1] == "https://example.invalid/video"


def test_jellyfin_playback_reduces_total_and_per_slot_bandwidth(monkeypatch):
    monkeypatch.setattr(
        smart,
        "jellyfin_playback_status",
        lambda state=None, force=False: {
            "configured": True,
            "reachable": True,
            "active_streams": 1,
            "error": "",
        },
    )
    bandwidth = smart.effective_bandwidth(None, _policy())
    assert bandwidth["configured_mbps"] == 20.0
    assert bandwidth["effective_mbps"] == 5.0
    assert bandwidth["per_download_mbps"] == 2.5
    assert bandwidth["reduced_for_jellyfin"] is True


def test_low_space_blocks_automatic_series_but_not_manual_queue_api(monkeypatch):
    state = types.SimpleNamespace(
        automation=_policy(),
        series_path="/series",
        save_path="/movies",
    )
    monkeypatch.setattr(
        smart,
        "storage_status",
        lambda state, media_type="series": {
            "enabled": True,
            "ok": False,
            "threshold_gb": 50.0,
            "free_gb": 42.0,
            "path": "/series",
            "error": "",
        },
    )
    allowed, reason = smart.automatic_series_decision(state, now=_clock(0, 2))
    assert allowed is False
    assert "42.0 GB" in reason


def test_movie_upgrades_obey_own_night_window(monkeypatch):
    state = types.SimpleNamespace(
        automation=_policy(),
        save_path="/movies",
        series_path="/series",
    )
    monkeypatch.setattr(
        smart,
        "storage_status",
        lambda state, media_type="series": {
            "enabled": False,
            "ok": True,
            "threshold_gb": 0.0,
            "free_gb": None,
            "path": "",
            "error": "",
        },
    )
    assert smart.automatic_movie_upgrade_decision(state, now=_clock(1, 3))[0] is True
    allowed, reason = smart.automatic_movie_upgrade_decision(state, now=_clock(1, 14))
    assert allowed is False
    assert "Nachtfenster" in reason
