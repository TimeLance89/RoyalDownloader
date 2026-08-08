"""Jellyfin recommendation runner backed by Royal's unified taste profile."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Mapping, Sequence

import jellyfin_recommender as legacy
from taste_profile import TasteProfileStore, score_metadata_against_profile


LOGGER = logging.getLogger("jellyfin_recommender")


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _profile_recommendation(
    item: dict[str, Any],
    profile: Mapping[str, Any],
) -> legacy.Recommendation:
    result = score_metadata_against_profile(profile, item, str(item.get("Type") or ""))
    community_rating = _finite_float(item.get("CommunityRating")) or 0.0
    rating_bonus = 0.05 * min(1.0, max(0.0, (community_rating - 5.0) / 5.0))
    matches: dict[str, list[str]] = defaultdict(list)
    for reason in result.get("reasons") or []:
        if float(reason.get("contribution") or 0) <= 0:
            continue
        dimension = str(reason.get("dimension") or "")
        value = str(reason.get("value") or "")
        if dimension and value and value not in matches[dimension]:
            matches[dimension].append(value)
    return legacy.Recommendation(
        item=item,
        score=float(result.get("score") or 0) + rating_bonus,
        content_score=float(result.get("score") or 0),
        rating_bonus=rating_bonus,
        matches={key: tuple(values) for key, values in matches.items()},
    )


def rank_with_taste_profile(
    unseen: Sequence[dict[str, Any]],
    profile: Mapping[str, Any],
    top_n: int,
) -> list[legacy.Recommendation]:
    scored = [_profile_recommendation(item, profile) for item in unseen]

    def sort_key(recommendation: legacy.Recommendation):
        item = recommendation.item
        rating = _finite_float(item.get("CommunityRating")) or 0.0
        year = _finite_float(item.get("ProductionYear")) or 0.0
        return (
            -recommendation.score,
            -recommendation.content_score,
            -rating,
            -year,
            legacy.normalize_text(item.get("Name")),
            str(item.get("Id") or ""),
        )

    return sorted(scored, key=sort_key)[:top_n]


def run_unified_recommender_once(
    config: legacy.Config,
    profile_store: TasteProfileStore,
    api: legacy.JellyfinAPI | None = None,
) -> list[legacy.Recommendation]:
    client = api or legacy.JellyfinAPI(
        config.jellyfin_url,
        config.api_key,
        config.request_timeout,
        config.page_size,
    )
    items = client.list_media_items(config.user_id)
    watched, unseen = legacy.split_watched(items)
    LOGGER.info(
        "Bibliothek: %d Filme/Serien, %d gesehen, %d ungesehen",
        len(watched) + len(unseen),
        len(watched),
        len(unseen),
    )

    # Replace instead of accumulate: repeated recommendation runs must not
    # inflate Jellyfin evidence.  The refreshed snapshot is part of the same
    # profile that downloads, explicit feedback and web interactions use.
    profile_store.replace_jellyfin_items(watched)
    profile = profile_store.public_profile()
    if not any((profile.get("dimensions") or {}).values()):
        raise legacy.RecommenderError(
            "Keine belastbaren Geschmackssignale; Collection bleibt unverändert"
        )

    recommendations = rank_with_taste_profile(unseen, profile, config.top_n)
    LOGGER.info(
        "Auswahl für %r: %d Item(s), Royal-Profil=%s (%.0f%%)",
        config.collection_name,
        len(recommendations),
        profile.get("confidence_label") or "low",
        float(profile.get("confidence") or 0) * 100,
    )
    for rank, recommendation in enumerate(recommendations, start=1):
        item = recommendation.item
        LOGGER.info(
            "%02d. %s (%s, %s) | Taste=%.4f Bonus=%.4f Gesamt=%.4f",
            rank,
            item.get("Name") or item.get("Id"),
            item.get("Type") or "?",
            item.get("ProductionYear") or "?",
            recommendation.content_score,
            recommendation.rating_bonus,
            recommendation.score,
        )

    collection_id, created = client.get_or_create_collection(
        config.user_id, config.collection_name,
    )
    LOGGER.info(
        "Collection %s: %s (%s)",
        "angelegt" if created else "gefunden",
        config.collection_name,
        collection_id,
    )
    sync = client.sync_collection(
        config.user_id,
        collection_id,
        [str(recommendation.item["Id"]) for recommendation in recommendations],
    )
    LOGGER.info(
        "Collection aktualisiert: +%d, -%d, unverändert=%d",
        sync.added,
        sync.removed,
        sync.unchanged,
    )
    if recommendations and client.ensure_collection_primary_image(
        collection_id,
        [recommendation.item for recommendation in recommendations],
    ):
        LOGGER.info("Collection-Cover aus der besten Empfehlung gesetzt")

    configure_moonfin = getattr(client, "configure_moonfin_dashboard", None)
    if callable(configure_moonfin):
        try:
            configured = configure_moonfin(
                config.user_id, collection_id, config.collection_name,
            )
        except legacy.RecommenderError as exc:
            LOGGER.warning("Moonfin-Dashboard konnte nicht aktualisiert werden: %s", exc)
        else:
            if configured:
                LOGGER.info("Moonfin-Dashboard und Media Bar aktualisiert")
            else:
                LOGGER.info("Moonfin-Plugin nicht installiert; Dashboard-Sync übersprungen")
    return recommendations
