from tmdb_client import TMDBClient


class FakeTMDBClient(TMDBClient):
    def __init__(self):
        super().__init__(api_key="test")

    def _request(self, path, params=None):
        if path == "/movie/99":
            return {
                "id": 99,
                "title": "Testfilm",
                "original_title": "Test Movie",
                "release_date": "2025-03-04",
                "poster_path": "/movie-poster.jpg",
                "backdrop_path": "/movie-wallpaper.jpg",
                "overview": "Filmbeschreibung",
                "genres": [{"id": 18, "name": "Drama"}],
                "vote_average": 7.4,
                "vote_count": 80,
                "recommendations": {"results": [
                    {
                        "id": 100,
                        "title": "Ähnlicher Film",
                        "release_date": "2024-08-09",
                        "backdrop_path": "/similar-wallpaper.jpg",
                        "poster_path": "/similar-poster.jpg",
                        "overview": "Eine verwandte Geschichte.",
                        "vote_average": 8.2,
                        "vote_count": 120,
                        "original_language": "de",
                    },
                    {
                        "id": 101,
                        "title": "Nur mit Poster",
                        "poster_path": "/poster-only.jpg",
                    },
                ]},
            }
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


def test_movie_summary_by_id_uses_exact_tmdb_artwork():
    summary = FakeTMDBClient().movie_summary_by_id(99, "Fallback")

    assert summary["tmdb_id"] == 99
    assert summary["cover_url"].endswith("/movie-poster.jpg")
    assert summary["backdrop_url"].endswith("/movie-wallpaper.jpg")
    assert summary["genres"] == ["Drama"]


def test_movie_details_include_landscape_recommendations_only():
    movie = FakeTMDBClient().movie_by_id(99)

    assert movie["similar_titles"] == [{
        "tmdb_id": 100,
        "slug": "tmdb:100",
        "title": "Ähnlicher Film",
        "year": "2024",
        "backdrop_url": "https://image.tmdb.org/t/p/w1280/similar-wallpaper.jpg",
        "description": "Eine verwandte Geschichte.",
        "rating": 8.2,
        "vote_count": 120,
        "original_language": "DE",
    }]
