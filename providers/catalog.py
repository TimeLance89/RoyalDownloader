"""Zentraler Katalog aller Medienanbieter.

``content_language`` ist die Primär-/Legacy-Sprache, ``content_languages`` die
möglichen Providerfähigkeiten. Konkrete Titel und Episoden bestimmen ihre Tracks.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Optional


LANGUAGE_NAMES = {
    "de": "Deutsch",
    "en": "English",
    "es": "Español",
    "fr": "Français",
    "it": "Italiano",
    "nl": "Nederlands",
    "pl": "Polski",
    "pt": "Português",
    "tr": "Türkçe",
    "uk": "Українська",
    "ja": "日本語",
}

_LANGUAGE_ALIASES = {
    "de": "de",
    "de-de": "de",
    "deutsch": "de",
    "german": "de",
    "ger": "de",
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "english": "en",
    "englisch": "en",
    "eng": "en",
    "es": "es",
    "espanol": "es",
    "español": "es",
    "spanisch": "es",
    "spanish": "es",
    "fr": "fr",
    "francais": "fr",
    "français": "fr",
    "franzosisch": "fr",
    "französisch": "fr",
    "french": "fr",
    "it": "it",
    "italiano": "it",
    "italienisch": "it",
    "italian": "it",
    "nl": "nl",
    "nederlands": "nl",
    "niederlandisch": "nl",
    "niederländisch": "nl",
    "dutch": "nl",
    "pl": "pl",
    "polski": "pl",
    "polnisch": "pl",
    "polish": "pl",
    "pt": "pt",
    "portugues": "pt",
    "português": "pt",
    "portugiesisch": "pt",
    "portuguese": "pt",
    "tr": "tr",
    "turkce": "tr",
    "türkçe": "tr",
    "turkisch": "tr",
    "türkisch": "tr",
    "turkish": "tr",
    "uk": "uk",
    "ukrainisch": "uk",
    "ukrainian": "uk",
    "українська": "uk",
    "ja": "ja",
    "japanese": "ja",
    "japanisch": "ja",
}


def normalize_content_language(value: str, default: str = "") -> str:
    """Normalisiert BCP-47-Codes und verbreitete Sprachbezeichnungen."""
    raw = str(value or "").strip().replace("_", "-").casefold()
    if not raw:
        return default
    normalized = _LANGUAGE_ALIASES.get(raw)
    if normalized:
        return normalized
    for alias, language in sorted(
        _LANGUAGE_ALIASES.items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if raw.startswith(alias) and (
            len(raw) == len(alias) or not raw[len(alias)].isalpha()
        ):
            return language
    base = raw.split("-", 1)[0]
    return base if base in LANGUAGE_NAMES else default


@dataclass(frozen=True)
class ProviderDefinition:
    key: str
    label: str
    content_language: str
    media_types: tuple[str, ...]
    movie_priority: Optional[int] = None
    series_priority: Optional[int] = None
    anime_priority: Optional[int] = None
    source_prefixes: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    content_languages: tuple[str, ...] = ()
    track_languages: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        languages = tuple(dict.fromkeys((self.content_language, *self.content_languages)))
        object.__setattr__(self, "content_languages", languages)

    @property
    def primary_language(self) -> str:
        return self.content_language

    @property
    def language_label(self) -> str:
        return LANGUAGE_NAMES.get(self.content_language, self.content_language.upper())

    def public_dict(self) -> dict:
        payload = asdict(self)
        payload.pop("movie_priority", None)
        payload.pop("series_priority", None)
        payload.pop("anime_priority", None)
        payload.pop("source_prefixes", None)
        payload.pop("domains", None)
        payload.pop("track_languages", None)
        payload["media_types"] = list(self.media_types)
        payload["primary_language"] = self.primary_language
        payload["content_languages"] = list(self.content_languages)
        payload["language_labels"] = [LANGUAGE_NAMES.get(lang, lang.upper()) for lang in self.content_languages]
        payload["language_label"] = self.language_label
        payload["homepage"] = (
            f"https://{self.domains[0]}"
            if self.domains
            else ""
        )
        return payload


PROVIDER_CATALOG = {
    "filmfrei24": ProviderDefinition(
        key="filmfrei24",
        label="FilmFrei24",
        content_language="de",
        media_types=("movies",),
        movie_priority=110,
        source_prefixes=("filmfrei24:",),
        domains=("filmfrei24.com",),
    ),
    "filmpalast": ProviderDefinition(
        key="filmpalast",
        label="Filmpalast",
        content_language="de",
        media_types=("movies", "series"),
        movie_priority=10,
        series_priority=40,
        domains=("filmpalast.to",),
    ),
    "megakino": ProviderDefinition(
        key="megakino",
        label="MegaKino",
        content_language="de",
        media_types=("movies", "series"),
        movie_priority=30,
        series_priority=30,
        source_prefixes=("megakino:",),
        domains=("megakino.org",),
    ),
    "moflix": ProviderDefinition(
        key="moflix",
        label="Moflix",
        content_language="de",
        media_types=("movies", "series"),
        movie_priority=40,
        series_priority=20,
        source_prefixes=("moflix:",),
        domains=("moflix-stream.xyz",),
    ),
    "huhu": ProviderDefinition(
        key="huhu",
        label="Huhu",
        content_language="de",
        media_types=("movies", "series"),
        movie_priority=20,
        series_priority=15,
        source_prefixes=("huhu:", "huhu-movie:"),
        domains=("huhu.to",),
    ),
    "filmo": ProviderDefinition(
        key="filmo",
        label="Filmo",
        content_language="de",
        media_types=("movies",),
        movie_priority=25,
        source_prefixes=("filmo:",),
        domains=("filmo.to",),
    ),
    "einschalten": ProviderDefinition(
        key="einschalten",
        label="Einschalten",
        content_language="de",
        media_types=("movies",),
        movie_priority=50,
        source_prefixes=("einschalten:",),
        domains=("einschalten.in",),
    ),
    "kinox": ProviderDefinition(
        key="kinox",
        label="Kinox",
        content_language="de",
        media_types=("movies",),
        movie_priority=60,
        source_prefixes=("kinox:",),
        domains=("kinox.camp",),
    ),
    "kinoger": ProviderDefinition(
        key="kinoger",
        label="KinoGer",
        content_language="de",
        media_types=("movies", "series"),
        movie_priority=70,
        series_priority=50,
        source_prefixes=("kinoger:",),
        domains=("kinoger.com",),
    ),
    "xcine": ProviderDefinition(
        key="xcine",
        label="XCine",
        content_language="de",
        media_types=("movies", "series"),
        movie_priority=80,
        series_priority=60,
        source_prefixes=("xcine:",),
        domains=("xcine.ru",),
    ),
    "sflix": ProviderDefinition(
        key="sflix",
        label="SFlix",
        content_language="en",
        media_types=("movies", "series"),
        movie_priority=90,
        series_priority=70,
        source_prefixes=("sflix:",),
        domains=("sflix.win", "sflix.to"),
    ),
    "ridomovies": ProviderDefinition(
        key="ridomovies",
        label="Ridomovies",
        content_language="en",
        media_types=("movies", "series"),
        movie_priority=100,
        series_priority=80,
        source_prefixes=("ridomovies:",),
        domains=("ridomovies.su", "ridomovies.tv"),
    ),
    "vidsrc": ProviderDefinition(
        key="vidsrc", label="VidSrc", content_language="en",
        media_types=("movies", "series"), movie_priority=109,
        series_priority=119, source_prefixes=("vidsrc:",),
        domains=("vidsrc.sh", "data.vidsrcme.ru", "vidsrc.me", "vidsrcme.ru", "vsrc.su"),
    ),
    "vidrift": ProviderDefinition(
        key="vidrift", label="VidRift", content_language="en",
        media_types=("movies", "series"), movie_priority=109,
        series_priority=120, source_prefixes=("vidrift:",),
        domains=("embed.vidrift.net", "embed.vidrift.in"),
        content_languages=("en", "de", "fr", "es", "hi"),
    ),
    "vixsrc": ProviderDefinition(
        key="vixsrc", label="VixSrc", content_language="en",
        media_types=("movies", "series"), movie_priority=109,
        series_priority=121, source_prefixes=("vixsrc:",),
        domains=("vixsrc.to",), content_languages=("en", "it"),
    ),
    "vidrock": ProviderDefinition(
        key="vidrock", label="VidRock", content_language="en",
        media_types=("movies", "series"), movie_priority=109,
        series_priority=122, source_prefixes=("vidrock:",),
        domains=("vidrock.net",),
    ),
    "vidlink": ProviderDefinition(
        key="vidlink", label="VidLink", content_language="en",
        media_types=("movies", "series"), movie_priority=109,
        series_priority=124, source_prefixes=("vidlink:",),
        domains=("vidlink.pro",),
    ),
    "moviebox": ProviderDefinition(
        key="moviebox", label="MovieBox", content_language="en",
        media_types=("movies", "series"), movie_priority=109,
        series_priority=123, source_prefixes=("moviebox:",),
        domains=("movieboxhd.net", "moviebox.ph", "api3.aoneroom.com", "api4.aoneroom.com", "api5.aoneroom.com", "api6.aoneroom.com"),
        content_languages=("en", "de", "fr", "es", "it"),
    ),
    "mkissa": ProviderDefinition(
        key="mkissa",
        label="MKissa",
        content_language="en",
        media_types=("anime",),
        anime_priority=10,
        source_prefixes=("mkissa:",),
        domains=("mkissa.to", "api.mkissa.net"),
        track_languages=(("dub", "en"), ("sub", "en"), ("raw", "ja")),
    ),
    "aniworld": ProviderDefinition(
        key="aniworld",
        label="AniWorld",
        content_language="de",
        media_types=("anime",),
        anime_priority=5,
        source_prefixes=("aniworld:",),
        domains=("aniworld.to",),
        content_languages=("de", "en"),
        track_languages=(("dub", "de"), ("sub", "de"), ("eng", "en")),
    ),
    "flixitv": ProviderDefinition(
        key="flixitv", label="FlixiTV", content_language="de",
        media_types=("movies", "series"), movie_priority=105,
        series_priority=90, source_prefixes=("flixitv:",),
        domains=("flixitv-stream.eu",),
    ),
    "kinoking": ProviderDefinition(
        key="kinoking", label="KinoKing", content_language="de",
        media_types=("movies", "series"), movie_priority=106,
        series_priority=100, source_prefixes=("kinoking:",),
        domains=("kinoking.cc",),
    ),
    "movie2k": ProviderDefinition(
        key="movie2k", label="Movie2k", content_language="de",
        media_types=("movies", "series"), movie_priority=107,
        series_priority=105, source_prefixes=("movie2k:",),
        domains=("movie2k.cx",),
    ),
    "hdfilme_family": ProviderDefinition(
        key="hdfilme_family", label="HDFilme Family", content_language="de",
        media_types=("movies", "series"), movie_priority=108,
        series_priority=110, source_prefixes=("hdfilme_family:",),
        domains=("hdfilme.ceo", "hdfilme.win", "streamcloud.download", "streamkiste.bid"),
    ),
    "kellerkino": ProviderDefinition(
        key="kellerkino", label="KellerKino", content_language="de",
        media_types=("movies",), movie_priority=109,
        source_prefixes=("kellerkino:",),
        domains=("www.kellerkino.com", "kellerkino.com"),
    ),
    "serienstream": ProviderDefinition(
        key="serienstream",
        label="Serienstream",
        content_language="de",
        media_types=("series",),
        series_priority=10,
        source_prefixes=("serienstream:",),
        domains=("serienstream.to",),
    ),
}


def provider_keys(media_type: str) -> tuple[str, ...]:
    priority_field = {
        "movies": "movie_priority",
        "series": "series_priority",
        "anime": "anime_priority",
    }.get(media_type)
    if priority_field is None:
        return ()
    entries = [
        definition
        for definition in PROVIDER_CATALOG.values()
        if media_type in definition.media_types
    ]
    return tuple(
        definition.key
        for definition in sorted(
            entries,
            key=lambda item: getattr(item, priority_field) or 10_000,
        )
    )


def provider_for_source(value: str, default: str = "filmpalast") -> str:
    source = str(value or "").strip().casefold()
    for key, definition in PROVIDER_CATALOG.items():
        if any(source.startswith(prefix.casefold()) for prefix in definition.source_prefixes):
            return key
        if any(domain.casefold() in source for domain in definition.domains):
            return key
    return default


def provider_content_language(provider: str, default: str = "") -> str:
    """Primary/legacy default; not proof of title or episode track availability."""
    definition = PROVIDER_CATALOG.get(str(provider or "").strip().casefold())
    return definition.content_language if definition else default


def provider_content_languages(provider: str) -> tuple[str, ...]:
    definition = PROVIDER_CATALOG.get(str(provider or "").strip().casefold())
    return definition.content_languages if definition else ()


def provider_supports_languages(provider: str, languages) -> bool:
    return bool(set(provider_content_languages(provider)) & {
        normalize_content_language(language) for language in languages
    })


def provider_track_language(provider: str, track: str) -> str:
    definition = PROVIDER_CATALOG.get(str(provider or "").strip().casefold())
    return dict(definition.track_languages).get(str(track or "").casefold(), "") if definition else ""


def selected_episode_language(provider: str, source: str) -> str:
    """Language of an explicitly selected adapter track, not a capability guess."""
    from providers.models import parse_episode_slug
    parsed = parse_episode_slug(str(source or ""))
    if not parsed or not parsed[0].startswith(f"{provider}:"):
        return ""
    descriptor, separator, track = parsed[0].partition("|")
    return provider_track_language(provider, track) if separator and descriptor else ""


def selected_source_language_allowed(provider: str, language: str, enabled, source: str = "") -> bool:
    """Global language policy, with explicitly selected auxiliary episode tracks."""
    language = normalize_content_language(language)
    if language in enabled:
        return True
    return bool(language and language not in provider_content_languages(provider)
                and selected_episode_language(provider, source) == language
                and provider_supports_languages(provider, enabled))


def provider_language_keys() -> tuple[str, ...]:
    """Inhaltssprachen in stabiler Katalog-Reihenfolge."""
    return tuple(dict.fromkeys(
        language
        for definition in PROVIDER_CATALOG.values()
        for language in definition.content_languages
    ))


def provider_language_payload() -> dict[str, str]:
    return {
        language: LANGUAGE_NAMES.get(language, language.upper())
        for language in provider_language_keys()
    }


def provider_catalog_payload() -> dict[str, dict]:
    return {
        key: definition.public_dict()
        for key, definition in PROVIDER_CATALOG.items()
    }
