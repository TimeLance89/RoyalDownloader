from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_profile_hub_has_the_royal_wide_dashboard_structure():
    markup = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "web" / "styles" / "user-profile.css").read_text(encoding="utf-8")
    script = (ROOT / "web" / "screens" / "user-profile.js").read_text(encoding="utf-8")

    assert 'class="profile-hero-cinema"' in markup
    for identifier in (
        "profile-top-genre-count",
        "profile-activity-ratings",
        "profile-recent-downloads",
        "profile-security",
    ):
        assert f'id="{identifier}"' in markup
    assert "grid-template-columns:1.1fr 1fr .9fr" in styles
    assert "@media(max-width:1120px)" in styles
    assert "@media(max-width:760px)" in styles
    assert "relative Präferenzstärke" in script
    assert "createProfileEmptyState" in script
    assert "requested_at" in script


def test_profile_summary_keeps_recent_requests_personal_and_includes_real_request_time():
    server = (ROOT / "server.py").read_text(encoding="utf-8")

    assert "state.personal_requests.recent_for_user(user_id, limit=8)" in server
    assert "state.personal_requests.count_for_user(user_id)" in server
