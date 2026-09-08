from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


class InboxMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


def test_subscription_inbox_behavior():
    """Run the actual frontend functions, including the screenshot regression."""
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the subscription inbox behavior tests")
    result = subprocess.run(
        [node, "--test", str(ROOT / "tests/frontend/subscription_center.test.cjs")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_subscription_inbox_exposes_all_filters_as_accessible_buttons():
    markup = InboxMarkup()
    markup.feed((ROOT / "web/index.html").read_text(encoding="utf-8"))
    filters = {
        attrs["data-notif-filter"]: (tag, attrs)
        for tag, attrs in markup.elements
        if "data-notif-filter" in attrs
    }
    assert set(filters) == {"all", "new", "queued", "downloaded", "issue"}
    for filter_name, (tag, attrs) in filters.items():
        assert tag == "button"
        assert attrs["type"] == "button"
        assert attrs["aria-pressed"] == str(filter_name == "all").lower()

    ids = {attrs["id"] for _, attrs in markup.elements if "id" in attrs}
    assert {
        "notif-bell", "notif-badge", "notif-trigger-label", "notif-summary",
        "notif-subscription-count", "notif-list", "notif-refresh", "notif-library",
    } <= ids
    assert "notif-stats" not in ids


def test_subscription_inbox_remains_responsive_and_supports_artwork_fallback():
    css = (ROOT / "web/styles/subscription-center.css").read_text(encoding="utf-8")
    assert "@media" in css
    assert "env(safe-area-inset-bottom)" in css
    assert ".notif-item-art.is-fallback" in css
    assert ".notif-item-check" in css
