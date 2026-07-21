"""Auswahlregeln fuer automatisch abonnierte Serienepisoden."""

WATCH_MODE_ALL = "all"
WATCH_MODE_LATEST_SEASON = "latest_season"
WATCH_MODE_NEXT_SEASON = "next_season"
WATCH_MODE_DEFAULT = WATCH_MODE_LATEST_SEASON

CLEANUP_MODE_KEEP = "keep"
CLEANUP_MODE_WATCHED_SEASONS = "watched_seasons"
CLEANUP_MODE_WATCHED_EPISODES = "watched_episodes"
CLEANUP_MODE_DEFAULT = CLEANUP_MODE_KEEP

WATCH_MODE_LABELS = {
    WATCH_MODE_ALL: "Alles Fehlende",
    WATCH_MODE_LATEST_SEASON: "Neueste Staffel",
    WATCH_MODE_NEXT_SEASON: "Nächste Staffel nach Gesehen-Status",
}

CLEANUP_MODE_LABELS = {
    CLEANUP_MODE_KEEP: "Gesehene Folgen behalten",
    CLEANUP_MODE_WATCHED_SEASONS: "Gesehene Staffeln löschen",
    CLEANUP_MODE_WATCHED_EPISODES: "Gesehene Episoden löschen",
}


def normalize_watch_mode(value: str | None) -> str:
    """Gibt immer einen bekannten, rueckwaertskompatiblen Modus zurueck."""
    return value if value in WATCH_MODE_LABELS else WATCH_MODE_DEFAULT


def normalize_cleanup_mode(value: str | None) -> str:
    """Gibt immer eine bekannte, standardmäßig nicht löschende Regel zurück."""
    return value if value in CLEANUP_MODE_LABELS else CLEANUP_MODE_DEFAULT


def normalize_episode_history(values) -> set[tuple[int, int]]:
    """Liest persistierte ``Staffel:Episode``-Paare fehlertolerant ein."""
    result: set[tuple[int, int]] = set()
    for value in values or []:
        try:
            if isinstance(value, (tuple, list)) and len(value) == 2:
                season, episode = value
            else:
                season, episode = str(value).split(":", 1)
            pair = (int(season), int(episode))
        except (TypeError, ValueError):
            continue
        if pair[0] >= 0 and pair[1] > 0:
            result.add(pair)
    return result


def serialize_episode_history(values) -> list[str]:
    """Schreibt Episodenpaare stabil und JSON-kompatibel."""
    return [f"{season}:{episode}" for season, episode in sorted(set(values or []))]


def select_cleanup_items(
    items, mode: str, season_episode_counts=None, cleanup_history=None,
) -> list[dict]:
    """Wählt gesehene Jellyfin-Episoden für die konfigurierte Löschregel.

    Eine Staffel wird nur dann vollständig gelöscht, wenn ihr verifizierter
    Episodenumfang exakt bekannt ist und jede erwartete Folge in Jellyfin als
    gesehen markiert oder bereits durch diese Regel gelöscht wurde. So gilt eine
    nur teilweise vorhandene Staffel nie irrtümlich als vollständig und ein
    fehlgeschlagener Teillauf kann die übrigen Folgen später erneut versuchen.
    """
    mode = normalize_cleanup_mode(mode)
    candidates = []
    for item in items or []:
        try:
            season = int(item.get("season"))
            episode = int(item.get("episode"))
        except (TypeError, ValueError):
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id or season < 0 or episode <= 0:
            continue
        candidates.append({**item, "id": item_id, "season": season, "episode": episode})

    if mode == CLEANUP_MODE_KEEP:
        return []
    if mode == CLEANUP_MODE_WATCHED_EPISODES:
        return [item for item in candidates if item.get("played")]

    raw_counts = season_episode_counts if isinstance(season_episode_counts, dict) else {}
    expected_counts = {
        int(season): int(count)
        for season, count in raw_counts.items()
        if str(season).lstrip("-").isdigit()
        and str(count).isdigit()
        and int(season) > 0
        and int(count) > 0
    }
    cleaned_pairs = normalize_episode_history(cleanup_history)
    watched_pairs = cleaned_pairs | {
        (item["season"], item["episode"])
        for item in candidates if item.get("played")
    }
    known_pairs = cleaned_pairs | {
        (item["season"], item["episode"])
        for item in candidates
    }
    completed_seasons = {
        season
        for season, count in expected_counts.items()
        if (
            (expected := {(season, episode) for episode in range(1, count + 1)})
            == {pair for pair in known_pairs if pair[0] == season}
            and expected.issubset(watched_pairs)
        )
    }
    return [
        item for item in candidates
        if item.get("played") and item["season"] in completed_seasons
    ]


def select_missing_episode_slugs(
    episodes,
    mode: str,
    downloaded_slugs=None,
    jellyfin_existing=None,
    jellyfin_watched=None,
    season_episode_counts=None,
    unreleased_slugs=None,
) -> set[str]:
    """Waehlt fehlende Episoden entsprechend der Abo-Regel aus.

    ``jellyfin_existing`` enthaelt vorhandene und ``jellyfin_watched`` die beim
    konfigurierten Benutzer gesehenen ``(staffel, episode)``-Paare. Im Modus
    ``next_season`` wird erst nach einer vollständig gesehenen Staffel die
    folgende freigegeben. ``None`` bedeutet, dass kein Benutzerstatus vorliegt.
    ``unreleased_slugs`` enthaelt Episoden, die laut Metadaten noch nicht
    erschienen sind – die werden nie als fehlend gemeldet, sonst landen
    unveroeffentlichte Folgen in der Auto-Download-Warteschlange und schlagen
    dort dauerhaft fehl.
    """
    episodes = list(episodes or [])
    downloaded = set(downloaded_slugs or [])
    jellyfin = set(jellyfin_existing or [])
    unreleased = set(unreleased_slugs or [])
    mode = normalize_watch_mode(mode)

    missing = [
        episode for episode in episodes
        if episode.slug not in downloaded
        and (episode.season, episode.episode) not in jellyfin
        and episode.slug not in unreleased
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
