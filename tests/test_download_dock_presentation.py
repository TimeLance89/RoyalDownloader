from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "styles" / "catalog-polish.css").read_text(encoding="utf-8")


def test_download_dock_keeps_existing_queue_contract_ids():
    for element_id in (
        "queue-dock",
        "queue-drawer",
        "queue-list",
        "queue-history-list",
        "queue-count",
        "download-stage",
        "dl-state-title",
        "dl-status",
        "dl-percent",
        "progress-fill",
        "log-console",
    ):
        assert f'id="{element_id}"' in HTML


def test_idle_download_dock_hides_meaningless_zero_progress():
    assert '#queue-dock .download-stage[data-state="idle"] .download-percent' in CSS
    assert '#queue-dock .download-stage[data-state="idle"] .progress-bar' in CSS
    assert "display: none" in CSS


def test_desktop_dock_is_a_single_slide_up_surface():
    assert "/* ── Royal Download Dock" in CSS
    assert "#queue-dock.queue-expanded .queue-panel" in CSS
    assert "max-height: min(66vh, 620px)" in CSS
    assert "#queue-dock .queue-drawer" in CSS
    assert "height: min(53vh, 520px)" in CSS
    assert "border-radius: 18px 18px 0 0" in CSS


def test_queue_rows_expose_status_progress_and_actions_as_cards():
    for selector in (
        "#queue-dock .queue-item",
        "#queue-dock .queue-item-status",
        "#queue-dock .queue-item-progress",
        "#queue-dock .queue-item-actions",
        "#queue-dock .queue-action-btn",
    ):
        assert selector in CSS
    assert "border-radius: 13px" in CSS
    assert "linear-gradient(90deg, #b90812, #e50914, #ff4a55)" in CSS


def test_activity_column_is_reduced_to_recent_readable_events():
    assert "Live-Ereignisse des aktuellen Durchlaufs" in CSS
    assert "#queue-dock .queue-activity .log-line:nth-last-child(n + 9)" in CSS
    assert "display: none" in CSS
    assert "#queue-dock .queue-activity .log-line.err::before" in CSS


def test_mobile_queue_remains_a_safe_area_aware_sheet():
    assert "body.queue-open #queue-dock .queue-panel" in CSS
    assert "border-radius: 22px 22px 0 0" in CSS
    assert "env(safe-area-inset-bottom)" in CSS
