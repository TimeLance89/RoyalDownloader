import threading
from pathlib import Path
from types import SimpleNamespace

import server  # noqa: F401
from api_library_router import _prepare_movie_subscription_upgrade
from application_services import movie_subscription_repeat_guard as repeat_guard
from providers.models import FilmpalastMovie, HosterInfo


def _source(hoster_url: str, quality: str = "2160p") -> FilmpalastMovie:
    return FilmpalastMovie(
        title="Test Movie",
        url="https://catalog.example/movies/test-movie",
        year="2026",
        hosters=[
            HosterInfo(
                name="VOE",
                url=hoster_url,
                language="Deutsch",
                quality=quality,
            )
        ],
    )


def _state_with_subscription(entry):
    return SimpleNamespace(
        movie_subscriptions=[entry],
        movie_subscriptions_lock=threading.RLock(),
    )


def _fake_prepare(entry, sources):
    if not sources:
        return None, [], 0, ""
    return sources[0], list(sources[1:]), 2160, "2160p"


def test_same_false_upgrade_candidate_is_not_selected_again(monkeypatch):
    source = _source("https://voe.example/embed/same-release")
    entry = {
        "title": "Test Movie",
        "current_quality_rank": 1080,
        "target_quality": "2160p",
    }
    signature = repeat_guard._candidate_signature(source, 1080, "2160p")
    entry["upgrade_rejected_candidates"] = {
        signature: {
            "from_rank": 1080,
            "advertised_rank": 2160,
            "observed_rank": 1080,
            "recorded_at": 1.0,
        }
    }
    monkeypatch.setattr(
        repeat_guard,
        "_ORIGINAL_PREPARE_MOVIE_SUBSCRIPTION_UPGRADE",
        _fake_prepare,
    )

    primary, fallbacks, rank, label = _prepare_movie_subscription_upgrade(
        entry,
        [source],
    )

    assert primary is None
    assert fallbacks == []
    assert rank == 0
    assert label == ""


def test_changed_hoster_candidate_becomes_eligible_again(monkeypatch):
    old_source = _source("https://voe.example/embed/old-release")
    new_source = _source("https://voe.example/embed/new-release")
    entry = {
        "title": "Test Movie",
        "current_quality_rank": 1080,
        "target_quality": "2160p",
    }
    old_signature = repeat_guard._candidate_signature(old_source, 1080, "2160p")
    entry["upgrade_rejected_candidates"] = {
        old_signature: {
            "from_rank": 1080,
            "advertised_rank": 2160,
            "observed_rank": 1080,
            "recorded_at": 1.0,
        }
    }
    monkeypatch.setattr(
        repeat_guard,
        "_ORIGINAL_PREPARE_MOVIE_SUBSCRIPTION_UPGRADE",
        _fake_prepare,
    )

    primary, _fallbacks, rank, label = _prepare_movie_subscription_upgrade(
        entry,
        [new_source],
    )

    assert primary is new_source
    assert rank == 2160
    assert label == "2160p"
    assert entry["_upgrade_candidate_signature"] != old_signature
    assert entry["_upgrade_candidate_from_rank"] == 1080
    assert entry["_upgrade_candidate_advertised_rank"] == 2160


def test_ffprobe_proven_non_upgrade_is_remembered(monkeypatch):
    source = _source("https://voe.example/embed/not-really-4k")
    signature = repeat_guard._candidate_signature(source, 1080, "2160p")
    entry = {
        "title": "Test Movie",
        "source_slug": "movie:test",
        "pending_slug": "movie:test",
        "current_quality_rank": 1080,
        "quality_source": "jellyfin",
        "quality_observed_at": 1.0,
        "_upgrade_candidate_signature": signature,
        "_upgrade_candidate_from_rank": 1080,
        "_upgrade_candidate_advertised_rank": 2160,
    }
    monkeypatch.setattr(repeat_guard, "state", _state_with_subscription(entry))

    def original(_slug, _out_path, _quality):
        entry["pending_slug"] = ""
        entry["current_quality_rank"] = 1080
        entry["current_quality"] = "1080p · HEVC"
        entry["quality_source"] = "ffprobe"
        entry["quality_observed_at"] = 2.0

    monkeypatch.setattr(
        repeat_guard,
        "_ORIGINAL_MOVIE_SUBSCRIPTION_FINISHED",
        original,
    )
    monkeypatch.setattr(
        repeat_guard,
        "_persist_movie_subscriptions_background",
        lambda: None,
    )
    monkeypatch.setattr(repeat_guard, "log", lambda *_args, **_kwargs: None)

    repeat_guard._movie_subscription_download_finished(
        "movie:test",
        Path("/media/Test Movie.mp4"),
        "2160p",
    )

    rejected = entry["upgrade_rejected_candidates"][signature]
    assert rejected["from_rank"] == 1080
    assert rejected["advertised_rank"] == 2160
    assert rejected["observed_rank"] == 1080
    assert "_upgrade_candidate_signature" not in entry
    assert "_upgrade_candidate_from_rank" not in entry
    assert "_upgrade_candidate_advertised_rank" not in entry


def test_real_upgrade_is_not_blacklisted(monkeypatch):
    source = _source("https://voe.example/embed/real-4k")
    signature = repeat_guard._candidate_signature(source, 1080, "2160p")
    entry = {
        "title": "Test Movie",
        "source_slug": "movie:test",
        "pending_slug": "movie:test",
        "current_quality_rank": 1080,
        "quality_source": "jellyfin",
        "quality_observed_at": 1.0,
        "_upgrade_candidate_signature": signature,
        "_upgrade_candidate_from_rank": 1080,
        "_upgrade_candidate_advertised_rank": 2160,
    }
    monkeypatch.setattr(repeat_guard, "state", _state_with_subscription(entry))

    def original(_slug, _out_path, _quality):
        entry["pending_slug"] = ""
        entry["current_quality_rank"] = 2160
        entry["current_quality"] = "2160p · HEVC"
        entry["quality_source"] = "ffprobe"
        entry["quality_observed_at"] = 2.0

    monkeypatch.setattr(
        repeat_guard,
        "_ORIGINAL_MOVIE_SUBSCRIPTION_FINISHED",
        original,
    )
    monkeypatch.setattr(
        repeat_guard,
        "_persist_movie_subscriptions_background",
        lambda: None,
    )
    monkeypatch.setattr(repeat_guard, "log", lambda *_args, **_kwargs: None)

    repeat_guard._movie_subscription_download_finished(
        "movie:test",
        Path("/media/Test Movie.mp4"),
        "2160p",
    )

    assert not entry.get("upgrade_rejected_candidates")
    assert entry["current_quality_rank"] == 2160
