"""Auswahlregeln fuer automatisch abonnierte Serienepisoden."""

WATCH_MODE_ALL = "all"
WATCH_MODE_LATEST_SEASON = "latest_season"
WATCH_MODE_NEXT_SEASON = "next_season"
WATCH_MODE_DEFAULT = WATCH_MODE_LATEST_SEASON

WATCH_MODE_LABELS = {
    WATCH_MODE_ALL: "Alles Fehlende",
    WATCH_MODE_LATEST_SEASON: "Neueste Staffel",
    WATCH_MODE_NEXT_SEASON: "Nächste Staffel nach Gesehen-Status",
}


def normalize_watch_mode(value: str | None) -> str:
    """Gibt immer einen bekannten, rueckwaertskompatiblen Modus zurueck."""
    return value if value in WATCH_MODE_LABELS else WATCH_MODE_DEFAULT


def select_missing_episode_slugs(
    episodes,
    mode: str,
    downloaded_slugs=None,
    jellyfin_existing=None,
    jellyfin_watched=None,
    season_episode_counts=None,
) -> set[str]:
    """Waehlt fehlende Episoden entsprechend der Abo-Regel aus.

    ``jellyfin_existing`` enthaelt vorhandene und ``jellyfin_watched`` die beim
    konfigurierten Benutzer gesehenen ``(staffel, episode)``-Paare. Im Modus
    ``next_season`` wird erst nach einer vollständig gesehenen Staffel die
    folgende freigegeben. ``None`` bedeutet, dass kein Benutzerstatus vorliegt.
    """
    episodes = list(episodes or [])
    downloaded = set(downloaded_slugs or [])
    jellyfin = set(jellyfin_existing or [])
    mode = normalize_watch_mode(mode)

    missing = [
        episode for episode in episodes
        if episode.slug not in downloaded
        and (episode.season, episode.episode) not in jellyfin
    ]
    if not missing:
        return set()

    source_seasons = sorted({episode.season for episode in episodes})
    if mode == WATCH_MODE_ALL:
        selected = missing
    elif mode == WATCH_MODE_LATEST_SEASON:
        target_season = source_seasons[-1]
        selected = [episode for episode in missing if episode.season == target_season]
    else:
        if jellyfin_watched is None:
            return set()
        watched = set(jellyfin_watched)
        expected_counts = {
            int(season): int(count)
            for season, count in (season_episode_counts or {}).items()
            if str(season).lstrip("-").isdigit() and str(count).isdigit()
        }
        regular_seasons = [season for season in source_seasons if season > 0]
        candidate_seasons = regular_seasons or source_seasons
        # Ohne verifizierte Episodenzahl könnte eine erst teilweise veröffentlichte
        # Staffel fälschlich als vollständig gesehen gelten.
        if any(expected_counts.get(season, 0) <= 0 for season in candidate_seasons):
            return set()
        watched_through = None
        for season in candidate_seasons:
            season_pairs = {
                (episode.season, episode.episode)
                for episode in episodes if episode.season == season
            }
            expected_pairs = {
                (season, episode) for episode in range(1, expected_counts[season] + 1)
            }
            source_complete = expected_pairs.issubset(season_pairs)
            if source_complete and expected_pairs and expected_pairs.issubset(watched):
                watched_through = season
            else:
                break
        if watched_through is not None:
            later_seasons = [season for season in candidate_seasons if season > watched_through]
            if not later_seasons:
                return set()
            target_season = later_seasons[0]
        else:
            target_season = candidate_seasons[0]
        selected = [episode for episode in missing if episode.season == target_season]

    return {episode.slug for episode in selected}
