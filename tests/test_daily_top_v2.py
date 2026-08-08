from datetime import date

import application_services.daily_top as daily_top


def candidate(
    kind="movie", title="Example", year="2026", score=0.0, providers=None, tmdb_id=None,
):
    item = {
        "title": title,
        "year": year,
        "slug": f"{title.lower()}-{year}" if kind == "movie" else "",
        "base_slug": f"{title.lower()}-{year}" if kind == "series" else "",
    }
    if tmdb_id:
        item["tmdb_id"] = tmdb_id
    return {
        "identity": daily_top._candidate_identity(kind, title, year, tmdb_id),
        "kind": kind,
        "title": title,
        "year": year,
        "item": item,
        "provider_ranks": dict(providers or {}),
        "availability_providers": list((providers or {}).keys()),
        "score": score,
    }


def test_provider_consensus_beats_single_source_leader_when_other_signals_are_equal():
    single = candidate(providers={"one": 1})
    consensus = candidate(providers={"one": 3, "two": 5, "three": 2})
    single_score = daily_top._score_candidate(single, date(2026, 8, 8))["score"]
    consensus_score = daily_top._score_candidate(consensus, date(2026, 8, 8))["score"]
    assert consensus_score > single_score


def test_rating_confidence_prevents_tiny_vote_sample_from_winning():
    assert daily_top._rating_confidence_score(9.5, 6) < daily_top._rating_confidence_score(
        8.1, 25_000,
    )


def test_freshness_is_small_but_current_and_current_series_trend_stays_relevant():
    recent = daily_top._freshness_score(
        "2026-08-01", "2026", kind="movie", is_trending=False, today=date(2026, 8, 8),
    )
    old = daily_top._freshness_score(
        "2015-01-01", "2015", kind="movie", is_trending=False, today=date(2026, 8, 8),
    )
    old_series_trending = daily_top._freshness_score(
        "2015-01-01", "2015", kind="series", is_trending=True, today=date(2026, 8, 8),
    )
    assert recent > old
    assert old_series_trending >= 55


def test_yearless_provider_duplicate_merges_only_when_year_is_unambiguous():
    known = candidate(title="Same Film", year="2026", providers={"one": 2})
    unknown = candidate(title="Same Film", year="", providers={"two": 4})
    merged = daily_top._merge_title_year_fallbacks([known, unknown])
    assert len(merged) == 1
    assert merged[0]["provider_ranks"] == {"one": 2, "two": 4}

    remake = candidate(title="Same Film", year="1999", providers={"three": 1})
    unresolved = daily_top._merge_title_year_fallbacks([known, remake, unknown])
    assert len(unresolved) == 3


def test_tmdb_identity_merges_provider_aliases_and_keeps_best_ranks():
    first = candidate(title="Localized", year="2026", providers={"one": 6}, tmdb_id=123)
    second = candidate(title="Original", year="2026", providers={"two": 2}, tmdb_id=123)
    first["tmdb_id"] = 123
    second["tmdb_id"] = 123
    merged = daily_top._merge_candidates_by_identity([first, second])
    assert len(merged) == 1
    assert merged[0]["identity"] == "movie:tmdb:123"
    assert merged[0]["provider_ranks"] == {"one": 6, "two": 2}


def test_soft_diversity_caps_dominant_kind_only_when_three_relevant_others_exist():
    movies = [candidate(title=f"Movie {index}", score=100 - index) for index in range(8)]
    series = [
        candidate(kind="series", title=f"Series {index}", score=91 - index)
        for index in range(3)
    ]
    ranked = daily_top._apply_diversity(movies + series, 20)
    top_ten = ranked[:10]
    assert sum(item["kind"] == "movie" for item in top_ten) <= 7
    assert sum(item["kind"] == "series" for item in top_ten) >= 3
    assert [item["global_rank"] for item in ranked] == list(range(1, len(ranked) + 1))


def test_soft_diversity_does_not_force_other_kind_when_only_two_are_relevant():
    movies = [candidate(title=f"Movie {index}", score=100 - index) for index in range(10)]
    series = [
        candidate(kind="series", title=f"Series {index}", score=90 - index)
        for index in range(2)
    ]
    ranked = daily_top._apply_diversity(movies + series, 12)
    assert sum(item["kind"] == "movie" for item in ranked[:10]) == 10
    assert sum(item["kind"] == "series" for item in ranked[:10]) == 0
