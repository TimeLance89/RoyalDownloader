"""Zentraler Katalog aller Medienanbieter.

Die ``content_language`` beschreibt die erwartete Sprache des angebotenen
Streams. Eine konkrete Hoster-Sprachangabe darf diesen Anbieter-Standard später
überschreiben.
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
    source_prefixes: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()

    @property
    def language_label(self) -> str:
        return LANGUAGE_NAMES.get(self.content_language, self.content_language.upper())

    def public_dict(self) -> dict:
        payload = asdict(self)
        payload.pop("movie_priority", None)
        payload.pop("series_priority", None)
        payload.pop("source_prefixes", None)
        payload.pop("domains", None)
        payload["media_types"] = list(self.media_types)
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
        movie_priority=10,
        source_prefixes=("filmfrei24:",),
        domains=("filmfrei24.com",),
    ),
    "filmpalast": ProviderDefinition(
        key="filmpalast",
        label="Filmpalast",
        content_language="de",
        media_types=("movies", "series"),
        movie_priority=20,
        series_priority=30,
        domains=("filmpalast.to",),
    ),
    "megakino": ProviderDefinition(
        key="megakino",
        label="MegaKino",
        content_language="de",
        media_types=("movies", "series"),
        movie_priority=30,
        series_priority=20,
        source_prefixes=("megakino:",),
        domains=("megakino.org",),
    ),
    "moflix": ProviderDefinition(
        key="moflix",
        label="Moflix",
        content_language="de",
        media_types=("movies", "series"),
        movie_priority=40,
        series_priority=40,
        source_prefixes=("moflix:",),
        domains=("moflix-stream.xyz",),
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
    priority_field = "movie_priority" if media_type == "movies" else "series_priority"
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
    definition = PROVIDER_CATALOG.get(str(provider or "").strip().casefold())
    return definition.content_language if definition else default


def provider_catalog_payload() -> dict[str, dict]:
    return {
        key: definition.public_dict()
        for key, definition in PROVIDER_CATALOG.items()
    }
