"""Automatische Übersetzung der Weboberfläche mit persistentem Cache.

Standardmäßig wird der öffentliche Google-Translate-Endpunkt verwendet. Für
vollständig selbst gehostete Installationen kann stattdessen eine kompatible
LibreTranslate-Instanz über ``UI_TRANSLATOR_URL`` konfiguriert werden.
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

import requests

from runtime_paths import data_dir


SOURCE_LANGUAGE = "de"
SUPPORTED_UI_LANGUAGES = {
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
DEFAULT_UI_LANGUAGE = "de"
TRANSLATION_CACHE_FILE = data_dir() / ".ui_translations.json"
MAX_CACHE_ENTRIES = 10_000


def normalize_ui_language(value: str) -> str:
    """Normalisiert BCP-47-Werte wie ``en-US`` auf einen unterstützten Code."""
    code = str(value or "").strip().replace("_", "-").casefold()
    if code in SUPPORTED_UI_LANGUAGES:
        return code
    base = code.split("-", 1)[0]
    return base if base in SUPPORTED_UI_LANGUAGES else DEFAULT_UI_LANGUAGE


class UITranslator:
    def __init__(
        self,
        cache_path: Path = TRANSLATION_CACHE_FILE,
        endpoint: str = "",
        api_key: str = "",
    ):
        self.cache_path = Path(cache_path)
        self.endpoint = (
            endpoint or os.environ.get("UI_TRANSLATOR_URL", "")
        ).strip().rstrip("/")
        self.api_key = (
            api_key or os.environ.get("UI_TRANSLATOR_API_KEY", "")
        ).strip()
        self._lock = threading.RLock()
        self._cache = self._load_cache()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "RoyalDownloader/1.0 UI-Translator",
        })

    @property
    def engine(self) -> str:
        return "libretranslate" if self.endpoint else "google"

    def translate_many(self, texts: Iterable[str], target_language: str) -> list[str]:
        target = normalize_ui_language(target_language)
        values = [str(text or "") for text in texts]
        if target == SOURCE_LANGUAGE:
            return values

        unique = list(dict.fromkeys(text for text in values if text.strip()))
        translations: dict[str, str] = {}
        missing: list[str] = []
        with self._lock:
            language_cache = self._cache.setdefault(target, {})
            for text in unique:
                cached = language_cache.get(text)
                if isinstance(cached, str) and cached.strip():
                    translations[text] = cached
                else:
                    missing.append(text)

        if missing:
            workers = min(6, len(missing))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(self._translate_one, text, target): text
                    for text in missing
                }
                for future in as_completed(futures):
                    source = futures[future]
                    try:
                        translated = str(future.result() or "").strip()
                    except Exception:
                        translated = ""
                    translations[source] = translated or source

            successful = {
                source: translated
                for source, translated in translations.items()
                if source in missing and translated and translated != source
            }
            if successful:
                with self._lock:
                    self._cache.setdefault(target, {}).update(successful)
                    self._trim_cache()
                    self._save_cache()

        return [translations.get(text, text) for text in values]

    def _translate_one(self, text: str, target: str) -> str:
        if self.endpoint:
            return self._translate_libre(text, target)
        return self._translate_google(text, target)

    def _translate_google(self, text: str, target: str) -> str:
        response = self._session.get(
            "https://translate.googleapis.com/translate_a/single",
            params={
                "client": "gtx",
                "sl": SOURCE_LANGUAGE,
                "tl": target,
                "dt": "t",
                "q": text,
            },
            timeout=(5, 20),
        )
        response.raise_for_status()
        data = response.json()
        segments = data[0] if isinstance(data, list) and data else []
        return "".join(
            str(segment[0])
            for segment in segments
            if isinstance(segment, list) and segment and segment[0]
        ).strip()

    def _translate_libre(self, text: str, target: str) -> str:
        payload = {
            "q": text,
            "source": SOURCE_LANGUAGE,
            "target": target,
            "format": "text",
        }
        if self.api_key:
            payload["api_key"] = self.api_key
        endpoint = self.endpoint if self.endpoint.endswith("/translate") else f"{self.endpoint}/translate"
        response = self._session.post(
            endpoint,
            json=payload,
            timeout=(5, 25),
        )
        response.raise_for_status()
        data = response.json()
        return str(data.get("translatedText") or "").strip()

    def _load_cache(self) -> dict[str, dict[str, str]]:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return {}
        if not isinstance(data, dict):
            return {}
        cleaned: dict[str, dict[str, str]] = {}
        for language, entries in data.items():
            code = normalize_ui_language(language)
            if code == SOURCE_LANGUAGE or not isinstance(entries, dict):
                continue
            cleaned[code] = {
                str(source): str(translated)
                for source, translated in entries.items()
                if str(source).strip() and str(translated).strip()
            }
        return cleaned

    def _trim_cache(self) -> None:
        total = sum(len(entries) for entries in self._cache.values())
        if total <= MAX_CACHE_ENTRIES:
            return
        remove_count = total - MAX_CACHE_ENTRIES
        for language in list(self._cache):
            entries = self._cache[language]
            while entries and remove_count > 0:
                entries.pop(next(iter(entries)))
                remove_count -= 1
            if not entries:
                self._cache.pop(language, None)
            if remove_count <= 0:
                break

    def _save_cache(self) -> None:
        temp = self.cache_path.with_name(
            f".{self.cache_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(self._cache, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.cache_path)
        except OSError:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
