"""Signed direct manifests retain their request context through resolution."""

from types import SimpleNamespace

import server  # noqa: F401 - installs the application runtime
from application_services import source_resolution
from media import downloader
from providers.models import FilmpalastMovie, HosterInfo


def test_dash_source_preserves_cookie_audio_and_referer(monkeypatch):
    monkeypatch.setattr(source_resolution.state, "content_languages", {"en"})
    intel = source_resolution.state.hoster_intel
    monkeypatch.setattr(intel, "rank", lambda hosters: list(hosters))
    monkeypatch.setattr(intel, "cooldown", lambda *_args, **_kwargs: (0, ""))
    monkeypatch.setattr(intel, "record_probe", lambda *_args, **_kwargs: None)
    captured = {}

    def probe(url, **kwargs):
        captured.update(url=url, **kwargs)
        return True, "ok"

    monkeypatch.setattr(source_resolution, "probe_stream_url", probe)
    hoster = HosterInfo(
        "MovieBox DASH", "https://cdn.example.com/index.mpd", "en", "1080p",
        "https://moviebox.ph/", "https://moviebox.ph", "dash", "en",
        {"Cookie": "CloudFront-Policy=signed"},
    )
    movie = FilmpalastMovie(
        title="Inception", url="moviebox:27205", provider="moviebox",
        content_language="en", hosters=[hoster],
    )
    result = source_resolution._extract_from_movie(movie, set())
    assert result.stream_info == (hoster.url, "dash")
    assert result.audio_language == "en"
    assert result.headers == hoster.headers
    assert captured["referer"] == hoster.referer
    assert captured["origin"] == hoster.origin
    assert captured["headers"] == hoster.headers


def test_dash_probe_passes_signed_headers_to_downloader(monkeypatch):
    monkeypatch.setattr(downloader, "ensure_public_http_url", lambda _url: None)
    commands = []

    def run(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stdout="ready")

    monkeypatch.setattr(downloader.subprocess, "run", run)
    ok, _message = downloader.probe_stream_url(
        "https://cdn.example.com/index.mpd", referer="https://moviebox.ph/",
        origin="https://moviebox.ph", headers={"Cookie": "CloudFront-Policy=signed"},
    )
    assert ok
    assert "https://moviebox.ph/" in commands[0]
    assert "Origin:https://moviebox.ph" in commands[0]
    assert "Cookie:CloudFront-Policy=signed" in commands[0]
