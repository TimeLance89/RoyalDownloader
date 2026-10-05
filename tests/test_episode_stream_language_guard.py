"""The enabled stream languages must apply to concrete episode hosters."""

import time
from types import SimpleNamespace

import server  # noqa: F401 - publishes the runtime services
from application_services import source_resolution
from providers.models import FilmpalastMovie, HosterInfo


def _episode(*hosters):
    return FilmpalastMovie(
        title="Testserie S01E01",
        url="https://huhu.to/serie/testserie/staffel-1/episode-1",
        provider="huhu",
        content_language="de",
        hosters=list(hosters),
    )


def _hoster(language, suffix):
    return HosterInfo(
        "filmfrei24",
        f"https://example.invalid/{suffix}.m3u8",
        language,
    )


def _prepare(monkeypatch, probe):
    monkeypatch.setattr(source_resolution.state, "content_languages", {"de"})
    monkeypatch.setattr(
        source_resolution.state.hoster_intel, "rank", lambda hosters: list(hosters)
    )
    monkeypatch.setattr(
        source_resolution.state.hoster_intel,
        "cooldown",
        lambda *_args, **_kwargs: (0, ""),
    )
    monkeypatch.setattr(
        source_resolution.state.hoster_intel,
        "record_probe",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(source_resolution, "probe_stream_url", probe)


def test_english_only_episode_never_reaches_stream_probe(monkeypatch):
    probed = []
    _prepare(
        monkeypatch,
        lambda url, **_kwargs: (probed.append(url) or True, "ok"),
    )

    result = source_resolution._extract_from_movie(
        _episode(_hoster("Englisch", "english")), set()
    )

    assert result.stream_info is None
    assert probed == []


def test_failed_german_hoster_does_not_fall_back_to_english(monkeypatch):
    probed = []
    _prepare(
        monkeypatch,
        lambda url, **_kwargs: (probed.append(url) and False, "unavailable"),
    )

    result = source_resolution._extract_from_movie(
        _episode(_hoster("Deutsch", "german"), _hoster("Englisch", "english")),
        set(),
    )

    assert result.stream_info is None
    assert probed == ["https://example.invalid/german.m3u8"]


def test_german_hoster_remains_available_after_english_is_skipped(monkeypatch):
    probed = []
    _prepare(
        monkeypatch,
        lambda url, **_kwargs: (probed.append(url) or True, "ok"),
    )

    result = source_resolution._extract_from_movie(
        _episode(_hoster("Englisch", "english"), _hoster("Deutsch", "german")),
        set(),
    )

    assert result.stream_info == ("https://example.invalid/german.m3u8", "hls")
    assert probed == ["https://example.invalid/german.m3u8"]


def test_pre_resolved_english_stream_cannot_bypass_language_guard(monkeypatch):
    from application_services import movie_subscription_stream_quality as quality

    monkeypatch.setattr(quality.state, "content_languages", {"de"})
    calls = []
    monkeypatch.setattr(
        quality,
        "_ORIGINAL_EXTRACT_FROM_MOVIE",
        lambda *_args, **_kwargs: calls.append(True) or SimpleNamespace(stream_info=None),
    )
    movie = _episode(_hoster("Englisch", "english"))
    movie._quality_pre_resolved = {
        "expires_at": time.time() + 300,
        "stream_info": ("https://example.invalid/english.m3u8", "hls"),
        "source_hoster_url": "https://example.invalid/english.m3u8",
        "content_language": "en",
    }

    result = quality._extract_from_movie(movie, set())

    assert result.stream_info is None
    assert calls == [True]


def test_pinned_german_queue_lane_wins_even_when_english_is_globally_enabled(monkeypatch):
    probed = []
    monkeypatch.setattr(source_resolution.state, "content_languages", {"de", "en"})
    monkeypatch.setattr(
        source_resolution.state.hoster_intel, "rank", lambda hosters: list(hosters)
    )
    monkeypatch.setattr(
        source_resolution.state.hoster_intel,
        "cooldown",
        lambda *_args, **_kwargs: (0, ""),
    )
    monkeypatch.setattr(
        source_resolution.state.hoster_intel,
        "record_probe",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        source_resolution,
        "probe_stream_url",
        lambda url, **_kwargs: (probed.append(url) or True, "ok"),
    )
    movie = FilmpalastMovie(
        title="Bilingual S01E01",
        url="https://moviebox.example/episode",
        provider="moviebox",
        content_language="en",
        hosters=[
            _hoster("Englisch", "english"),
            _hoster("Deutsch", "german"),
        ],
    )
    movie._required_content_language = "de"

    result = source_resolution._extract_from_movie(movie, set())

    assert result.content_language == "de"
    assert result.stream_info == ("https://example.invalid/german.m3u8", "hls")
    assert probed == ["https://example.invalid/german.m3u8"]


def test_unknown_track_on_multilingual_provider_fails_closed(monkeypatch):
    probed = []
    monkeypatch.setattr(source_resolution.state, "content_languages", {"de"})
    monkeypatch.setattr(
        source_resolution.state.hoster_intel, "rank", lambda hosters: list(hosters)
    )
    monkeypatch.setattr(
        source_resolution.state.hoster_intel,
        "cooldown",
        lambda *_args, **_kwargs: (0, ""),
    )
    monkeypatch.setattr(
        source_resolution.state.hoster_intel,
        "record_probe",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        source_resolution,
        "probe_stream_url",
        lambda url, **_kwargs: (probed.append(url) or True, "ok"),
    )
    movie = FilmpalastMovie(
        title="Unknown track S01E01",
        url="https://moviebox.example/episode",
        provider="moviebox",
        content_language="en",
        hosters=[_hoster("", "unknown")],
    )
    movie._required_content_language = "de"

    result = source_resolution._extract_from_movie(movie, set())

    assert result.stream_info is None
    assert probed == []


def test_english_track_never_satisfies_pinned_german_lane(monkeypatch):
    probed = []
    monkeypatch.setattr(source_resolution.state, "content_languages", {"de", "en"})
    monkeypatch.setattr(
        source_resolution.state.hoster_intel, "rank", lambda hosters: list(hosters)
    )
    monkeypatch.setattr(
        source_resolution.state.hoster_intel,
        "cooldown",
        lambda *_args, **_kwargs: (0, ""),
    )
    monkeypatch.setattr(
        source_resolution.state.hoster_intel,
        "record_probe",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        source_resolution,
        "probe_stream_url",
        lambda url, **_kwargs: (probed.append(url) or True, "ok"),
    )
    movie = FilmpalastMovie(
        title="English only S01E03",
        url="https://embed.vidrift.net/tv/1/1/3",
        provider="vidrift",
        content_language="en",
        hosters=[_hoster("English", "english-only")],
    )
    movie._required_content_language = "de"

    result = source_resolution._extract_from_movie(movie, set())

    assert result.stream_info is None
    assert probed == []
