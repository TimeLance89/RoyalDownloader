from features.home_discovery import discover_home_candidates


class Client:
    configured = True
    language = "de-DE"

    def __init__(self):
        self.calls = []

    def _request(self, path, params):
        self.calls.append((path, params))
        if path == "/search/collection":
            return {"results": [{"name": "Amazing Trilogy", "id": 601}]}
        if path == "/collection/601":
            return {"parts": [
                {"id": 143, "title": "Part 2", "genre_ids": [28], "vote_average": 7.6,
                 "vote_count": 122, "poster_path": "/143.jpg"},
            ]}
        return {"results": []}

    def _poster_url(self, path):
        return path

    def _backdrop_url(self, path):
        return path


def test_franchise_only_taste_can_open_the_full_movie_collection():
    client = Client()
    profile = {"dimensions": {"franchises": {"Amazing Trilogy": 12}}, "confidence": .6}
    result = discover_home_candidates(profile, client)
    assert len(result) == 1
    assert result[0]["item"]["title"] == "Part 2"
    assert result[0]["item"]["discovery_reason"] == ["Amazing Trilogy"]
    assert len(client.calls) == 2
    assert all("user_id" not in params for _, params in client.calls)


def test_franchise_title_mismatch_does_not_guess_collection_identity():
    class Mismatch(Client):
        def _request(self, path, params):
            if path == "/search/collection":
                self.calls.append((path, params))
                return {"results": [{"name": "A different trilogy", "id": 601}]}
            return super()._request(path, params)

    client = Mismatch()
    result = discover_home_candidates(
        {"dimensions": {"franchises": {"Amazing Trilogy": 12}}}, client)
    assert result == []
    assert len(client.calls) == 1


def test_franchise_seed_is_bounded_to_three_tmdb_calls_with_genre():
    client = Client()
    profile = {"dimensions": {
        "franchises": {"Amazing Trilogy": 12}, "genres": {"Action": 4},
    }}
    assert discover_home_candidates(profile, client)
    assert len(client.calls) == 3
