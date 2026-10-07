"""Pure completeness checks for series detail payloads."""


def series_payload_missing_seasons(payload: dict) -> set[int]:
    """Erkennt laut TMDB existierende, im Provider-Snapshot fehlende Staffeln."""
    expected: set[int] = set()
    for season, count in (payload.get("season_episode_counts") or {}).items():
        try:
            number, episode_count = int(season), int(count or 0)
        except (TypeError, ValueError):
            continue
        if number > 0 and episode_count > 0:
            expected.add(number)
    present = {
        int(item.get("season") or 0)
        for item in payload.get("seasons") or []
        if int(item.get("season") or 0) > 0
    }
    return expected - present
