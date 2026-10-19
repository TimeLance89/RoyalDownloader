from features.home_discovery import discover_home_candidates


class Client:
    configured = True
    language = "de-DE"

    def __init__(self):
        self.calls = []

    def _request(self, path, params):
        self.calls.append((path, params))
        if path == "/search/person":
            return {"results": [{"name": "Example Director", "id": 881}]}
        return {"results": [
            {"id": 31, "title": "Example Film", "genre_ids": [53],
             "poster_path": "/31.jpg", "vote_average": 7.3, "vote_count": 200},
        ]}

    def _poster_url(self, path):
        return path

    def _backdrop_url(self, path):
        return path


def test_person_credits_diversify_taste_with_bounded_requests():
    client = Client()
    profile = {"dimensions": {"genres": {"Thriller": 9},
                              "directors": {"Example Director": 15}}, "confidence": 0.4}
    rows = discover_home_candidates(profile, client, day="2026-10-19")
    assert len(rows) == 1
    assert any("Example Director" in row["item"]["discovery_reason"] for row in rows)
    assert [path for path, _ in client.calls].count("/search/person") == 1
    assert any(params.get("with_crew") == 881 for _, params in client.calls)
    assert len(client.calls) <= 3


def test_actor_preference_alone_still_works():
    class ActorClient(Client):
        def _request(self, path, params):
            if path == "/search/person":
                self.calls.append((path, params))
                return {"results": [{"name": "Sample Actor", "id": 991}]}
            return super()._request(path, params)

    client = ActorClient()
    profile = {"dimensions": {"actors": {"Sample Actor": 14}}, "confidence": 0.4}
    rows = discover_home_candidates(profile, client, day="2026-10-19")
    assert rows
    assert rows[0]["item"]["discovery_reason"] == ["Sample Actor"]
    assert any(params.get("with_cast") == 991 for _, params in client.calls)
    assert len(client.calls) == 2


def test_name_mismatch_protects_against_similar_celebrities():
    client = Client()
    profile = {"dimensions": {"directors": {"Different Director": 7},
                              "genres": {"Thriller": 5}}}
    rows = discover_home_candidates(profile, client)
    assert rows
    assert not any("with_crew" in params for _, params in client.calls)
    assert len(client.calls) == 2
