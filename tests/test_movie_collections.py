from pathlib import Path
from unittest.mock import patch

from tmdb_client import TMDBClient


ROOT = Path(__file__).resolve().parents[1]


def test_movie_collection_search_uses_only_tmdb_collection_endpoint():
    client = TMDBClient("key", language="de-DE")
    payload = {"results": [{
        "id": 91361,
        "name": "Halloween Filmreihe",
        "original_name": "Halloween Collection",
        "poster_path": "/halloween.jpg",
        "backdrop_path": "/halloween-wide.jpg",
    }]}

    with patch.object(client, "_request", return_value=payload) as request:
        results = client.search_movie_collections("Halloween")

    assert results[0]["collection_id"] == 91361
    assert results[0]["kind"] == "collection"
    assert request.call_args.args[0] == "/search/collection"


def test_movie_collection_sorts_parts_and_keeps_unreleased_films():
    client = TMDBClient("key")
    payload = {
        "id": 91361,
        "name": "Halloween Collection",
        "parts": [
            {"id": 3, "title": "Später", "release_date": "1982-10-22"},
            {"id": 1, "title": "Halloween", "release_date": "1978-10-24"},
            {"id": 9, "title": "Ohne Termin", "release_date": ""},
        ],
    }

    with patch.object(client, "_request", return_value=payload):
        result = client.movie_collection(91361)

    assert [part["tmdb_id"] for part in result["parts"]] == [1, 3, 9]
    assert result["part_count"] == 3
    assert result["parts"][0]["slug"] == "tmdb:1"


def test_collection_flow_checks_jellyfin_before_providers_and_uses_queue_truth():
    source = (ROOT / "web" / "screens" / "movie-collections.js").read_text(
        encoding="utf-8",
    )
    open_flow = source[source.index("async function openMovieCollection"):]
    assert open_flow.index("await checkMovieCollectionJellyfin") < open_flow.index(
        "resolveMovieCollectionParts(resolvable",
    )
    assert 'status === "owned"' in source
    assert "collectionReleaseIsFuture(part)" in source
    assert "response.skipped_details?.[slug]" in source
    assert "state.queuedSlugs.has(part.slug)" in source
    assert "selected: true" in source
    assert 'normalized.includes("in jellyfin vorhanden")' in source
    assert "requests.length; index += 100" in source
    assert 'collectionLibraryAllowsDownload(record.libraryStatus)' in source
    assert 'providerStatus: "blocked"' in source
    assert 'download.textContent = "Jellyfin prüfen"' in source
    assert 'normalized.includes("sicherheitsprüfung")' in source
    assert "retryMovieCollectionJellyfinPart(part)" in source
