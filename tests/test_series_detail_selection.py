from pathlib import Path


def test_series_detail_keeps_episodes_selectable_while_status_checks_run():
    source = (Path(__file__).parents[1] / "web" / "screens" / "series.js").read_text(
        encoding="utf-8"
    )
    selectable = source.split("function isEpisodeSelectable(episode)", 1)[1].split(
        "function syncSeriesQueueFlags", 1
    )[0]

    assert "availability_pending" not in selectable
    assert "jellyfin_pending" not in selectable
    assert "jellyfin_available" not in selectable
    assert "!episode.downloaded" in selectable
    assert "!episode.in_jellyfin" in selectable
    assert "!episode.unreleased" in selectable
