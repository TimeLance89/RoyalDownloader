"""Small shared helpers for HTTP-only provider adapters."""

from __future__ import annotations

import re
import threading
import time
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from core import egress_curl as requests
from media.hoster_contracts import hoster_key
from providers.models import HosterInfo


_ALIASES = {
    "doodstream": "Doodstream", "voe": "VOE", "firestream": "FireStream",
    "streamtape": "Streamtape", "vidoza": "Vidoza", "vidmoly": "Vidmoly",
    "filemoon": "Filemoon", "vinovo": "Vinovo", "mixdrop": "Mixdrop",
    "supervideo": "Supervideo", "dropload": "Dropload", "dr0pstream": "Dropload",
    "mxdrop": "Mixdrop", "luluvid": "Luluvid", "lulust": "Luluvid",
    "playmogo": "PlayMogo", "ano": "Ano", "jeremyparticipantanything": "JeremyParticipantAnything",
}


def hoster(url: str, language: str = "", quality: str = "", label: str = "") -> HosterInfo | None:
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    key = hoster_key(label or parsed.hostname, url)
    if key == parsed.hostname.replace(".", ""):
        key = parsed.hostname.split(".")[-2] if "." in parsed.hostname else key
    return HosterInfo(_ALIASES.get(key, key.capitalize()), url, language, quality)


class CachedHTTP:
    """One browser-shaped session, bounded cache, and provider health feedback."""

    def __init__(self, provider: str, health=None):
        self.provider = provider
        self.health = health
        self.session = requests.Session(impersonate="chrome")
        self._lock = threading.RLock()
        self._cache: dict[str, tuple[float, BeautifulSoup]] = {}

    def soup(self, url: str, ttl: int = 600) -> BeautifulSoup:
        with self._lock:
            now = time.monotonic()
            cached = self._cache.get(url)
            if cached and cached[0] > now:
                return cached[1]
            if self.health is not None and not self.health.request_allowed(self.provider):
                raise RuntimeError(f"{self.provider} im Provider-Cooldown")
            try:
                response = self.session.get(url, timeout=12)
                response.raise_for_status()
                if re.search(r"Just a moment|cf-challenge|captcha challenge", response.text, re.I):
                    raise RuntimeError("Provider-Challenge")
                result = BeautifulSoup(response.content, "lxml")
                self._cache[url] = (now + ttl, result)
                return result
            except Exception as exc:
                if self.health is not None:
                    self.health.mark_blocked(self.provider, "transient_failure", str(exc))
                raise
