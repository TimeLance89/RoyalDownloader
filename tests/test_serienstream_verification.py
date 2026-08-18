from __future__ import annotations

from types import SimpleNamespace

import pytest

import serienstream_verification as verification
from api_serienstream_verification_router import router


@pytest.mark.parametrize(
    "url",
    [
        "https://serienstream.to/serie/breaking-bad/staffel-1/episode-1",
        "https://www.serienstream.to/serie/safe/staffel-2/episode-7/",
    ],
)
def test_episode_url_allowlist_accepts_only_direct_serienstream_episodes(url):
    assert verification.valid_episode_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://serienstream.to/serie/breaking-bad/staffel-1/episode-1",
        "https://evil.example/serie/breaking-bad/staffel-1/episode-1",
        "https://serienstream.to.evil.example/serie/breaking-bad/staffel-1/episode-1",
        "https://serienstream.to/serie/breaking-bad",
        "https://serienstream.to/serie/breaking-bad/staffel-1/episode-1?next=https://evil.example",
        "https://user:pass@serienstream.to/serie/breaking-bad/staffel-1/episode-1",
    ],
)
def test_episode_url_allowlist_rejects_non_episode_and_cross_origin_urls(url):
    assert verification.valid_episode_url(url) is False


def test_extract_redirect_url_only_accepts_serienstream_r_tokens():
    html = '<button data-play-url="/r?t=abc123" data-provider-name="VOE"></button>'
    assert verification.SerienStreamVerificationManager._extract_redirect_url(
        html,
        verification.DEFAULT_EPISODE_URL,
    ) == "https://serienstream.to/r?t=abc123"

    with pytest.raises(RuntimeError):
        verification.SerienStreamVerificationManager._extract_redirect_url(
            '<button data-play-url="https://evil.example/embed"></button>',
            verification.DEFAULT_EPISODE_URL,
        )


class _FakeCookieJar:
    def __init__(self):
        self.values = []

    def set(self, name, value, **kwargs):
        self.values.append((name, value, kwargs))


class _FakeSession:
    def __init__(self):
        self._curl = SimpleNamespace(cookies=_FakeCookieJar())
        self._cookies = {}
        self.saved = 0

    def _save_cookies(self):
        self.saved += 1


def test_browser_cookies_are_persisted_into_http_session():
    session = _FakeSession()
    installed = verification.SerienStreamVerificationManager._install_into_session(
        session,
        [
            {
                "name": "cf_clearance",
                "value": "clear",
                "domain": ".serienstream.to",
                "path": "/",
                "secure": True,
            },
            {
                "name": "session",
                "value": "abc",
                "domain": "serienstream.to",
                "path": "/",
                "secure": True,
            },
        ],
    )

    assert installed == ["cf_clearance", "session"]
    assert session._cookies == {"cf_clearance": "clear", "session": "abc"}
    assert session.saved == 1
    assert session._curl.cookies.values[0][2]["domain"] == ".serienstream.to"


class _FakeCdp:
    def __init__(self):
        self.clicks = []
        self.scrolls = []

    def click(self, x, y):
        self.clicks.append((x, y))

    def scroll(self, value):
        self.scrolls.append(value)

    def cookies(self):
        return []

    def current_url(self):
        return verification.DEFAULT_EPISODE_URL

    def page_markers(self):
        return {"turnstile": True}


class _FakeProcess:
    def poll(self):
        return None

    def terminate(self):
        return None

    def wait(self, timeout=None):
        return 0


def _active_manager():
    manager = verification.SerienStreamVerificationManager(clock=lambda: 100.0)
    manager._state = verification.VerificationState(
        phase="waiting_for_user",
        episode_url=verification.DEFAULT_EPISODE_URL,
        redirect_url="https://serienstream.to/r?t=abc",
        started_at=100.0,
    )
    manager._cdp = _FakeCdp()
    manager._chrome = _FakeProcess()
    return manager


def test_user_click_coordinates_are_normalized_to_fixed_browser_viewport(monkeypatch):
    manager = _active_manager()
    monkeypatch.setattr(verification.time, "sleep", lambda *_args: None)

    manager.click(0.25, 0.5)

    assert manager._cdp.clicks == [(320.0, 450.0)]
    with pytest.raises(ValueError):
        manager.click(-0.01, 0.5)
    with pytest.raises(ValueError):
        manager.click(0.5, 1.01)


def test_scroll_is_clamped_to_bounded_user_gesture(monkeypatch):
    manager = _active_manager()
    monkeypatch.setattr(verification.time, "sleep", lambda *_args: None)

    manager.scroll(9000)
    manager.scroll(-9000)

    assert manager._cdp.scrolls == [1600.0, -1600.0]


def test_verification_api_is_registered_only_as_provider_admin_surface():
    paths = {route.path for route in router.routes}
    assert "/api/providers/serienstream/verification" in paths
    assert "/api/providers/serienstream/verification/start" in paths
    assert "/api/providers/serienstream/verification/frame" in paths
    assert "/api/providers/serienstream/verification/click" in paths
    assert "/api/providers/serienstream/verification/finish" in paths
    assert "/api/providers/serienstream/verification/ui" in paths
