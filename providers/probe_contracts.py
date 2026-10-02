"""Capabilities for existing adapters, independent of the server composition."""
from dataclasses import dataclass
from importlib import import_module

from providers.catalog import PROVIDER_CATALOG


ADAPTER_CLASSES = {
    "filmpalast": "FilmpalastScraper", "filmfrei24": "FilmFrei24Scraper",
    "filmo": "FilmoScraper", "einschalten": "EinschaltenScraper",
    "kinox": "KinoxScraper", "kinoger": "KinogerScraper", "huhu": "HuhuScraper",
    "megakino": "MegaKinoScraper", "moflix": "MoflixScraper", "xcine": "XcineScraper",
    "sflix": "SflixScraper", "ridomovies": "RidomoviesScraper",
    "flixitv": "FlixiTVScraper", "kinoking": "KinoKingScraper",
    "serienstream": "SerienstreamScraper", "aniworld": "AniWorldScraper", "mkissa": "MkissaScraper",
}


@dataclass(frozen=True)
class ProbeContract:
    provider: str
    media_types: tuple[str, ...]
    browser_session: bool
    repair_fields: tuple[str, ...]

    def public_dict(self):
        return {"media_types": list(self.media_types), "browser_session": self.browser_session,
                "steps": ["connectivity", "catalog", "search", "detail", "metadata", "hoster_structure", "source_structure"],
                "repair_fields": list(self.repair_fields), "downloads": False,
                "source_resolution": "link_structure_only", "browser_probe": False}


def contract(provider):
    definition = PROVIDER_CATALOG[provider]
    fields = ("domain",)
    if provider == "filmpalast":
        fields += ("catalog_selector", "title_selector", "poster_selector")
    if provider == "megakino":
        fields += ("catalog_json_path",)
    return ProbeContract(provider, definition.media_types, provider in {"filmpalast", "serienstream"}, fields)


def create_adapter(provider):
    adapter = getattr(import_module(f"providers.{provider}"), ADAPTER_CLASSES[provider])
    return adapter(progress_cb=lambda _message: None)
