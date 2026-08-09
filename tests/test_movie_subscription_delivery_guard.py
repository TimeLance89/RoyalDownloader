import threading
from types import SimpleNamespace

import server  # noqa: F401
import api_library_router
import application_services.source_resolution as source_resolution
from application_services import movie_subscription_delivery_guard as guard
from application_services import movie_subscription_commit_guard as commit_guard
from media_quality import normalize_media_profile


def _profile(height: int) -> dict:
    return normalize_media_profile({
        "width": 1920 if height <= 1080 else 3840,
        "height": height,
        "video_codec": "h264" if height <= 1080 else "hevc",
        "video_bitrate": 6_000_000 if height <= 1080 else 16_000_000,
        "bit_depth": 8 if height <= 1080 else 10,
        "hdr": "sdr" if height <= 1080 else "hdr10",
        "fps": 24,
        "audio_codec": "aac",
        "audio_channels": 2,
        "audio_bitrate": 192_000,
        "audio_language": "de",
    })


def _source(profile: dict):
    hoster = SimpleNamespace(
        url="https://cdn.example/movie.m3u8?token=rotating",
        name="FireStream",
        quality=f"{profile['height']}p",
        language="de",
    )
    source = SimpleNamespace(
        url="https://provider.example/movie",
        provider="provider",
        hosters=[hoster],
        _probed_media_profile=profile,
    )
    return source


def test_guard_owns_router_and_terminal_callback_seams():
    assert api_library_router._prepare_movie_subscription_upgrade is guard._prepare_movie_subscription_upgrade
    assert server._movie_subscription_download_finished is guard._movie_subscription_download_finished.__wrapped__
    assert source_resolution._movie_subscription_download_finished is guard._movie_subscription_download_finished.__wrapped__
    assert source_resolution._movie_subscription_download_failed is guard._movie_subscription_download_failed.__wrapped__
    assert source_resolution.on_job_done is commit_guard.on_job_done.__wrapped__


def test_same_successfully_delivered_candidate_is_not_enqueued_again(monkeypatch):
    profile = _profile(1080)
    source = _source(profile)
    entry = {"key": "tmdb:1", "upgrade_available_profile": profile}
    state = SimpleNamespace(
        movie_subscriptions=[entry],
        movie_subscriptions_lock=threading.RLock(),
    )
    monkeypatch.setattr(guard, "state", state)
    monkeypatch.setattr(
        guard,
        "_ORIGINAL_PREPARE_UPGRADE",
        lambda *_args: (source, [], 1080, "1080p"),
    )
    monkeypatch.setattr(guard, "_confirmed_local_downgrade", lambda _entry: False)
    prepare = guard._prepare_movie_subscription_upgrade

    first = prepare(entry, [source])
    fingerprint = entry[guard._ACTIVE_FINGERPRINT]
    entry[guard._LAST_FINGERPRINT] = fingerprint
    second = prepare(entry, [source])

    assert first[0] is source
    assert second == (None, [], 0, "")
    assert guard._ACTIVE_FINGERPRINT not in entry


def test_changed_candidate_profile_can_upgrade_again(monkeypatch):
    old_source = _source(_profile(1080))
    new_profile = _profile(2160)
    new_source = _source(new_profile)
    entry = {"key": "tmdb:1", "upgrade_available_profile": new_profile}
    state = SimpleNamespace(
        movie_subscriptions=[entry],
        movie_subscriptions_lock=threading.RLock(),
    )
    entry[guard._LAST_FINGERPRINT] = guard._candidate_fingerprint(
        {"upgrade_available_profile": _profile(1080)}, old_source,
    )
    monkeypatch.setattr(guard, "state", state)
    monkeypatch.setattr(
        guard,
        "_ORIGINAL_PREPARE_UPGRADE",
        lambda *_args: (new_source, [], 2160, "2160p"),
    )
    monkeypatch.setattr(guard, "_confirmed_local_downgrade", lambda _entry: False)

    result = guard._prepare_movie_subscription_upgrade(entry, [new_source])

    assert result[0] is new_source
    assert entry[guard._ACTIVE_FINGERPRINT] != entry[guard._LAST_FINGERPRINT]


def test_recent_legacy_success_gets_settle_window_without_another_download(monkeypatch):
    profile = _profile(1080)
    source = _source(profile)
    entry = {
        "key": "tmdb:1",
        "last_upgraded": guard.time.time() - 60,
        "upgrade_available_profile": profile,
    }
    monkeypatch.setattr(
        guard,
        "state",
        SimpleNamespace(
            movie_subscriptions=[entry],
            movie_subscriptions_lock=threading.RLock(),
        ),
    )
    monkeypatch.setattr(
        guard,
        "_ORIGINAL_PREPARE_UPGRADE",
        lambda *_args: (source, [], 1080, "1080p"),
    )

    result = guard._prepare_movie_subscription_upgrade(entry, [source])

    assert result == (None, [], 0, "")


def test_success_records_candidate_before_transient_state_is_cleared(monkeypatch):
    profile = _profile(1080)
    entry = {
        "key": "tmdb:1",
        "source_slug": "movie:1",
        "pending_slug": "movie:1",
        guard._ACTIVE_FINGERPRINT: "candidate-a",
        "upgrade_available_profile": profile,
    }
    state = SimpleNamespace(
        movie_subscriptions=[entry],
        movie_subscriptions_lock=threading.RLock(),
    )
    monkeypatch.setattr(guard, "state", state)
    monkeypatch.setattr(guard, "_persist_movie_subscriptions_background", lambda: True)

    def finished(*_args):
        entry["pending_slug"] = ""
        entry["current_media_profile"] = profile

    monkeypatch.setattr(guard, "_ORIGINAL_DOWNLOAD_FINISHED", finished)
    guard._movie_subscription_download_finished.__wrapped__("movie:1", "Movie.mp4", "1080p")

    assert entry[guard._LAST_FINGERPRINT] == "candidate-a"
    assert entry[guard._LAST_PROFILE]["height"] == 1080
    assert guard._ACTIVE_FINGERPRINT not in entry


def test_failed_unchanged_inventory_is_not_downloaded_again(monkeypatch):
    profile = _profile(2160)
    source = _source(profile)
    entry = {"key": "tmdb:1", "source_slug": "movie:1", "upgrade_available_profile": profile}
    state = SimpleNamespace(movie_subscriptions=[entry], movie_subscriptions_lock=threading.RLock())
    monkeypatch.setattr(guard, "state", state)
    monkeypatch.setattr(guard, "_ORIGINAL_PREPARE_UPGRADE", lambda *_args: (source, [], 2160, "2160p"))
    monkeypatch.setattr(guard, "_ORIGINAL_DOWNLOAD_FAILED", lambda *_args: None)
    monkeypatch.setattr(guard, "_persist_movie_subscriptions_background", lambda: True)
    monkeypatch.setattr(guard, "_confirmed_local_downgrade", lambda _entry: False)

    first = guard._prepare_movie_subscription_upgrade(entry, [source])
    entry["pending_slug"] = "movie:1"
    guard._movie_subscription_download_failed("movie:1", "Kein tatsächliches Qualitäts-Upgrade: nicht besser als Bestand")
    second = guard._prepare_movie_subscription_upgrade(entry, [source])

    assert first[0] is source
    assert entry[guard._FAILED_INVENTORY]
    assert second == (None, [], 0, "")
