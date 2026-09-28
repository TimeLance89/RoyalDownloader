"""Resolver contracts shared by runtime attribution and Source Sentinel."""
from dataclasses import dataclass, asdict
import re
import hashlib
from urllib.parse import urlsplit

from media.hoster_intel import BASE_SCORE


@dataclass(frozen=True)
class HosterContract:
    hoster: str
    resolver: str
    capabilities: tuple
    markers: tuple = ()

    def public_dict(self):
        return asdict(self)


SPECIAL = {
    "voe": ("extract_stream_url", ("voe",)),
    "moflix": ("extract_stream_url", ("moflix",)),
    "veev": ("extract_stream_url", ("veev",)),
    "kinoger": ("extract_stream_url", ("fsst", "incvideo", "kinoger.be", "vidhide", "embed4me", "seekplays")),
    "doodstream": ("extract_doodstream_url", ("dood", "vide0", "d000d", "d0o0d", "dooood", "ds2play", "dsvplay", "ds2video")),
    "vidara": ("extract_vidara_url", ("vidara", "vidmatrix", "vidchamp", "vidachamp", "vidavaca", "viewdara", "thebesthost", "kinoger.pw")),
    "vidsonic": ("extract_vidsonic_url", ("vidsonic",)),
    "firestream": ("extract_firestream_url", ("firestream",)),
}
GENERIC = {"streamruby", "upcloud", "vidsrc", "closeload", "rapidrame", "upstream", "vinovo", "luluvid", "netu"}
CONTRACTS = {}
for name in set(BASE_SCORE) | set(SPECIAL) | GENERIC:
    key = re.sub(r"[^a-z0-9]", "", name)
    if key.startswith("filmfrei24"):
        CONTRACTS[key] = HosterContract(key, "direct", ("recognition", "manifest", "direct_media"), ("filmfrei24",))
    else:
        resolver, markers = SPECIAL.get(key, ("yt_dlp", (key,)))
        CONTRACTS[key] = HosterContract(key, resolver, ("recognition", "embed", "redirect", "player", "resolver", "manifest", "direct_media"), markers)


def hoster_key(name, url=""):
    label = re.sub(r"[^a-z0-9]", "", str(name).lower())[:50]
    if label in CONTRACTS:
        return label
    domain = (urlsplit(url).hostname or "").lower()
    # Label aliases are used for attribution, never as trust for domain repair.
    for key, contract in CONTRACTS.items():
        if any(marker in label or marker in domain for marker in contract.markers):
            return key
    return label or "unknown"


def runtime_contract(name, url=""):
    key = hoster_key(name, url)
    return CONTRACTS.get(key, HosterContract(key, "yt_dlp", ("recognition", "embed", "redirect", "resolver", "manifest", "direct_media")))


def canary_identity(url):
    parsed = urlsplit(url)
    return hashlib.sha256(f"{parsed.hostname}{parsed.path}".encode()).hexdigest()[:24]


def media_identity(url):
    parsed = urlsplit(url)
    return hashlib.sha256(f"{parsed.hostname}{parsed.path}".encode()).hexdigest()[:24] if parsed.hostname else ""
