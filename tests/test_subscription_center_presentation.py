from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTIFICATIONS = (ROOT / "web" / "screens" / "notifications.js").read_text(encoding="utf-8")
STYLES = (ROOT / "web" / "styles" / "subscription-center.css").read_text(encoding="utf-8")


def test_subscription_center_keeps_existing_notification_contracts():
    for element_id in (
        "notif-bell",
        "notif-badge",
        "notif-trigger-label",
        "notif-summary",
        "notif-subscription-count",
        "notif-list",
        "notif-refresh",
    ):
        assert f'getElementById("{element_id}")' in NOTIFICATIONS

    assert "api.watchlistCheck(null)" in NOTIFICATIONS
    assert "openWatchlistEntry(entry.base_slug)" in NOTIFICATIONS


def test_subscription_center_loads_isolated_styles_without_manifest_changes():
    assert "ensureSubscriptionCenterStyles" in NOTIFICATIONS
    assert "/styles/subscription-center.css?v=royal-20260828-1" in NOTIFICATIONS
    assert "data-subscription-center-styles" in NOTIFICATIONS
    assert "Royal Subscription Center" in STYLES


def test_subscription_center_uses_artwork_with_monogram_fallback():
    assert 'art.className = "notif-item-art"' in NOTIFICATIONS
    assert "entry.backdrop_url" in NOTIFICATIONS
    assert "api.coverUrl(entry.backdrop_url)" in NOTIFICATIONS
    assert 'monogram.className = "notif-item-monogram"' in NOTIFICATIONS
    assert "subscriptionMonogram(entry.title)" in NOTIFICATIONS
    assert ".notif-item-art img" in STYLES
    assert ".notif-item-art.is-fallback img" in STYLES


def test_subscription_center_separates_new_items_from_real_issues():
    assert "function notificationHasIssue(entry)" in NOTIFICATIONS
    assert 'appendNotificationSection(list, "is-new", "Neue Folgen", newSorted)' in NOTIFICATIONS
    assert (
        'appendNotificationSection(list, "is-issue", "Probleme", issueSorted)'
        in NOTIFICATIONS
    )
    assert 'item.className = `notif-item is-${stateName}`' in NOTIFICATIONS
    assert ".notif-section.is-issue .notif-section-title" in STYLES
    assert ".notif-item.is-issue" in STYLES


def test_subscription_center_surfaces_completed_subscription_downloads():
    assert "downloadedEpisodeLabel" in NOTIFICATIONS
    assert 'appendNotificationSection(list, "is-downloaded", "Heruntergeladen", downloadedSorted)' in NOTIFICATIONS
    assert "api.watchlistDownloadsRead(entry.base_slug)" in NOTIFICATIONS
    assert 'downloadReceipt.className = "library-download-receipt"' in NOTIFICATIONS
    assert ".notif-item.is-downloaded" in STYLES


def test_subscription_center_exposes_separate_episode_and_issue_badges():
    assert 'issueBadge.id = "notif-issue-badge"' in NOTIFICATIONS
    assert 'badge.classList.toggle("hidden", noticeTotal === 0)' in NOTIFICATIONS
    assert 'issueBadge.classList.toggle("hidden", issueCount === 0)' in NOTIFICATIONS
    assert ".notif-issue-badge" in STYLES


def test_subscription_center_shows_summary_metrics_and_richer_empty_state():
    for element_id in (
        "notif-stats",
        "notif-new-count",
        "notif-issue-count",
        "notif-center-subscriptions",
    ):
        assert element_id in NOTIFICATIONS

    assert "Alles auf dem neuesten Stand" in NOTIFICATIONS
    assert "Royal überwacht deine abonnierten Serien weiter automatisch" in NOTIFICATIONS
    assert "Gerade eben geprüft" in NOTIFICATIONS
    assert ".notif-stats" in STYLES
    assert ".notif-empty-meta" in STYLES


def test_subscription_center_remains_responsive_on_mobile():
    assert "@media (max-width: 820px)" in STYLES
    assert "@media (max-width: 520px)" in STYLES
    assert "env(safe-area-inset-bottom)" in STYLES
    assert "width: auto;" in STYLES


def test_subscription_center_supports_filters_and_single_subscription_checks():
    for filter_name in ("all", "new", "issue"):
        assert f'data-notif-filter="{filter_name}"' in (
            ROOT / "web" / "index.html"
        ).read_text(encoding="utf-8")

    assert "state.wl.notifFilter" in NOTIFICATIONS
    assert "api.watchlistCheck([entry.base_slug])" in NOTIFICATIONS
    assert 'check.className = "notif-item-check"' in NOTIFICATIONS
    assert ".notif-item-check" in STYLES
