"""Production routing must use proven repairs and fail open when they fail."""
from types import SimpleNamespace

import server
from application_services import source_resolution
from providers.models import FilmpalastMovie, HosterInfo


def prepare(monkeypatch, profile):
    state = source_resolution.state
    monkeypatch.setattr(state, "content_languages", {"de"})
    monkeypatch.setattr(state, "hoster_intel", SimpleNamespace(rank=lambda rows: rows, cooldown=lambda *_args, **_kwargs: (0, ""), record_probe=lambda *_args, **_kwargs: None))
    monkeypatch.setattr(source_resolution, "hoster_profile_safely", lambda *_: profile)
    monkeypatch.setattr(server, "probe_stream_url", lambda *_args, **_kwargs: (True, "ok"))


def test_validated_player_repair_precedes_browser_fallback(monkeypatch):
    profile = {"player_selector": "script#config", "player_json_path": ["player", "sources", 0, "file"], "embed_domain": "new.example", "embed_path_prefix": "/embed/"}
    prepare(monkeypatch, profile)
    calls, signals = [], []
    def extract(url, **options):
        calls.append((url, options))
        return "https://media.example/known.m3u8", "hls"
    monkeypatch.setattr(server, "extract_stream_url", extract)
    monkeypatch.setattr(source_resolution, "_shared_browser_pool", lambda *_: (_ for _ in ()).throw(AssertionError("Proven HTTP profile must not start browser")))
    monkeypatch.setattr(source_resolution, "observe_hoster_safely", lambda *args: signals.append(args))
    movie = FilmpalastMovie(title="Known", url="https://filmpalast.to/stream/known", provider="filmpalast", hosters=[HosterInfo("VOE", "https://old.example/e/known", "Deutsch")])
    result = source_resolution._extract_from_movie(movie, set())
    assert result.stream_info == ("https://media.example/known.m3u8", "hls")
    assert calls[0][0] == "https://new.example/embed/known"
    assert calls[0][1]["repair_profile"] == profile
    assert len(calls) == 1
    assert signals[0][2] is True
    assert signals[0][-1] == "https://media.example/known.m3u8"


def test_monitoring_or_repair_failure_keeps_normal_route(monkeypatch):
    prepare(monkeypatch, {"player_selector": "script#config"})
    monkeypatch.setattr(server, "extract_stream_url", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("Monitoring failure")))
    monkeypatch.setattr(source_resolution, "observe_hoster_safely", lambda *_args: None)
    movie = FilmpalastMovie(title="Known", url="https://filmpalast.to/stream/known", provider="filmpalast", hosters=[HosterInfo("filmfrei24", "https://media.example/known.m3u8", "Deutsch")])
    result = source_resolution._extract_from_movie(movie, set())
    assert result.stream_info == ("https://media.example/known.m3u8", "hls")
