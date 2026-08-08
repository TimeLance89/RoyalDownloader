from __future__ import annotations

import pytest

from taste_model import score_profile_dimensions
from taste_profile import (
    TasteProfileStore,
    jellyfin_taste_signal,
    normalize_metadata,
)
from taste_recommender import rank_with_taste_profile


def test_genre_aliases_are_canonicalized():
    metadata = normalize_metadata({
        "genres": ["Adventure", "Comedy", "Science Fiction", "Crime"],
    }, "movie")
    assert metadata["genres"] == ["Abenteuer", "Komödie", "Science-Fiction", "Krimi"]


def test_jellyfin_completed_repeat_is_stronger_than_short_start():
    complete = {
        "RunTimeTicks": 6_000_000_000,
        "UserData": {
            "Played": True,
            "PlayCount": 3,
            "PlaybackPositionTicks": 5_900_000_000,
        },
    }
    short = {
        "RunTimeTicks": 6_000_000_000,
        "UserData": {
            "Played": False,
            "PlayCount": 1,
            "PlaybackPositionTicks": 300_000_000,
        },
    }
    complete_signal, complete_evidence = jellyfin_taste_signal(complete)
    short_signal, short_evidence = jellyfin_taste_signal(short)
    assert complete_signal > short_signal * 5
    assert complete_evidence["play_count"] == 3
    assert short_evidence["completion"] == pytest.approx(0.05)


def test_low_rating_can_counteract_completed_playback():
    item = {
        "UserData": {
            "Played": True,
            "PlayCount": 1,
            "Rating": 1,
        },
    }
    signal, _evidence = jellyfin_taste_signal(item)
    assert signal < 0


def test_legacy_profile_decays_instead_of_living_forever(tmp_path):
    now = [1_000_000.0]
    store = TasteProfileStore(tmp_path / "taste.json", clock=lambda: now[0])
    assert store.import_legacy({"genres": {"Horror": 20}, "kinds": {"movie": 4}})
    assert store.public_profile()["genres"]["Horror"] == 20
    now[0] += 120 * 86400
    assert store.public_profile()["genres"]["Horror"] == pytest.approx(10.0, abs=0.001)


def test_less_feedback_reduces_similarity_without_blocking_exact_item(tmp_path):
    store = TasteProfileStore(tmp_path / "taste.json", clock=lambda: 100_000)
    store.set_feedback(
        "movie:one-piece",
        "less",
        media_type="series",
        metadata={"genres": ["Adventure", "Animation", "Fantasy"]},
    )
    profile = store.public_profile()
    assert "movie:one-piece" not in profile["blocked_items"]
    assert profile["genres"]["Abenteuer"] < 0
    assert profile["genres"]["Animation"] < 0


def test_dismiss_blocks_exact_item_and_teaches_negative_dimensions(tmp_path):
    store = TasteProfileStore(tmp_path / "taste.json", clock=lambda: 100_000)
    store.set_feedback(
        "series:tmdb:37854",
        "dismiss",
        media_type="series",
        metadata={"genres": ["Action", "Adventure", "Animation", "Fantasy"]},
    )
    profile = store.public_profile()
    assert profile["blocked_items"] == ["series:tmdb:37854"]
    assert profile["genres"]["Animation"] < 0


def test_profile_exposes_confidence_and_signal_breakdown(tmp_path):
    store = TasteProfileStore(tmp_path / "taste.json", clock=lambda: 100_000)
    for index in range(12):
        store.record_event(
            "download",
            source="web",
            media_type="movie",
            item_key=f"movie:{index}",
            metadata={"genres": ["Horror", "Thriller"]},
        )
    store.set_feedback("movie:fav", "like", metadata={"genres": ["Horror"]})
    profile = store.public_profile()
    assert profile["version"] == 2
    assert profile["confidence"] > 0
    assert profile["signal_breakdown"]["behavior"] == 12
    assert profile["signal_breakdown"]["explicit"] == 1
    assert profile["ranking"]["negative_multiplier"] > 1


def test_broad_unknown_genres_do_not_beat_precise_match():
    profile = {
        "confidence": 0.9,
        "ranking": {},
        "dimensions": {
            "genres": {"Action": 10, "Abenteuer": 9, "Thriller": 8},
            "media_types": {"movie": 4},
        },
    }
    precise = score_profile_dimensions(profile, {
        "genres": ["Action", "Abenteuer", "Thriller"],
        "media_types": ["movie"],
    })
    broad = score_profile_dimensions(profile, {
        "genres": ["Action", "Abenteuer", "Animation", "Fantasy", "Science-Fiction"],
        "media_types": ["movie"],
    })
    assert precise["score"] > broad["score"]
    assert broad["unknown_genre_penalty"] > 0


def test_negative_evidence_is_amplified_in_candidate_score():
    profile = {
        "confidence": 0.8,
        "ranking": {"negative_multiplier": 1.55},
        "dimensions": {
            "genres": {"Action": 6, "Animation": -8},
        },
    }
    result = score_profile_dimensions(profile, {
        "genres": ["Action", "Animation"],
    })
    assert result["negative"] < -result["positive"]
    assert result["score"] < 0


def test_jellyfin_ranking_uses_unified_royal_profile(tmp_path):
    store = TasteProfileStore(tmp_path / "taste.json", clock=lambda: 100_000)
    for index in range(4):
        store.record_event(
            "download",
            source="web",
            media_type="movie",
            item_key=f"movie:horror-{index}",
            metadata={"genres": ["Horror", "Thriller"], "year": 2024},
        )
    store.set_feedback(
        "series:anime",
        "less",
        media_type="series",
        metadata={"genres": ["Animation", "Fantasy"]},
    )
    profile = store.public_profile()
    horror = {
        "Id": "horror",
        "Name": "Dark Night",
        "Type": "Movie",
        "ProductionYear": 2024,
        "Genres": ["Horror", "Thriller"],
        "CommunityRating": 7.0,
        "UserData": {},
    }
    anime = {
        "Id": "anime",
        "Name": "Bright Adventure",
        "Type": "Series",
        "ProductionYear": 2024,
        "Genres": ["Animation", "Fantasy", "Adventure"],
        "CommunityRating": 9.0,
        "UserData": {},
    }
    ranked = rank_with_taste_profile([anime, horror], profile, 2)
    assert [item.item["Id"] for item in ranked] == ["horror", "anime"]
