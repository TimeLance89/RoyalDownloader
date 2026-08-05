from tmdb_client import TMDBClient


class FakeTMDBClient(TMDBClient):
    def __init__(self):
        super().__init__(api_key="test")

    def _request(self, path, params=None):
        if path == "/search/tv":
            return {"results": [{
                "id": 42,
                "name": "Testserie",
                "original_name": "Test Series",
                "first_air_date": "2024-01-02",
                "poster_path": "/poster.jpg",
                "backdrop_path": "/wallpaper.jpg",
                "overview": "Beschreibung",
                "genre_ids": [18, 9648],
                "vote_average": 8.1,
                "vote_count": 50,
                "popularity": 10,
            }]}
        if path == "/genre/tv/list":
            return {"genres": [
                {"id": 18, "name": "Drama"},
                {"id": 9648, "name": "Mystery"},
            ]}
        return {}


def test_series_summary_contains_landscape_artwork_and_genres():
    summary = FakeTMDBClient().series_summary("Testserie", "2024")

    assert summary["backdrop_url"].endswith("/wallpaper.jpg")
    assert summary["genres"] == ["Drama", "Mystery"]
