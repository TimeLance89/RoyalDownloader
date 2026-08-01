from types import SimpleNamespace

import pytest

from providers.models import FilmpalastMovie, HosterInfo
from providers.serienstream import SerienstreamScraper
from session_manager import GATE_BLOCKED, ProviderBlockedError, SessionManager


class RedirectSession:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = 0

    def get_redirect_location(self, *_args, **_kwargs):
        self.calls += 1
        return next(self.values)


def test_gate_blocked_sets_scraper_gate():
    session = RedirectSession([GATE_BLOCKED])
    scraper = SerienstreamScraper(session=session)
    assert scraper.resolve_play_url("https://serienstream.to/r?t=one") is None
    assert scraper.gated
    assert scraper.last_block_reason == "captcha_gate"
    assert session.calls == 1


def test_http_429_redirect_does_not_start_browser(monkeypatch):
    manager = SessionManager.__new__(SessionManager)
    manager.TARGET_DOMAIN = "serienstream.to"
    manager._human_delay = lambda: None
    manager._browser_headers = lambda *_args: {}
    manager._curl = SimpleNamespace(get=lambda *_args, **_kwargs: SimpleNamespace(
        headers={}, text="rate limited", status_code=429,
    ))
    monkeypatch.setattr(
        manager, "_nodriver_get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("browser started")),
    )
    assert manager.get_redirect_location("https://serienstream.to/r?t=x") == GATE_BLOCKED


def test_blocked_episode_page_does_not_start_browser(monkeypatch):
    manager = SessionManager.__new__(SessionManager)
    manager.TARGET_DOMAIN = "serienstream.to"
    manager._human_delay = lambda fast=False: None
    manager._curl_get = lambda _url: ("<html>cloudflare captcha</html>", 403)
    manager._log = lambda *_args: None
    monkeypatch.setattr(
        manager, "_nodriver_get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("browser started")),
    )
    with pytest.raises(ProviderBlockedError):
        manager.get("https://serienstream.to/serie/test/staffel-1/episode-1")


def test_extract_stops_after_first_blocked_redirect(monkeypatch, tmp_path):
    import server
    from provider_health import ProviderHealth

    server.state.provider_health = ProviderHealth(
        tmp_path / "health.json", initial_cooldown=10, maximum_cooldown=40,
    )
    scraper = SimpleNamespace(
        gated=False,
        last_block_reason="",
        is_redirect_url=SerienstreamScraper.is_redirect_url,
        resolve_play_url=lambda *_args, **_kwargs: None,
    )

    def blocked(*_args, **_kwargs):
        scraper.gated = True
        scraper.last_block_reason = "captcha_gate"
        return None

    scraper.resolve_play_url = blocked
    monkeypatch.setattr(server, "get_sto_scraper", lambda: scraper)
    monkeypatch.setattr(server, "broadcast", lambda *_args, **_kwargs: None)
    movie = FilmpalastMovie(
        title="Test S01E01",
        url="https://serienstream.to/serie/test/staffel-1/episode-1",
        provider="serienstream",
        hosters=[
            HosterInfo("VOE", "https://serienstream.to/r?t=one"),
            HosterInfo("Dood", "https://serienstream.to/r?t=two"),
        ],
    )
    calls = {"count": 0}
    original = scraper.resolve_play_url
    scraper.resolve_play_url = lambda *args, **kwargs: (
        calls.__setitem__("count", calls["count"] + 1) or original(*args, **kwargs)
    )
    result = server._extract_from_movie(movie, set())
    assert result.gated
    assert calls["count"] == 1
    assert server.state.provider_health.status("serienstream")["state"] == "cooldown"
