"""Shared browser/network identity for the SerienStream provider session.

StreamFlix keeps WebView and OkHttp on one cookie jar and one browser identity.
Royal uses the same principle: Chromium and curl_cffi must present the same
User-Agent while exchanging the same provider cookies.
"""

SERIESSTREAM_HOSTS = {"serienstream.to", "www.serienstream.to"}
SERIESSTREAM_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)
SERIESSTREAM_ACCEPT_LANGUAGE = "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"
