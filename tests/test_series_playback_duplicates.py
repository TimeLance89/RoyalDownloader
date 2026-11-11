from uuid import UUID

import pytest
from fastapi import HTTPException

from api.api_movie_playback_router import _matched_series_inventory

A, B, E1, E2 = (UUID(int=n).hex for n in range(1, 5))


def test_same_tmdb_library_copies_combine_seasons_without_duplicate_items():
    library = [{"id": A, "tmdb_id": "66732"}, {"id": B, "tmdb_id": "66732"}]
    one = {"id": E1, "season": 1, "episode": 1}
    two = {"id": E2, "season": 2, "episode": 1}
    calls = []

    def fetch(identity):
        calls.append(identity)
        return [two, one] if identity == A else [one]

    assert _matched_series_inventory({A, B}, library, 66732, fetch) == [one, two]
    assert set(calls) == {A, B}


@pytest.mark.parametrize("tmdb,library", [
    (None, [{"id": A}, {"id": B}]),
    (66732, [{"id": A, "tmdb_id": "66732"}, {"id": B, "tmdb_id": "99"}]),
    (66732, [{"id": A, "tmdb_id": "66732"}, {"id": B}]),
    (66732, [{"id": A, "tmdb_id": "66732"}]),
])
def test_ambiguous_identity_never_fetches_or_merges(tmdb, library):
    def fetch(_):
        pytest.fail("Ambiguous identity must never fetch episodes")

    assert _matched_series_inventory({A, B}, library, tmdb, fetch) == []


def test_invalid_series_id_is_explicit_error():
    with pytest.raises(HTTPException) as error:
        _matched_series_inventory({"invalid"}, [], None, lambda _: [])
    assert error.value.status_code == 502


@pytest.mark.parametrize("status", [403, 404, 503])
def test_profile_hidden_copy_is_skipped_but_other_errors_propagate(status):
    library = [{"id": A, "tmdb_id": "66732"}, {"id": B, "tmdb_id": "66732"}]
    episode = {"id": E1, "season": 1, "episode": 1}

    def fetch(identity):
        if identity == A:
            raise HTTPException(status)
        return [episode]

    if status == 404:
        assert _matched_series_inventory({A, B}, library, 66732, fetch) == [episode]
    else:
        with pytest.raises(HTTPException) as error:
            _matched_series_inventory({A, B}, library, 66732, fetch)
        assert error.value.status_code == status


def test_single_series_preserves_access_errors():
    def fetch(_):
        raise HTTPException(404)

    with pytest.raises(HTTPException):
        _matched_series_inventory({A}, [], None, fetch)


def test_no_matching_series_does_not_fetch():
    assert _matched_series_inventory(None, [], 66732, lambda _: pytest.fail()) == []

def test_episode_cards_keep_their_own_overview_and_allow_missing_text():
    from api.api_movie_playback_router import _episode_cards

    base = {"Type": "Episode", "ParentIndexNumber": 1, "SeriesName": "Serie"}
    cards = _episode_cards([
        dict(base, Id=E1, IndexNumber=1, Name="Erste Folge", Overview="  Handlung eins.  "),
        dict(base, Id=E2, IndexNumber=2, Name="Zweite Folge", Overview="Handlung zwei."),
        dict(base, Id=A, IndexNumber=3, Name="Dritte Folge", Overview=None),
        dict(base, Id=B, IndexNumber=4, Name="Platzhalter", LocationType="Virtual"),
    ])
    assert [(card["episode"], card["description"]) for card in cards] == [
        (1, "Handlung eins."), (2, "Handlung zwei."), (3, ""),
    ]
