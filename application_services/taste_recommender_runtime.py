"""Bind Royal Taste Profile v2 into the existing Jellyfin worker seam."""

from __future__ import annotations

import integrations.jellyfin_recommender as legacy
from application_services.runtime import backend_value, publish_service
from features.taste_recommender import TasteJellyfinAPI, run_unified_recommender_once


def _sync_household_jellyfin_profiles(config) -> int:
    """Refresh Jellyfin playback evidence independently for each Royal user."""
    state = backend_value("state")
    user_store = backend_value("USER_STORE")
    users = user_store.list_jellyfin_profiles()
    client = TasteJellyfinAPI(
        config.jellyfin_url,
        config.api_key,
        config.request_timeout,
        config.page_size,
    )
    synced = 0
    for user in users:
        if not user.get("enabled"):
            continue
        royal_user_id = str(user.get("id") or "").strip()
        jellyfin_user_id = str(user.get("jellyfin_user_id") or "").strip()
        if not jellyfin_user_id and royal_user_id == "admin-legacy":
            jellyfin_user_id = str(config.user_id or "").strip()
        if not royal_user_id or not jellyfin_user_id:
            continue
        try:
            items = client.list_media_items(jellyfin_user_id)
            watched, _unseen = legacy.split_watched(items)
            state.taste_profiles.for_user(royal_user_id).replace_jellyfin_items(watched)
            synced += 1
        except Exception as exc:
            backend_value("logger").warning(
                "Jellyfin-Geschmackssync für Royal-Profil %s fehlgeschlagen: %s",
                royal_user_id,
                exc,
            )
    return synced


def _run_recommender_once() -> bool:
    try:
        config = backend_value("_build_recommender_config")()
    except backend_value("JellyfinRecommenderConfigurationError") as exc:
        backend_value("logger").info("Jellyfin-Empfehlungen übersprungen: %s", exc)
        return False

    primary_success = True
    recommendations = []
    try:
        recommendations = run_unified_recommender_once(
            config,
            backend_value("state").taste_profile,
        )
    except backend_value("JellyfinRecommenderError") as exc:
        primary_success = False
        backend_value("logger").warning("Jellyfin-Empfehlungen fehlgeschlagen: %s", exc)
    except Exception:
        primary_success = False
        backend_value("logger").exception("Unerwarteter Fehler bei den Jellyfin-Empfehlungen")

    synced_profiles = _sync_household_jellyfin_profiles(config)
    backend_value("logger").info(
        "Jellyfin-Empfehlungen aktualisiert: %d Eintrag/Einträge; %d Royal-Profil(e) synchronisiert",
        len(recommendations),
        synced_profiles,
    )
    return primary_success or synced_profiles > 0


publish_service(globals(), ("_run_recommender_once", "_sync_household_jellyfin_profiles"))
