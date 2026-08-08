"""Bind Royal Taste Profile v2 into the existing Jellyfin worker seam."""

from __future__ import annotations

from application_services.runtime import backend_value, publish_service
from taste_recommender import run_unified_recommender_once


def _run_recommender_once() -> bool:
    try:
        config = backend_value("_build_recommender_config")()
    except backend_value("JellyfinRecommenderConfigurationError") as exc:
        backend_value("logger").info("Jellyfin-Empfehlungen übersprungen: %s", exc)
        return False

    try:
        recommendations = run_unified_recommender_once(
            config,
            backend_value("state").taste_profile,
        )
    except backend_value("JellyfinRecommenderError") as exc:
        backend_value("logger").warning("Jellyfin-Empfehlungen fehlgeschlagen: %s", exc)
        return False
    except Exception:
        backend_value("logger").exception("Unerwarteter Fehler bei den Jellyfin-Empfehlungen")
        return False

    backend_value("logger").info(
        "Jellyfin-Empfehlungen aktualisiert: %d Eintrag/Einträge",
        len(recommendations),
    )
    return True


publish_service(globals(), ("_run_recommender_once",))
