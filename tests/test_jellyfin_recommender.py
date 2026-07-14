import base64
import json
import math
import unittest
from datetime import datetime, timedelta, timezone

from jellyfin_recommender import (
    ACTOR_LIMIT,
    Config,
    ConfigurationError,
    JellyfinAPI,
    RecommenderError,
    build_profile,
    is_watched,
    item_attributes,
    rank_recommendations,
    run_once,
    score_item,
    split_watched,
    watched_item_weight,
)


def media_item(item_id, name, *, played=False, play_count=0, **extra):
    item = {
        "Id": item_id,
        "Name": name,
        "Type": "Movie",
        "Genres": ["Drama"],
        "Tags": [],
        "Studios": [],
        "People": [],
        "UserData": {"Played": played, "PlayCount": play_count},
    }
    item.update(extra)
    return item


class FakeResponse:
    def __init__(self, payload=None, *, content=b"", headers=None, status_code=200):
        self.payload = payload
        self.content = content
        self.headers = dict(headers or {})
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, responses=()):
        self.headers = {}
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError("Unerwarteter HTTP-Aufruf")
        return self.responses.pop(0)


class ConfigTests(unittest.TestCase):
    def test_required_values_and_defaults(self):
        config = Config.from_env({
            "JELLYFIN_URL": "http://jellyfin:8096/",
            "JELLYFIN_API_KEY": "secret",
            "JELLYFIN_USER_ID": "user",
        })

        self.assertEqual(config.jellyfin_url, "http://jellyfin:8096")
        self.assertEqual(config.collection_name, "Für dich empfohlen")
        self.assertEqual(config.top_n, 20)
        self.assertEqual(config.request_timeout, 120)
        self.assertEqual(config.page_size, 100)
        self.assertEqual(config.run_interval_seconds, 0)

    def test_heavy_item_pages_are_capped(self):
        config = Config.from_env({
            "JELLYFIN_URL": "http://jellyfin:8096",
            "JELLYFIN_API_KEY": "secret",
            "JELLYFIN_USER_ID": "user",
            "PAGE_SIZE": "500",
        })

        self.assertEqual(config.page_size, 100)

    def test_invalid_configuration_is_rejected(self):
        with self.assertRaises(ConfigurationError):
            Config.from_env({})
        with self.assertRaises(ConfigurationError):
            Config.from_env({
                "JELLYFIN_URL": "jellyfin:8096",
                "JELLYFIN_API_KEY": "secret",
                "JELLYFIN_USER_ID": "user",
            })
        with self.assertRaises(ConfigurationError):
            Config.from_env({
                "JELLYFIN_URL": "http://jellyfin",
                "JELLYFIN_API_KEY": "secret",
                "JELLYFIN_USER_ID": "user",
                "TOP_N": "0",
            })


class ProfileTests(unittest.TestCase):
    def test_watched_uses_played_or_positive_play_count(self):
        self.assertTrue(is_watched(media_item("1", "A", played=True)))
        self.assertTrue(is_watched(media_item("2", "B", play_count=2)))
        self.assertFalse(is_watched(media_item("3", "C")))
        self.assertFalse(is_watched({"Id": "4", "UserData": {"Played": "false"}}))

        watched, unseen = split_watched([
            media_item("1", "A", played=True),
            media_item("1", "A duplicate", played=False),
            media_item("2", "B"),
            {"Name": "Ohne ID"},
        ])
        self.assertEqual([item["Id"] for item in watched], ["1"])
        self.assertEqual([item["Id"] for item in unseen], ["2"])

    def test_attributes_are_normalized_deduplicated_and_actor_limited(self):
        people = [{"Name": "Regie Eins", "Type": "Director"}]
        people += [
            {"Name": f"Darsteller {index}", "Type": "Actor"}
            for index in range(ACTOR_LIMIT + 2)
        ]
        attributes = item_attributes({
            "Genres": ["Science Fiction", " science   fiction "],
            "Tags": ["Düster", "DÜSTER"],
            "Studios": [{"Name": "Studio A"}, {"Name": "studio a"}],
            "People": people,
        })

        self.assertEqual(attributes["genres"], ["science fiction"])
        self.assertEqual(attributes["tags"], ["düster"])
        self.assertEqual(attributes["studios"], ["studio a"])
        self.assertEqual(attributes["directors"], ["regie eins"])
        self.assertEqual(len(attributes["actors"]), ACTOR_LIMIT)

    def test_favorite_rating_and_recency_raise_profile_weight(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        base = media_item("1", "A", played=True)
        preferred = media_item("2", "B", played=True, UserData={
            "Played": True,
            "IsFavorite": True,
            "Rating": 10,
            "LastPlayedDate": now.isoformat(),
        })
        old = media_item("3", "C", played=True, UserData={
            "Played": True,
            "LastPlayedDate": (now - timedelta(days=360)).isoformat(),
        })

        base_weight = watched_item_weight(base, now, 180)
        preferred_weight = watched_item_weight(preferred, now, 180)
        old_weight = watched_item_weight(old, now, 180)

        self.assertGreater(preferred_weight, old_weight)
        self.assertGreater(old_weight, base_weight)
        self.assertEqual(watched_item_weight(preferred, now, 0), 3.0)

    def test_many_values_share_an_items_category_contribution(self):
        now = datetime(2026, 7, 13, tzinfo=timezone.utc)
        watched = media_item(
            "1", "A", played=True, Genres=["Drama"], Tags=["A", "B"],
        )
        profile = build_profile([watched], recency_half_life_days=0, now=now)

        self.assertAlmostEqual(profile["genres"]["drama"], math.log1p(1.0))
        self.assertAlmostEqual(profile["tags"]["a"], math.log1p(0.5))
        self.assertAlmostEqual(profile["tags"]["b"], math.log1p(0.5))


class ScoringTests(unittest.TestCase):
    def setUp(self):
        watched = media_item(
            "watched",
            "Gesehen",
            played=True,
            Genres=["Drama", "Thriller"],
            Tags=["Düster"],
            Studios=[{"Name": "Studio A"}],
            People=[
                {"Name": "Regie Eins", "Type": "Director"},
                {"Name": "Darsteller Eins", "Type": "Actor"},
            ],
        )
        self.profile = build_profile([watched], recency_half_life_days=0)

    def test_more_overlap_scores_higher_and_rating_is_only_a_small_bonus(self):
        exact = media_item(
            "exact", "Exakt", Genres=["Drama", "Thriller"], Tags=["Düster"],
            Studios=[{"Name": "Studio A"}],
            People=[
                {"Name": "Regie Eins", "Type": "Director"},
                {"Name": "Darsteller Eins", "Type": "Actor"},
            ],
            CommunityRating=5,
        )
        partial = media_item(
            "partial", "Teilweise", Genres=["Drama", "Komödie"], CommunityRating=10,
        )
        unrelated = media_item(
            "none", "Ohne Treffer", Genres=["Western"], CommunityRating=10,
        )

        exact_score = score_item(exact, self.profile)
        partial_score = score_item(partial, self.profile)
        unrelated_score = score_item(unrelated, self.profile)

        self.assertGreater(exact_score.score, partial_score.score)
        self.assertEqual(unrelated_score.content_score, 0)
        self.assertEqual(unrelated_score.rating_bonus, 0.05)
        ranked = rank_recommendations([unrelated, partial, exact], self.profile, 20)
        self.assertEqual(
            [entry.item["Id"] for entry in ranked], ["exact", "partial", "none"],
        )


class JellyfinAPITests(unittest.TestCase):
    def test_auth_header_and_media_query_pagination(self):
        session = FakeSession([
            FakeResponse({"Items": [{"Id": "1"}], "TotalRecordCount": 2}),
            FakeResponse({"Items": [{"Id": "2"}], "TotalRecordCount": 2}),
        ])
        api = JellyfinAPI("http://jellyfin", "key", page_size=1, session=session)

        items = api.list_media_items("user")

        self.assertEqual([item["Id"] for item in items], ["1", "2"])
        self.assertEqual(session.headers["Authorization"], 'MediaBrowser Token="key"')
        first_params = session.calls[0][2]["params"]
        self.assertEqual(first_params["userId"], "user")
        self.assertEqual(first_params["includeItemTypes"], "Movie,Series")
        self.assertEqual(first_params["fields"], "Genres,Tags,Studios,People")
        self.assertNotIn("CommunityRating", first_params["fields"])
        self.assertEqual(session.calls[1][2]["params"]["startIndex"], 1)

    def test_duplicate_exact_collection_names_abort(self):
        session = FakeSession([FakeResponse({
            "Items": [
                {"Id": "a", "Name": "Für dich empfohlen"},
                {"Id": "b", "Name": " FÜR DICH EMPFOHLEN "},
            ],
            "TotalRecordCount": 2,
        })])
        api = JellyfinAPI("http://jellyfin", "key", session=session)

        with self.assertRaises(RecommenderError):
            api.find_collection("user", "Für dich empfohlen")

    def test_create_collection_uses_official_endpoint(self):
        session = FakeSession([FakeResponse({"Id": "collection-id"})])
        api = JellyfinAPI("http://jellyfin", "key", session=session)

        self.assertEqual(api.create_collection("Empfohlen"), "collection-id")
        method, url, kwargs = session.calls[0]
        self.assertEqual((method, url), ("POST", "http://jellyfin/Collections"))
        self.assertEqual(kwargs["params"], {"name": "Empfohlen", "isLocked": "false"})

    def test_existing_collection_id_is_reused(self):
        session = FakeSession([FakeResponse({
            "Items": [{"Id": "stable-id", "Name": "Empfohlen"}],
            "TotalRecordCount": 1,
        })])
        api = JellyfinAPI("http://jellyfin", "key", session=session)

        self.assertEqual(
            api.get_or_create_collection("user", "Empfohlen"),
            ("stable-id", False),
        )
        self.assertEqual([call[0] for call in session.calls], ["GET"])

    def test_collection_mutations_use_collection_items_endpoint(self):
        session = FakeSession([FakeResponse(), FakeResponse()])
        api = JellyfinAPI("http://jellyfin", "key", session=session)

        api.add_to_collection("collection", ["a", "b"])
        api.remove_from_collection("collection", ["old"])

        self.assertEqual(
            [(call[0], call[1], call[2]["params"]) for call in session.calls],
            [
                (
                    "POST",
                    "http://jellyfin/Collections/collection/Items",
                    {"ids": "a,b"},
                ),
                (
                    "DELETE",
                    "http://jellyfin/Collections/collection/Items",
                    {"ids": "old"},
                ),
            ],
        )

    def test_existing_collection_cover_is_preserved(self):
        session = FakeSession([FakeResponse([{"ImageType": "Primary"}])])
        api = JellyfinAPI("http://jellyfin", "key", session=session)

        changed = api.ensure_collection_primary_image(
            "collection", [{"Id": "movie"}],
        )

        self.assertFalse(changed)
        self.assertEqual(len(session.calls), 1)

    def test_best_available_poster_becomes_collection_cover(self):
        poster = b"jpeg-poster"
        session = FakeSession([
            FakeResponse([]),
            FakeResponse([{"ImageType": "Primary"}]),
            FakeResponse(content=poster, headers={"Content-Type": "image/jpeg"}),
            FakeResponse(),
        ])
        api = JellyfinAPI("http://jellyfin", "key", session=session)

        changed = api.ensure_collection_primary_image(
            "collection", [{"Id": "best-movie"}],
        )

        self.assertTrue(changed)
        upload = session.calls[-1]
        self.assertEqual(
            (upload[0], upload[1]),
            ("POST", "http://jellyfin/Items/collection/Images/Primary"),
        )
        self.assertEqual(upload[2]["data"], base64.b64encode(poster))
        self.assertEqual(upload[2]["headers"], {"Content-Type": "image/jpeg"})

    def test_moonfin_dashboard_settings_are_merged_and_verified(self):
        saved = {
            "schemaVersion": 2,
            "syncEnabled": True,
            "global": {
                "displayCollectionsRows": True,
                "homeRowOrder": ["resume", "collections", "latestmedia"],
                "mediaBarCollectionIds": ["recommendation", "old"],
            },
            "tv": {
                "displayCollectionsRows": True,
                "homeRowOrder": ["resume", "collections", "latestmedia"],
                "mediaBarCollectionIds": ["recommendation"],
            },
        }
        session = FakeSession([
            FakeResponse({"installed": True}),
            FakeResponse({
                "schemaVersion": 2,
                "syncEnabled": False,
                "global": {
                    "homeRowOrder": ["resume", "latestmedia"],
                    "mediaBarCollectionIds": ["old"],
                    "watchedIndicator": "checkmark",
                },
                "tv": {},
            }),
            FakeResponse(),
            FakeResponse(saved),
        ])
        api = JellyfinAPI("http://jellyfin", "key", session=session)

        configured = api.configure_moonfin_dashboard(
            "user", "recommendation", "Für dich empfohlen",
        )

        self.assertTrue(configured)
        post = session.calls[2]
        self.assertEqual((post[0], post[1]), (
            "POST", "http://jellyfin/Moonfin/Settings/user",
        ))
        payload = json.loads(post[2]["data"].decode("utf-8"))
        global_profile = payload["settings"]["global"]
        self.assertEqual(global_profile["watchedIndicator"], "checkmark")
        self.assertEqual(
            global_profile["mediaBarCollectionIds"], ["recommendation", "old"],
        )
        self.assertEqual(
            global_profile["homeRowOrder"],
            ["resume", "collections", "latestmedia"],
        )
        dynamic = [
            section for section in global_profile["homeSections"]
            if section.get("pluginAdditionalData") == "recommendation"
        ]
        self.assertEqual(len(dynamic), 1)
        self.assertTrue(dynamic[0]["enabled"])
        self.assertEqual(dynamic[0]["serverId"], "http://jellyfin")

    def test_missing_moonfin_plugin_is_a_clean_noop(self):
        session = FakeSession([FakeResponse(status_code=404)])
        api = JellyfinAPI("http://jellyfin", "key", session=session)

        self.assertFalse(api.configure_moonfin_dashboard(
            "user", "collection", "Empfohlen",
        ))
        self.assertEqual(len(session.calls), 1)


class MemoryAPI(JellyfinAPI):
    def __init__(self, current):
        self.current = set(current)
        self.calls = []

    def list_collection_items(self, user_id, collection_id):
        self.calls.append(("list", tuple(sorted(self.current))))
        return [{"Id": item_id} for item_id in sorted(self.current)]

    def add_to_collection(self, collection_id, ids):
        self.calls.append(("add", tuple(ids)))
        self.current.update(ids)

    def remove_from_collection(self, collection_id, ids):
        self.calls.append(("remove", tuple(ids)))
        self.current.difference_update(ids)


class CollectionSyncTests(unittest.TestCase):
    def test_equal_sets_are_a_noop(self):
        api = MemoryAPI({"a", "b"})

        result = api.sync_collection("user", "collection", ["b", "a", "a"])

        self.assertEqual((result.added, result.removed, result.unchanged), (0, 0, 2))
        self.assertEqual([call[0] for call in api.calls], ["list"])

    def test_add_is_verified_before_stale_items_are_removed(self):
        api = MemoryAPI({"old", "keep"})

        result = api.sync_collection("user", "collection", ["keep", "new"])

        self.assertEqual(api.current, {"keep", "new"})
        self.assertEqual((result.added, result.removed, result.unchanged), (1, 1, 1))
        self.assertEqual(
            [call[0] for call in api.calls],
            ["list", "add", "list", "remove", "list"],
        )

    def test_failed_add_verification_never_removes_old_items(self):
        class BrokenAddAPI(MemoryAPI):
            def add_to_collection(self, collection_id, ids):
                self.calls.append(("add", tuple(ids)))

        api = BrokenAddAPI({"old"})

        with self.assertRaises(RecommenderError):
            api.sync_collection("user", "collection", ["new"])

        self.assertEqual(api.current, {"old"})
        self.assertNotIn("remove", [call[0] for call in api.calls])

    def test_no_unseen_items_synchronizes_an_empty_collection(self):
        class RunAPI:
            def __init__(self):
                self.desired_ids = None

            def list_media_items(self, user_id):
                return [media_item("watched", "Gesehen", played=True)]

            def get_or_create_collection(self, user_id, name):
                return "collection", False

            def sync_collection(self, user_id, collection_id, desired_ids):
                self.desired_ids = desired_ids
                from jellyfin_recommender import SyncResult
                return SyncResult(added=0, removed=1, unchanged=0)

        api = RunAPI()
        config = Config("http://jellyfin", "key", "user")

        self.assertEqual(run_once(config, api), [])
        self.assertEqual(api.desired_ids, [])


if __name__ == "__main__":
    unittest.main()
