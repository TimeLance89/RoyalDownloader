from contextlib import nullcontext
from types import SimpleNamespace

from api.api_movie_playback_router import _stream_options


def playback_info(monkeypatch, container):
    source = {
        "Protocol": "File", "Id": "source", "Container": container,
        "RunTimeTicks": 61_271_250_000,
        "MediaStreams": [
            {"Type": "Video", "Codec": "h264", "BitDepth": 8},
            {"Type": "Audio", "Codec": "aac"},
        ],
    }
    monkeypatch.setattr(
        "api.api_movie_playback_router.requests.get",
        lambda *args, **kwargs: nullcontext(SimpleNamespace(
            status_code=200, json=lambda: {"MediaSources": [source]},
        )),
    )


def test_ts_with_aac_is_converted_to_mp4_in_isolated_playback_sessions(monkeypatch):
    playback_info(monkeypatch, "ts")
    first = _stream_options("http://jellyfin", {}, "encanto", 9_790_000_000)
    retry = _stream_options("http://jellyfin", {}, "encanto", 9_790_000_000)
    assert first["Static"] == "false"
    assert first["AllowAudioStreamCopy"] == "false"
    assert first["AudioCodec"] == "aac"
    assert first["StartTimeTicks"] == 9_790_000_000
    assert first["PlaySessionId"] != retry["PlaySessionId"]
    assert first["DeviceId"] == retry["DeviceId"]


def test_compatible_mp4_can_still_stream_directly(monkeypatch):
    playback_info(monkeypatch, "mp4")
    options = _stream_options("http://jellyfin", {}, "movie")
    assert options == {"MediaSourceId": "source", "Static": "true"}
