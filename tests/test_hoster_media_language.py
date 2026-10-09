"""Retain the actual release title through HTML and browser extraction."""

import asyncio
import copy
from types import SimpleNamespace

import pytest

from media import extractor
from media.source_language import StreamInfo, stream_audio_language_allowed


GERSUB = "Sailor.Moon.S01E01.GerSub.720p.BluRay.x264-Pudding-sama.mp4"


@pytest.mark.parametrize("marker", ["GerSub", "GER.SUB", "German Subbed", "deutsche Untertitel", "Deutsch-Sub"])
def test_subtitle_marker_cannot_satisfy_german_audio(marker):
    stream = StreamInfo("https://cdn.example/master.m3u8", "hls", [f"Sailor.Moon.{marker}.mp4"])
    assert not stream_audio_language_allowed(stream, "de")
    assert stream_audio_language_allowed(stream, "ja")
    assert stream_audio_language_allowed(stream, "de", audio_language="de")


@pytest.mark.parametrize("title", ["Sailor.Moon.German.DL.mp4", "German Subway", "Gersubmarine", "Sailor Moon"])
def test_non_subtitle_titles_keep_existing_language_evidence(title):
    assert stream_audio_language_allowed(StreamInfo("https://cdn.example/video.mp4", "mp4", [title]), "de")


def test_encoded_media_filename_also_proves_contradiction():
    assert not stream_audio_language_allowed(("https://cdn.example/Sailor%2EMoon%2EGerSub.mp4?token=1", "mp4"), "de")


def test_stream_tuple_contract_survives_copy():
    original = StreamInfo("https://cdn.example/master.m3u8", "hls", [GERSUB])
    cloned = copy.deepcopy(original)
    assert cloned == (original[0], "hls")
    assert cloned.media_titles == (GERSUB,)


@pytest.mark.parametrize("browser", [False, True])
def test_redirected_voe_title_survives_regex_and_browser(monkeypatch, browser):
    fetched = []
    def fetch(_session, url, **_kwargs):
        fetched.append(url)
        if url == "https://voe.sx/example":
            return '<script>window.location.href="https://voe-alias.example/e/example";</script>'
        return f'<title>Watch {GERSUB}</title><h1>{GERSUB}</h1>'

    monkeypatch.setattr(extractor, "_fetch_html", fetch)
    monkeypatch.setattr(extractor, "_extract_regex", lambda _html: None if browser else ("https://cdn.example/master.m3u8", "hls"))
    monkeypatch.setattr(extractor, "ensure_public_http_url", lambda _url: None)
    pool = SimpleNamespace(extract=lambda *_args, **_kwargs: ("https://cdn.example/master.m3u8", "hls"))
    result = extractor.extract_stream_url("https://voe.sx/example", session=object(), pool=pool)
    assert result == ("https://cdn.example/master.m3u8", "hls")
    assert GERSUB in result.media_titles
    assert not stream_audio_language_allowed(result, "de")
    assert fetched == ["https://voe.sx/example", "https://voe-alias.example/e/example"]


def test_doodstream_retains_title_after_handshake(monkeypatch):
    monkeypatch.setattr(extractor, "_fetch_html", lambda *_args, **_kwargs: f"<title>{GERSUB}</title><script>$.get('/pass_md5/token')</script>")
    monkeypatch.setattr(extractor, "request_proxy_kwargs", lambda _url: {})
    session = SimpleNamespace(get=lambda *_args, **_kwargs: SimpleNamespace(text="https://cdn.example/video/", raise_for_status=lambda: None))
    result = extractor.extract_doodstream_url("https://dood.yt/e/example", session=session)
    assert result[1] == "mp4"
    assert GERSUB in result.media_titles
    assert not stream_audio_language_allowed(result, "de")


def test_browser_rendered_release_title_is_kept_before_tab_closes(monkeypatch):
    handlers = []
    closed = []
    sends = []
    class Tab:
        def add_handler(self, _event, handler):
            handlers.append(handler)

        async def send(self, command):
            sends.append(True)
            if len(sends) == 2:
                handlers[0](SimpleNamespace(request=SimpleNamespace(url="https://cdn.example/master.m3u8")))
            if len(sends) == 3:
                request = next(command)
                assert request["method"] == "Runtime.evaluate"
                assert request["params"]["returnByValue"] is True
                assert "serializationOptions" not in request["params"]
                return SimpleNamespace(value=[GERSUB, None, None]), None

        async def close(self):
            closed.append(True)

    async def get(*_args, **_kwargs):
        return Tab()

    async def sleep(_seconds):
        pass

    monkeypatch.setattr(extractor.asyncio, "sleep", sleep)
    pool = extractor.VOEBrowserPool()
    pool._browser = SimpleNamespace(get=get)
    result = asyncio.run(pool._async_extract_inner("https://voe.sx/example", 5))
    assert result == ("https://cdn.example/master.m3u8", "hls")
    assert result.media_titles == (GERSUB,)
    assert closed == [True]
