from types import SimpleNamespace

import pytest

from providers.models import FilmpalastMovie, HosterInfo
from providers.serienstream import SerienstreamScraper
from serienstream_session_identity import SERIESSTREAM_USER_AGENT
from session_manager import GATE_BLOCKED, ProviderBlockedError, SessionManager


class RedirectSession:
    def __init__(self, values):
        self.values = iter(values)
        self.calls = 0

    def get_redirect_location(self, *_args, **_kwargs):
        self.calls += 1
        return next(self.values)


def _redirect_manager(response):
    manager = SessionManager.__new__(SessionManager)
    manager.TARGET_DOMAIN = "serienstream.to"
    manager._human_delay = lambda: None
    manager._browser_headers = lambda *_args: {}
    manager._log = lambda *_args: None
    manager._curl = SimpleNamespace(get=lambda *_args, **_kwargs: response)
    return manager


def test_gate_blocked_sets_scraper_gate():
    session = RedirectSession([GATE_BLOCKED])
    scraper = SerienstreamScraper(session=session)
    assert scraper.resolve_play_url("https://serienstream.to/r?t=one") is None
    assert scraper.gated
    assert scraper.last_block_reason == "captcha_gate"
    assert session.calls == 1


def test_http_429_redirect_uses_shared_browser_before_circuit_breaker(monkeypatch):
    manager = _redirect_manager(SimpleNamespace(
        url="https://serienstream.to/r?t=x",
        request=SimpleNamespace(url="https://serienstream.to/r?t=x"),
        headers={}, text="rate limited", status_code=429,
    ))
    calls = []
    monkeypatch.setattr(
        manager,
        "_serienstream_browser_redirect",
        lambda url, referer: calls.append((url, referer)) or "https://voe.sx/e/recovered",
    )

    assert manager.get_redirect_location(
        "https://serienstream.to/r?t=x",
        referer="https://serienstream.to/serie/test/staffel-1/episode-1",
    ) == "https://voe.sx/e/recovered"
    assert calls == [(
        "https://serienstream.to/r?t=x",
        "https://serienstream.to/serie/test/staffel-1/episode-1",
    )]


def test_http_gate_is_reported_only_after_shared_browser_is_still_gated(monkeypatch):
    manager = _redirect_manager(SimpleNamespace(
        url="https://serienstream.to/redirect-gate",
        request=SimpleNamespace(url="https://serienstream.to/redirect-gate"),
        headers={},
        text="<html><div id='frameBridge'>turnstile</div></html>",
        status_code=200,
    ))
    monkeypatch.setattr(
        manager,
        "_serienstream_browser_redirect",
        lambda *_args, **_kwargs: GATE_BLOCKED,
    )

    assert manager.get_redirect_location(
        "https://serienstream.to/r?t=x",
        referer="https://serienstream.to/serie/test/staffel-1/episode-1",
    ) == GATE_BLOCKED


def test_serienstream_redirect_follows_chain_to_external_embed(monkeypatch):
    manager = SessionManager.__new__(SessionManager)
    manager.TARGET_DOMAIN = "serienstream.to"
    manager._human_delay = lambda: None
    manager._browser_headers = lambda *_args: {}
    observed = {}

    def get(_url, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(
            url="https://voe.sx/e/example",
            request=SimpleNamespace(url="https://voe.sx/e/example"),
            headers={},
            text="<html>embed</html>",
            status_code=200,
        )

    manager._curl = SimpleNamespace(get=get)
    monkeypatch.setattr(
        manager,
        "_serienstream_browser_redirect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("browser recovery started")),
    )

    assert manager.get_redirect_location(
        "https://serienstream.to/r?t=x",
        referer="https://serienstream.to/serie/test/staffel-1/episode-1",
    ) == "https://voe.sx/e/example"
    assert observed["allow_redirects"] is True


def test_serienstream_redirect_accepts_external_js_fallback(monkeypatch):
    manager = _redirect_manager(SimpleNamespace(
        url="https://serienstream.to/r?t=x",
        request=SimpleNamespace(url="https://serienstream.to/r?t=x"),
        headers={},
        text='<script>window.location.href = "https://dood.example/e/abc"</script>',
        status_code=200,
    ))
    monkeypatch.setattr(
        manager,
        "_serienstream_browser_redirect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("browser recovery started")),
    )

    assert manager.get_redirect_location("https://serienstream.to/r?t=x") == "https://dood.example/e/abc"


def test_serienstream_nonredirect_response_can_be_resolved_by_shared_browser(monkeypatch):
    manager = _redirect_manager(SimpleNamespace(
        url="https://serienstream.to/r?t=x",
        request=SimpleNamespace(url="https://serienstream.to/r?t=x"),
        headers={}, text="<html>preparing player</html>", status_code=200,
    ))
    monkeypatch.setattr(
        manager,
        "_serienstream_browser_redirect",
        lambda *_args, **_kwargs: "https://vid.example/embed/abc",
    )

    assert manager.get_redirect_location(
        "https://serienstream.to/r?t=x",
        referer="https://serienstream.to/serie/test/staffel-1/episode-1",
    ) == "https://vid.example/embed/abc"


def test_other_provider_redirect_probe_stays_non_following(monkeypatch):
    manager = SessionManager.__new__(SessionManager)
    manager.TARGET_DOMAIN = "filmpalast.to"
    manager._human_delay = lambda: None
    manager._browser_headers = lambda *_args: {}
    manager._log = lambda *_args: None
    observed = {}

    def get(_url, **kwargs):
        observed.update(kwargs)
        return SimpleNamespace(
            headers={"Location": "https://example.org/embed"},
            text="",
            status_code=302,
        )

    manager._curl = SimpleNamespace(get=get)
    monkeypatch.setattr(
        manager, "_nodriver_get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("browser started")),
    )

    assert manager.get_redirect_location("https://filmpalast.to/r?t=x") == "https://example.org/embed"
    assert observed["allow_redirects"] is False


def test_blocked_episode_page_recovers_from_shared_browser(monkeypatch):
    manager = SessionManager.__new__(SessionManager)
    manager.TARGET_DOMAIN = "serienstream.to"
    manager._human_delay = lambda fast=False: None
    manager._curl_get = lambda _url: ("<html>cloudflare captcha</html>", 403)
    manager._log = lambda *_args: None
    monkeypatch.setattr(
        manager,
        "_serienstream_browser_html",
        lambda *_args, **_kwargs: "<html><button data-play-url='/r?t=ok'>VOE</button></html>",
    )

    html = manager.get("https://serienstream.to/serie/test/staffel-1/episode-1")
    assert "data-play-url" in html


def test_blocked_episode_page_raises_only_if_shared_browser_stays_blocked(monkeypatch):
    manager = SessionManager.__new__(SessionManager)
    manager.TARGET_DOMAIN = "serienstream.to"
    manager._human_delay = lambda fast=False: None
    manager._curl_get = lambda _url: ("<html>cloudflare captcha</html>", 403)
    manager._log = lambda *_args: None
    monkeypatch.setattr(manager, "_serienstream_browser_html", lambda *_args, **_kwargs: None)

    with pytest.raises(ProviderBlockedError):
        manager.get("https://serienstream.to/serie/test/staffel-1/episode-1")


def test_shared_browser_and_http_use_same_user_agent():
    headers = SessionManager._browser_headers(
        "https://serienstream.to/r?t=x",
        "https://serienstream.to/serie/test/staffel-1/episode-1",
    )
    assert headers["User-Agent"] == SERIESSTREAM_USER_AGENT


def test_shared_browser_cookie_sync_preserves_domain_and_persists(monkeypatch):
    class CookieJar:
        def __init__(self):
            self.values = []

        def set(self, name, value, **kwargs):
            self.values.append((name, value, kwargs))

    manager = SessionManager.__new__(SessionManager)
    manager.TARGET_DOMAIN = "serienstream.to"
    manager._curl = SimpleNamespace(cookies=CookieJar())
    manager._cookies = {}
    manager._cookie_file = SimpleNamespace()
    manager._log = lambda *_args: None
    saved = []
    monkeypatch.setattr(manager, "_save_cookies", lambda: saved.append(True))

    names = manager._install_shared_browser_cookies([
        {
            "name": "cf_clearance",
            "value": "clear",
            "domain": ".serienstream.to",
            "path": "/",
            "secure": True,
        },
        {
            "name": "other",
            "value": "ignored",
            "domain": "example.org",
            "path": "/",
            "secure": True,
        },
    ])

    assert names == ["cf_clearance"]
    assert manager._cookies == {"cf_clearance": "clear"}
    assert manager._curl.cookies.values[0][2]["domain"] == ".serienstream.to"
    assert saved == [True]


def test_extract_stops_after_first_still_blocked_redirect(monkeypatch, tmp_path):
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
