"""Release-title evidence for the requested audio language."""

import re
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup


class StreamInfo(tuple):
    """Keep the existing (url, kind) contract and retain hoster file titles."""

    def __new__(cls, url, kind, media_titles=()):
        result = super().__new__(cls, (url, kind))
        result.media_titles = tuple(dict.fromkeys(str(value) for value in media_titles if value))
        return result

    def __getnewargs__(self):
        return self[0], self[1], self.media_titles


def with_media_titles(result, html=""):
    if result is None:
        return None
    titles = list(getattr(result, "media_titles", ()))
    if html:
        soup = BeautifulSoup(html, "html.parser")
        titles.extend(node.get_text(" ", strip=True) for node in soup.select("title, h1")[:8])
        titles.extend(node.get("content", "") for node in soup.select('meta[property="og:title"]')[:2])
    return StreamInfo(*result, media_titles=titles)


_GERMAN_SUBTITLE_RELEASE = re.compile(
    r"(?<![a-z0-9])(?:ger|german|deutsch(?:e[nr]?)?|de)[\s._-]*"
    r"(?:sub(?:bed|s|titles?)?|untertitel)(?![a-z0-9])",
    re.IGNORECASE,
)


def stream_audio_language_allowed(stream_info, content_language, media_titles=(), audio_language=""):
    """GerSub describes subtitles, so it cannot prove a German audio lane.

    A separately identified German manifest track remains selectable through
    the downloader's strict audio selector. GerSub alone does not prove which
    original language is spoken and must never be relabeled as Japanese.
    """
    if content_language != "de" or audio_language == "de":
        return True
    titles = tuple(media_titles) + tuple(getattr(stream_info, "media_titles", ()))
    if stream_info:
        titles += (unquote(urlsplit(stream_info[0]).path.rsplit("/", 1)[-1]),)
    return not any(_GERMAN_SUBTITLE_RELEASE.search(str(title)) for title in titles)
