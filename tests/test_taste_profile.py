import json

import pytest

from jellyfin_recommender import Config, SyncResult, run_once
from taste_profile import TasteProfileStore, normalize_metadata


def test_profile_persists_and_aggregates_multiple_dimensions(tmp_path):
    path = tmp_path / "taste.json"
    store = TasteProfileStore(path, clock=lambda: 1_000_000)
    assert store.record_event(
        "download",
        source="web",
        media_type="movie",
        item_key="movie:42",
        title="Beispiel",
        metadata={
            "genres": ["Action", "Thriller"],
            "directors": ["A. Regie"],
            "actors": ["S. Star"],
            "year": 2024,
            "runtime": "112 Min.",
            "language": "de",
        },
    )

    profile = TasteProfileStore(path, clock=lambda: 1_000_000).public_profile()
    assert profile["genres"]["Action"] == 5.0
    assert profile["dimensions"]["directors"]["A. Regie"] == 3.25
    assert profile["dimensions"]["decades"]["2020er"] == 1.5
    assert profile["dimensions"]["runtime_buckets"]["lang"] == 1.25
    assert profile["kinds"]["movie"] == 3.5
    assert profile["recent"][0]["key"] == "movie:42"


def test_duplicate_events_do_not_inflate_profile(tmp_path):
    store = TasteProfileStore(tmp_path / "taste.json", clock=lambda: 50_000)
    kwargs = dict(action="download", source="queue", item_key="episode:1", media_type="series")
    assert store.record_event(**kwargs)
    assert not store.record_event(**kwargs)
    assert store.public_profile()["interactions"] == 1


def test_negative_feedback_blocks_item_and_outweighs_click(tmp_path):
    store = TasteProfileStore(tmp_path / "taste.json", clock=lambda: 100_000)
    metadata = {"genres": ["Horror"]}
    store.record_event("open", item_key="movie:horror", media_type="movie", metadata=metadata)
    store.set_feedback(
        "movie:horror", "dislike", media_type="movie", metadata=metadata,
    )
    profile = store.public_profile()
    assert profile["genres"]["Horror"] < -9
    assert profile["kinds"]["movie"] < 0
    assert profile["blocked_items"] == ["movie:horror"]


def test_explicit_feedback_replaces_previous_choice(tmp_path):
    store = TasteProfileStore(tmp_path / "taste.json")
    store.set_feedback("movie:1", "dislike", metadata={"genres": ["Drama"]})
    store.set_feedback("movie:1", "like", metadata={"genres": ["Drama"]})
    profile = store.public_profile()
    assert profile["genres"]["Drama"] > 0
    assert profile["blocked_items"] == []


def test_old_events_decay(tmp_path):
    now = 400 * 86400.0
    store = TasteProfileStore(tmp_path / "taste.json", clock=lambda: now)
    store.record_event(
        "download", item_key="movie:old", metadata={"genres": ["Alt"]}, at=now - 180 * 86400,
    )
    assert store.public_profile()["genres"]["Alt"] == pytest.approx(2.5, abs=0.001)


def test_legacy_import_is_idempotent(tmp_path):
    store = TasteProfileStore(tmp_path / "taste.json")
    assert store.import_legacy({"genres": {"Komödie": 4}, "kinds": {"movie": 2}})
    assert not store.import_legacy({"genres": {"Horror": 99}})
    profile = store.public_profile()
    assert profile["genres"] == {"Komödie": 4.0}
    assert profile["legacy_imported"] is True


def test_jellyfin_snapshot_is_replaced_not_accumulated(tmp_path):
    store = TasteProfileStore(tmp_path / "taste.json", clock=lambda: 100_000)
    item = {
        "Id": "jf-1",
        "Name": "Film",
        "Type": "Movie",
        "Genres": ["Drama"],
        "People": [{"Name": "Darsteller", "Type": "Actor"}],
        "UserData": {"Played": True, "IsFavorite": True, "Rating": 9},
    }
    assert store.replace_jellyfin_items([item]) == 1
    first = store.public_profile()["genres"]["Drama"]
    assert store.replace_jellyfin_items([item]) == 1
    assert store.public_profile()["genres"]["Drama"] == first
    assert store.public_profile()["jellyfin_updated_at"] == 100_000


def test_jellyfin_recommender_feeds_unified_profile(tmp_path):
    watched = {
        "Id": "jf-1",
        "Name": "Gesehen",
        "Type": "Movie",
        "Genres": ["Mystery"],
        "UserData": {"Played": True, "LastPlayedDate": "1970-01-02T03:46:40Z"},
    }

    class FakeAPI:
        def list_media_items(self, _user_id):
            return [watched]

        def get_or_create_collection(self, _user_id, _name):
            return "collection", False

        def sync_collection(self, _user_id, _collection_id, _ids):
            return SyncResult(added=0, removed=0, unchanged=0)

        def ensure_collection_primary_image(self, _collection_id, _items):
            return False

    config = Config(
        jellyfin_url="http://jellyfin",
        api_key="key",
        user_id="user",
        collection_name="Für dich",
        top_n=20,
        recency_half_life_days=180,
        request_timeout=10,
        page_size=100,
        run_interval_seconds=0,
        log_level="INFO",
    )
    store = TasteProfileStore(tmp_path / "taste.json", clock=lambda: 100_000)
    run_once(config, api=FakeAPI(), profile_callback=store.replace_jellyfin_items)
    profile = store.public_profile()
    assert profile["genres"]["Mystery"] > 0
    assert profile["recent"] == []  # Jellyfin-Rohhistorie wird nicht öffentlich ausgegeben.


def test_public_profile_does_not_expose_queries_or_titles(tmp_path):
    path = tmp_path / "taste.json"
    store = TasteProfileStore(path)
    store.record_event("search", query="mein geheimer Suchtext", title="Privater Titel")
    public = json.dumps(store.public_profile(), ensure_ascii=False)
    assert "geheimer" not in public
    assert "Privater Titel" not in public
    assert "geheimer" in path.read_text(encoding="utf-8")


def test_metadata_normalization_is_bounded_and_accepts_tmdb_objects():
    normalized = normalize_metadata({
        "genres": [{"name": "Action"}, {"name": "Action"}],
        "spoken_languages": [{"name": "Deutsch"}],
        "year": "2022-01-01",
    }, "film")
    assert normalized == {
        "genres": ["Action"],
        "languages": ["Deutsch"],
        "decades": ["2020er"],
        "media_types": ["movie"],
    }


def test_reset_removes_all_learned_data(tmp_path):
    store = TasteProfileStore(tmp_path / "taste.json")
    store.record_event("download", item_key="movie:1", metadata={"genres": ["Action"]})
    store.set_feedback("movie:1", "like", metadata={"genres": ["Action"]})
    store.reset()
    profile = store.public_profile()
    assert profile["interactions"] == 0
    assert profile["genres"] == {}
    assert profile["blocked_items"] == []
