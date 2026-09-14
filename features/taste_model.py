"""Shared taste-profile normalization and candidate scoring policy.

The persistence layer keeps raw evidence; this module defines how profile
weights are interpreted when a concrete movie or series is ranked.  Keeping
that policy independent from HTTP/UI code lets the Royal home screen and the
Jellyfin recommendation collection follow the same semantics.
"""

from __future__ import annotations

import math
import unicodedata
from typing import Any, Mapping, Sequence


GENRE_ALIASES = {
    "action": "Action",
    "adventure": "Abenteuer",
    "abenteuer": "Abenteuer",
    "animation": "Animation",
    "anime": "Anime",
    "comedy": "Komödie",
    "komodie": "Komödie",
    "komoedie": "Komödie",
    "drama": "Drama",
    "family": "Familie",
    "familie": "Familie",
    "fantasy": "Fantasy",
    "history": "Geschichte",
    "geschichte": "Geschichte",
    "horror": "Horror",
    "crime": "Krimi",
    "krimi": "Krimi",
    "music": "Musik",
    "musik": "Musik",
    "mystery": "Mystery",
    "romance": "Romanze",
    "romanze": "Romanze",
    "sciencefiction": "Science-Fiction",
    "scifi": "Science-Fiction",
    "sf": "Science-Fiction",
    "thriller": "Thriller",
    "war": "Krieg",
    "krieg": "Krieg",
    "western": "Western",
    "documentary": "Dokumentation",
    "dokumentation": "Dokumentation",
    "dokumentarfilm": "Dokumentation",
}

MEDIA_TYPE_ALIASES = {
    "movie": "movie",
    "film": "movie",
    "series": "series",
    "serie": "series",
    "tv": "series",
    "anime": "anime",
}

# Profile values already contain the evidence-side dimension factor.  These
# weights describe how discriminating a dimension is when evaluating a new
# candidate.  Broad genres still matter most, but a director/tag/franchise
# combination can beat a superficial Action/Adventure overlap.
MATCH_FACTORS = {
    "genres": 1.00,
    "tags": 0.72,
    "studios": 0.34,
    "directors": 0.82,
    "actors": 0.46,
    "languages": 0.18,
    "decades": 0.28,
    "runtime_buckets": 0.18,
    "media_types": 0.46,
    "franchises": 0.74,
}

RANKING_POLICY = {
    "negative_multiplier": 1.55,
    "unknown_genre_penalty": 1.35,
    "unknown_genre_confidence_floor": 0.55,
    "personal_min_affinity": 1.25,
    "personal_min_coverage": 0.18,
    "adjacent_min_affinity": 0.10,
}


def normalize_token(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return "".join(char for char in text.casefold() if char.isalnum())


def canonical_value(dimension: str, value: Any) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    if dimension == "genres":
        return GENRE_ALIASES.get(normalize_token(text), text)
    if dimension == "media_types":
        return MEDIA_TYPE_ALIASES.get(normalize_token(text), text.casefold())
    if dimension == "languages":
        token = normalize_token(text)
        if token in {"de", "deu", "ger", "german", "deutsch"}:
            return "de"
        if token in {"en", "eng", "english", "englisch"}:
            return "en"
    return text


def canonical_values(dimension: str, values: Sequence[Any] | Any, limit: int = 12) -> list[str]:
    source = values if isinstance(values, (list, tuple, set)) else [values]
    result: list[str] = []
    seen: set[str] = set()
    for value in source:
        canonical = canonical_value(dimension, value)
        key = canonical.casefold()
        if canonical and key not in seen:
            seen.add(key)
            result.append(canonical)
        if len(result) >= limit:
            break
    return result


def _profile_lookup(values: Mapping[str, Any]) -> dict[str, tuple[str, float]]:
    lookup: dict[str, tuple[str, float]] = {}
    for name, raw_score in values.items():
        try:
            score = float(raw_score)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(score):
            continue
        lookup[str(name).casefold()] = (str(name), score)
    return lookup


def score_profile_dimensions(
    profile: Mapping[str, Any],
    candidate_dimensions: Mapping[str, Sequence[Any]],
) -> dict[str, Any]:
    """Score one candidate against a public TasteProfileStore profile.

    Candidate-rich dimensions are normalized by sqrt(cardinality), preventing
    a title with ten generic tags from automatically beating one with two very
    precise matches.  Negative evidence is intentionally amplified: a mature
    explicit dislike should outweigh a couple of broad positive genres.
    """

    dimensions = profile.get("dimensions") or {}
    confidence = max(0.0, min(1.0, float(profile.get("confidence") or 0.0)))
    negative_multiplier = float(
        (profile.get("ranking") or {}).get(
            "negative_multiplier", RANKING_POLICY["negative_multiplier"],
        )
    )
    positive_total = 0.0
    negative_total = 0.0
    known_values = 0
    total_values = 0
    reasons: list[dict[str, Any]] = []

    for dimension, raw_values in candidate_dimensions.items():
        factor = MATCH_FACTORS.get(dimension)
        if factor is None:
            continue
        values = canonical_values(dimension, raw_values)
        if not values:
            continue
        total_values += len(values)
        profile_values = _profile_lookup(dimensions.get(dimension) or {})
        matched: list[tuple[str, float]] = []
        for value in values:
            hit = profile_values.get(value.casefold())
            if hit is not None and abs(hit[1]) >= 0.01:
                matched.append((hit[0], hit[1]))
                known_values += 1
        if not matched:
            continue
        divisor = math.sqrt(max(1, len(values)))
        positive = sum(max(0.0, score) for _name, score in matched) / divisor
        negative = sum(min(0.0, score) for _name, score in matched) / divisor
        weighted_positive = factor * positive
        weighted_negative = factor * negative * negative_multiplier
        positive_total += weighted_positive
        negative_total += weighted_negative
        for name, raw_score in matched:
            contribution = factor * raw_score / divisor
            if contribution < 0:
                contribution *= negative_multiplier
            reasons.append({
                "dimension": dimension,
                "value": name,
                "profile_score": round(raw_score, 3),
                "contribution": round(contribution, 3),
            })

    # A mature profile should not treat a candidate with mostly unknown genres
    # as equally personal as one whose whole genre shape is understood.  This
    # is deliberately a small penalty and only affects the personal lane; it
    # does not become a hard global exclusion.
    genre_values = canonical_values("genres", candidate_dimensions.get("genres") or [])
    genre_lookup = _profile_lookup(dimensions.get("genres") or {})
    unknown_genres = [value for value in genre_values if value.casefold() not in genre_lookup]
    unknown_penalty = 0.0
    ranking = profile.get("ranking") or {}
    confidence_floor = float(
        ranking.get(
            "unknown_genre_confidence_floor",
            RANKING_POLICY["unknown_genre_confidence_floor"],
        )
    )
    if confidence >= confidence_floor and len(genre_values) >= 2 and unknown_genres:
        penalty_per_genre = float(
            ranking.get("unknown_genre_penalty", RANKING_POLICY["unknown_genre_penalty"])
        )
        unknown_penalty = min(4.5, len(unknown_genres) * penalty_per_genre * confidence)

    score = positive_total + negative_total - unknown_penalty
    coverage = known_values / total_values if total_values else 0.0
    reasons.sort(key=lambda item: (-abs(float(item["contribution"])), str(item["value"]).casefold()))
    return {
        "score": round(score, 4),
        "positive": round(positive_total, 4),
        "negative": round(negative_total, 4),
        "unknown_genre_penalty": round(unknown_penalty, 4),
        "coverage": round(coverage, 4),
        "known_values": known_values,
        "total_values": total_values,
        "reasons": reasons[:8],
    }
