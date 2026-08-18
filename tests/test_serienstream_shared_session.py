from __future__ import annotations

import serienstream_shared_session as shared


class FakeCdp:
    def __init__(self):
        self.seed = []
        self.navigated = []
        self.clicked = []
        self._markers = {}

    def set_cookies(self, cookies):
        self.seed = list(cookies)

    def navigate(self, url):
        self.navigated.append(url)

    def click_hoster(self, url):
        self.clicked.append(url)
        return True

    def cookies(self):
        return [
            {
                "name": "session",
                "value": "abc",
                "domain": ".serienstream.to",
                "path": "/",
                "secure": True,
            },
            {
                "name": "foreign",
                "value": "ignored",
                "domain": "example.org",
                "path": "/",
                "secure": True,
            },
        ]

    def current_url(self):
        return "https://serienstream.to/r?t=token"

    def markers(self):
        return dict(self._markers)

    def html(self):
        return "<html>episode</html>"


class FakeRuntime:
    instances = []

    def __init__(self):
        self.cdp = FakeCdp()
        self.port = 12345
        self.closed = False
        FakeRuntime.instances.append(self)

    def start(self):
        return self.cdp

    def close(self):
        self.closed = True


def test_url_boundaries_only_allow_serienstream_provider_context():
    episode = "https://serienstream.to/serie/test/staffel-1/episode-2"
    assert shared.valid_episode_url(episode)
    assert shared.valid_provider_page_url(episode)
    assert shared.valid_provider_page_url("https://serienstream.to/serie/test")
    assert shared.valid_provider_page_url("https://serienstream.to/suche?term=test")
    assert shared.valid_redirect_url("https://serienstream.to/r?t=token")

    assert not shared.valid_episode_url("http://serienstream.to/serie/test/staffel-1/episode-2")
    assert not shared.valid_episode_url("https://evil.example/serie/test/staffel-1/episode-2")
    assert not shared.valid_episode_url("https://serienstream.to.evil.example/serie/test/staffel-1/episode-2")
    assert not shared.valid_episode_url("https://user:pass@serienstream.to/serie/test/staffel-1/episode-2")
    assert not shared.valid_redirect_url("https://serienstream.to/r?t=one&t=two")
    assert not shared.valid_redirect_url("https://serienstream.to/r?next=https://evil.example")
    assert not shared.valid_redirect_url("https://evil.example/r?t=token")


def test_redirect_recovery_loads_episode_and_clicks_exact_hoster(monkeypatch):
    FakeRuntime.instances.clear()
    monkeypatch.setattr(shared, "_BrowserRuntime", FakeRuntime)
    monkeypatch.setattr(
        shared,
        "_wait_for_page",
        lambda *_args, **_kwargs: ("<html>episode</html>", {}),
    )
    monkeypatch.setattr(shared, "_external_target", lambda _port: "https://voe.sx/e/final")

    seed = [{
        "name": "session",
        "value": "seed",
        "domain": "serienstream.to",
        "path": "/",
        "secure": True,
    }]
    redirect = "https://serienstream.to/r?t=token"
    episode = "https://serienstream.to/serie/test/staffel-1/episode-2"
    result = shared.resolve_provider_redirect(redirect, episode, seed)

    runtime = FakeRuntime.instances[-1]
    assert runtime.cdp.seed == seed
    assert runtime.cdp.navigated == [episode]
    assert runtime.cdp.clicked == [redirect]
    assert result.target == "https://voe.sx/e/final"
    assert [cookie["name"] for cookie in result.cookies] == ["session"]
    assert not result.gated
    assert runtime.closed


def test_redirect_recovery_never_clicks_when_interactive_challenge_is_present(monkeypatch):
    FakeRuntime.instances.clear()
    monkeypatch.setattr(shared, "_BrowserRuntime", FakeRuntime)
    monkeypatch.setattr(
        shared,
        "_wait_for_page",
        lambda *_args, **_kwargs: (
            "<html>turnstile</html>",
            {"turnstile": True, "challenge": True},
        ),
    )

    result = shared.resolve_provider_redirect(
        "https://serienstream.to/r?t=token",
        "https://serienstream.to/serie/test/staffel-1/episode-2",
        [],
    )

    runtime = FakeRuntime.instances[-1]
    assert runtime.cdp.clicked == []
    assert result.gated
    assert result.target == ""
    assert runtime.closed


def test_provider_html_recovers_normal_page_and_returns_shared_cookies(monkeypatch):
    FakeRuntime.instances.clear()
    monkeypatch.setattr(shared, "_BrowserRuntime", FakeRuntime)
    monkeypatch.setattr(
        shared,
        "_wait_for_page",
        lambda *_args, **_kwargs: ("<html>normal episode</html>", {}),
    )

    result = shared.fetch_provider_html(
        "https://serienstream.to/serie/test/staffel-1/episode-2",
        [],
    )

    assert result.html == "<html>normal episode</html>"
    assert not result.gated
    assert [cookie["name"] for cookie in result.cookies] == ["session"]
    assert FakeRuntime.instances[-1].closed


def test_provider_html_does_not_return_challenge_document(monkeypatch):
    FakeRuntime.instances.clear()
    monkeypatch.setattr(shared, "_BrowserRuntime", FakeRuntime)
    monkeypatch.setattr(
        shared,
        "_wait_for_page",
        lambda *_args, **_kwargs: (
            "<html>turnstile</html>",
            {"turnstile": True, "gate_root": True},
        ),
    )

    result = shared.fetch_provider_html(
        "https://serienstream.to/serie/test/staffel-1/episode-2",
        [],
    )

    assert result.html == ""
    assert result.gated
    assert FakeRuntime.instances[-1].closed
