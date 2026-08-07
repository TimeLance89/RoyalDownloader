import threading
from pathlib import Path
from types import SimpleNamespace

from application_services import movie_subscription_quality as quality_policy
from providers.filmpalast import FilmpalastScraper


class _ConfiguredJellyfin:
    configured = True


def _state_with_subscription(entry):
    return SimpleNamespace(
        movie_subscriptions=[entry],
        movie_subscriptions_lock=threading.RLock(),
    )


def test_jellyfin_observation_can_lower_stale_provider_rank(monkeypatch):
    entry = {
        "title": "Spider-Man Test",
        "year": "2026",
        "tmdb_id": "12345",
        "current_quality_rank": 2160,
        "current_quality": "2160p",
    }
    monkeypatch.setattr(quality_policy, "state", _state_with_subscription(entry))
    monkeypatch.setattr(quality_policy, "get_jellyfin_client", lambda: _ConfiguredJellyfin())
    monkeypatch.setattr(
        quality_policy,
        "get_jellyfin_library",
        lambda force=True: [{
            "tmdb_id": "12345",
            "name": "Spider-Man Test",
            "year": 2026,
            "quality_rank": 1080,
            "path": "/media/Spider-Man.Test.mp4",
        }],
    )
    monkeypatch.setattr(quality_policy, "log", lambda *_args, **_kwargs: None)

    quality_policy._synchronize_observed_jellyfin_quality([entry])

    assert entry["current_quality_rank"] == 1080
    assert entry["current_quality"] == "1080p"
    assert entry["quality_source"] == "jellyfin"
    assert entry["existing_path"] == "/media/Spider-Man.Test.mp4"


def test_subscription_check_corrects_rank_before_existing_policy(monkeypatch):
    entry = {
        "title": "Spider-Man Test",
        "year": "2026",
        "tmdb_id": "12345",
        "current_quality_rank": 2160,
    }
    monkeypatch.setattr(quality_policy, "state", _state_with_subscription(entry))
    monkeypatch.setattr(quality_policy, "get_jellyfin_client", lambda: _ConfiguredJellyfin())
    monkeypatch.setattr(
        quality_policy,
        "get_jellyfin_library",
        lambda force=True: [{
            "tmdb_id": "12345",
            "name": "Spider-Man Test",
            "year": 2026,
            "quality_rank": 720,
            "path": "/media/spider.mp4",
        }],
    )
    monkeypatch.setattr(quality_policy, "log", lambda *_args, **_kwargs: None)
    observed = {}

    def original(entries):
        observed["rank"] = entries[0]["current_quality_rank"]
        return 1

    monkeypatch.setattr(quality_policy, "_ORIGINAL_CHECK_MOVIE_SUBSCRIPTIONS", original)

    assert quality_policy.check_movie_subscriptions([entry]) == 1
    assert observed["rank"] == 720


def test_finished_upgrade_books_ffprobe_truth_not_provider_claim(monkeypatch):
    entry = {
        "title": "Movie",
        "source_slug": "tmdb:42",
        "pending_slug": "tmdb:42",
        "current_quality_rank": 720,
    }
    monkeypatch.setattr(quality_policy, "state", _state_with_subscription(entry))
    monkeypatch.setattr(
        quality_policy,
        "_probe_committed_file_quality",
        lambda _path: (1080, "1080p · HEVC · 10-bit"),
    )
    captured = {}

    def original(slug, out_path, advertised_quality):
        captured["slug"] = slug
        captured["path"] = out_path
        captured["quality"] = advertised_quality
        entry["pending_slug"] = ""

    monkeypatch.setattr(quality_policy, "_ORIGINAL_MOVIE_SUBSCRIPTION_FINISHED", original)
    monkeypatch.setattr(quality_policy, "_persist_movie_subscriptions_background", lambda: None)

    quality_policy._movie_subscription_download_finished(
        "tmdb:42", Path("/media/Movie.mp4"), "2160p"
    )

    assert captured["quality"] == "1080p"
    assert entry["current_quality_rank"] == 1080
    assert entry["current_quality"] == "1080p · HEVC · 10-bit"
    assert entry["quality_source"] == "ffprobe"


def test_filmpalast_quality_parser_prefers_explicit_1080p_over_generic_hd():
    _name, quality, _language = FilmpalastScraper._parse_hoster_text(
        "VOE HD Deutsch 1080p"
    )
    assert quality == "1080p"


def test_filmpalast_quality_parser_understands_uhd_and_2160p():
    assert FilmpalastScraper._parse_hoster_text("VOE UHD Deutsch")[1] == "2160p"
    assert FilmpalastScraper._parse_hoster_text("VOE 2160p Deutsch")[1] == "2160p"
