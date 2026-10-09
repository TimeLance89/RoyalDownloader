"""The enabled stream languages must apply to concrete episode hosters."""

import time
from types import SimpleNamespace

import pytest
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


def test_german_subtitles_never_satisfy_german_audio(monkeypatch):
    probed = []
    _prepare(monkeypatch, lambda url, **_kwargs: (probed.append(url) or True, "ok"))
    for label in ("Deutsch (Untertitel)", "Deutsch Sub", "German Subbed",
                  "Original (deutsche Untertitel)", "Japanisch (deutsche Untertitel)"):
        movie = _episode(_hoster(label, "sub"))
        movie.provider = "serienstream"
        movie._required_content_language = "de"
        assert source_resolution._extract_from_movie(movie, set()).stream_info is None
    assert probed == []


def test_subtitle_only_label_cannot_inherit_default_german(monkeypatch):
    probed = []
    _prepare(monkeypatch, lambda url, **_kwargs: (probed.append(url) or True, "ok"))
    result = source_resolution._extract_from_movie(
        _episode(_hoster("Deutsch (Untertitel)", "sub"), _hoster("Deutsch", "dub")), set()
    )
    assert result.stream_info == ("https://example.invalid/dub.m3u8", "hls")
    assert probed == ["https://example.invalid/dub.m3u8"]


def test_huhu_de_label_cannot_override_redirected_voe_gersub(monkeypatch):
    from media import extractor
    from providers.huhu import HuhuScraper

    probed = []
    _prepare(monkeypatch, lambda url, **_kwargs: (probed.append(url) or True, "ok"))
    scraper = object.__new__(HuhuScraper)
    hosters = scraper._source_hosters([{
        "name": "Server C1", "languages": ["de"], "type": "url",
        "url": "https://voe.sx/example",
    }])
    assert hosters[0].language == "de"
    fetched = []
    def fetch(_session, url, **_kwargs):
        fetched.append(url)
        if url == "https://voe.sx/example":
            return '<script>window.location="https://voe-alias.example/e/example";</script>'
        return '<title>Sailor.Moon.S01E01.GerSub.720p.BluRay.x264-Pudding-sama.mp4</title>'

    monkeypatch.setattr(extractor, "_fetch_html", fetch)
    monkeypatch.setattr(extractor, "_extract_regex", lambda _html: None)
    monkeypatch.setattr(extractor, "ensure_public_http_url", lambda _url: None)
    pool = SimpleNamespace(extract=lambda *_args, **_kwargs: ("https://cdn.example/sub.m3u8", "hls"))
    monkeypatch.setattr(source_resolution, "_shared_browser_pool", lambda _reason: pool)
    monkeypatch.setattr(source_resolution, "pre_check_voe", lambda *_args, **_kwargs: "ok")
    monkeypatch.setattr(source_resolution, "hoster_profile_safely", lambda *_args: {})
    monkeypatch.setattr(source_resolution, "extract_stream_url", extractor.extract_stream_url)
    movie = _episode(*hosters, _hoster("de", "dub"))
    movie._required_content_language = "de"
    barren = set()

    result = source_resolution._extract_from_movie(movie, set(), barren_hoster_urls=barren)
    assert result.stream_info == ("https://example.invalid/dub.m3u8", "hls")
    assert probed == ["https://example.invalid/dub.m3u8"]
    assert "https://voe.sx/example" in barren
    assert len(fetched) == 2
    # A repeated attempt must not re-resolve the already rejected release.
    source_resolution._extract_from_movie(movie, set(), barren_hoster_urls=barren)
    assert len(fetched) == 2


@pytest.mark.parametrize("required, audio, accepted", [("de", "", False), ("ja", "", True), ("de", "de", True)])
def test_actual_release_evidence_respects_audio_lane(monkeypatch, required, audio, accepted):
    from media.source_language import StreamInfo

    probed = []
    _prepare(monkeypatch, lambda url, **_kwargs: (probed.append(url) or True, "ok"))
    monkeypatch.setattr(source_resolution, "_shared_browser_pool", lambda _reason: object())
    monkeypatch.setattr(source_resolution, "pre_check_voe", lambda *_args, **_kwargs: "ok")
    monkeypatch.setattr(source_resolution, "hoster_profile_safely", lambda *_args: {})
    monkeypatch.setattr(source_resolution, "extract_stream_url", lambda *_args, **_kwargs: StreamInfo(
        "https://cdn.example/master.m3u8", "hls", ["Sailor.Moon.GerSub.mp4"],
    ))
    hoster = HosterInfo("VOE", "https://voe.sx/example", required, audio_language=audio)
    movie = _episode(hoster)
    movie._required_content_language = required
    result = source_resolution._extract_from_movie(movie, set())
    assert bool(result.stream_info) == accepted
    assert bool(probed) == accepted
    if accepted:
        assert result.content_language == required
        assert result.audio_language == audio


@pytest.mark.parametrize("titles", [None, ["Sailor.Moon.GerSub.mp4"]])
def test_old_or_contradictory_pre_resolved_german_cache_requires_fresh_extraction(monkeypatch, titles):
    from application_services import movie_subscription_stream_quality as quality

    calls = []
    monkeypatch.setattr(quality.state, "content_languages", {"de"})
    monkeypatch.setattr(quality, "_ORIGINAL_EXTRACT_FROM_MOVIE", lambda *_args, **_kwargs: calls.append(True) or SimpleNamespace(stream_info=None))
    movie = _episode(_hoster("de", "sub"))
    movie._required_content_language = "de"
    movie._quality_pre_resolved = {
        "expires_at": time.time() + 300,
        "stream_info": ("https://cdn.example/master.m3u8", "hls"),
        "source_hoster_url": "https://voe.sx/example",
        "content_language": "de",
    }
    if titles is not None:
        movie._quality_pre_resolved["media_titles"] = titles
    assert quality._extract_from_movie(movie, set()).stream_info is None
    assert calls == [True]


def test_checked_german_cache_can_be_reused_without_losing_release_title(monkeypatch):
    from application_services import movie_subscription_stream_quality as quality

    monkeypatch.setattr(quality.state, "content_languages", {"de"})
    monkeypatch.setattr(quality, "_ORIGINAL_EXTRACT_FROM_MOVIE", lambda *_args, **_kwargs: pytest.fail("Valid checked cache should be reused"))
    original = source_resolution._HosterResult()
    original.content_language = "de"
    original.stream_info = ("https://cdn.example/master.m3u8", "hls")
    original.media_titles = ("Sailor.Moon.German.DL.mp4",)
    original.source_hoster_url = "https://voe.sx/example"
    movie = _episode(_hoster("de", "dub"))
    movie._quality_pre_resolved = quality._pre_resolved_payload(original, {})
    result = quality._extract_from_movie(movie, set())
    assert result.stream_info == original.stream_info
    assert tuple(result.media_titles) == original.media_titles
