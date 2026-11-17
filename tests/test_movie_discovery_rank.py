from datetime import date, timedelta

from application_services import daily_top, movie_discovery_rank
from providers.models import FilmpalastSearchResult


def test_persistent_head_rotates_after_three_days_and_stays_stable_within_day(tmp_path, monkeypatch):
    monkeypatch.setattr(movie_discovery_rank, "config_path", lambda: tmp_path / "settings.ini")
    monkeypatch.setattr(daily_top, "_configuration", lambda: ("test",))
    monkeypatch.setattr(movie_discovery_rank, "_signals", lambda *_: {})
    start = date(2026, 11, 1)
    day = start
    monkeypatch.setattr(daily_top, "chart_day", lambda: day)
    featured = movie_discovery_rank.FEATURED
    entries = [("filmpalast", FilmpalastSearchResult(f"Film {i}", str(i), "", year="2026"))
               for i in range(featured)]

    def rank(rows):
        return movie_discovery_rank.rank_movie_browse(
            rows, {"filmpalast": [item for _, item in rows]}, ["filmpalast"], {"de"},
        )

    for offset in range(3):
        day = start + timedelta(days=offset)
        _, reasons = rank(entries)
        assert reasons == {}

    day = start + timedelta(days=3)
    newcomers = [("filmpalast", FilmpalastSearchResult(f"New {i}", f"new-{i}", "", year="2026"))
                 for i in range(featured)]
    rows = newcomers + entries
    ordered, reasons = rank(rows)
    assert ordered[:featured] == [entry for entry in ordered if entry in newcomers]
    assert reasons["new-0"] == "new"
    assert rank(list(reversed(rows))) == (ordered, reasons)

    identity = daily_top._candidate_identity("movie", entries[0][1].title, "2026")
    day += timedelta(days=1)
    monkeypatch.setattr(movie_discovery_rank, "_signals", lambda *_: {identity: 25})
    ordered, reasons = rank(entries + newcomers)
    assert entries[0] in ordered[:featured]
    assert reasons[entries[0][1].slug] == "rising"
