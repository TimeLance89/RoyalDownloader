"""Content-basierte Jellyfin-Empfehlungen aus dem eigenen Wiedergabeverlauf.

Das Script läuft einmalig (RUN_INTERVAL_SECONDS=0) oder dauerhaft in einem
einfachen Intervall. Es benötigt außer Python nur ``requests``.
"""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import signal
import sys
import tempfile
import threading
import unicodedata
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import quote, urlsplit

import requests


LOGGER = logging.getLogger("jellyfin_recommender")

ITEM_FIELDS = "Genres,Tags,Studios,People"
MEDIA_TYPES = "Movie,Series"
ACTOR_LIMIT = 5
BATCH_SIZE = 50

CATEGORY_WEIGHTS = {
    "genres": 0.35,
    "tags": 0.20,
    "studios": 0.10,
    "directors": 0.20,
    "actors": 0.15,
}

CATEGORY_LABELS = {
    "genres": "Genres",
    "tags": "Tags",
    "studios": "Studios",
    "directors": "Regie",
    "actors": "Darsteller",
}


class RecommenderError(RuntimeError):
    """Fehler, bei dem die bestehende Collection unverändert bleiben soll."""


class ConfigurationError(RecommenderError):
    """Ungültige oder fehlende Umgebungsvariable."""


def _env_int(
    environ: Mapping[str, str], name: str, default: int, minimum: int,
) -> int:
    raw = str(environ.get(name, default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} muss eine ganze Zahl sein") from exc
    if value < minimum:
        raise ConfigurationError(f"{name} muss mindestens {minimum} sein")
    return value


def _env_float(
    environ: Mapping[str, str], name: str, default: float, minimum: float,
) -> float:
    raw = str(environ.get(name, default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} muss eine Zahl sein") from exc
    if not math.isfinite(value) or value < minimum:
        raise ConfigurationError(f"{name} muss mindestens {minimum:g} sein")
    return value


@dataclass(frozen=True)
class Config:
    jellyfin_url: str
    api_key: str
    user_id: str
    collection_name: str = "Für dich empfohlen"
    top_n: int = 20
    request_timeout: float = 120.0
    page_size: int = 100
    recency_half_life_days: float = 180.0
    run_interval_seconds: int = 0
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Config":
        env = os.environ if environ is None else environ
        url = str(env.get("JELLYFIN_URL", "")).strip().rstrip("/")
        api_key = str(env.get("JELLYFIN_API_KEY", "")).strip()
        user_id = str(env.get("JELLYFIN_USER_ID", "")).strip()
        collection_name = str(
            env.get("COLLECTION_NAME", "Für dich empfohlen")
        ).strip()

        missing = [
            name
            for name, value in (
                ("JELLYFIN_URL", url),
                ("JELLYFIN_API_KEY", api_key),
                ("JELLYFIN_USER_ID", user_id),
                ("COLLECTION_NAME", collection_name),
            )
            if not value
        ]
        if missing:
            raise ConfigurationError(f"Fehlende Konfiguration: {', '.join(missing)}")

        parsed_url = urlsplit(url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ConfigurationError("JELLYFIN_URL muss eine vollständige HTTP(S)-URL sein")

        log_level = str(env.get("LOG_LEVEL", "INFO")).strip().upper()
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError("LOG_LEVEL ist ungültig")

        return cls(
            jellyfin_url=url,
            api_key=api_key,
            user_id=user_id,
            collection_name=collection_name,
            top_n=_env_int(env, "TOP_N", 20, 1),
            request_timeout=_env_float(env, "REQUEST_TIMEOUT_SECONDS", 120.0, 0.1),
            # People + UserData machen /Items deutlich schwerer als die normale
            # Bibliotheksanzeige. Große Altwerte werden deshalb sicher begrenzt.
            page_size=min(_env_int(env, "PAGE_SIZE", 100, 1), 100),
            recency_half_life_days=_env_float(
                env, "RECENCY_HALF_LIFE_DAYS", 180.0, 0.0,
            ),
            run_interval_seconds=_env_int(env, "RUN_INTERVAL_SECONDS", 0, 0),
            log_level=log_level,
        )


@dataclass(frozen=True)
class Recommendation:
    item: dict[str, Any]
    score: float
    content_score: float
    rating_bonus: float
    matches: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class SyncResult:
    added: int
    removed: int
    unchanged: int


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.split()).casefold()


def _unique_text(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_text(value)
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _named_values(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    names = []
    for value in values:
        if isinstance(value, Mapping):
            names.append(value.get("Name", ""))
        else:
            names.append(value)
    return _unique_text(names)


def item_attributes(item: Mapping[str, Any]) -> dict[str, list[str]]:
    people = item.get("People")
    people = people if isinstance(people, list) else []

    directors = _unique_text(
        person.get("Name", "")
        for person in people
        if isinstance(person, Mapping)
        and normalize_text(person.get("Type")) == "director"
    )
    actors = _unique_text(
        person.get("Name", "")
        for person in people
        if isinstance(person, Mapping)
        and normalize_text(person.get("Type")) == "actor"
    )[:ACTOR_LIMIT]

    genres = item.get("Genres")
    tags = item.get("Tags")
    return {
        "genres": _unique_text(genres if isinstance(genres, list) else []),
        "tags": _unique_text(tags if isinstance(tags, list) else []),
        "studios": _named_values(item.get("Studios")),
        "directors": directors,
        "actors": actors,
    }


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def is_watched(item: Mapping[str, Any]) -> bool:
    user_data = item.get("UserData")
    if not isinstance(user_data, Mapping):
        return False
    play_count = _finite_float(user_data.get("PlayCount")) or 0.0
    return user_data.get("Played") is True or play_count > 0


def split_watched(
    items: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    watched: list[dict[str, Any]] = []
    unseen: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in items:
        item_id = str(item.get("Id") or "").strip()
        if not item_id or item_id in seen_ids:
            continue
        seen_ids.add(item_id)
        (watched if is_watched(item) else unseen).append(item)
    return watched, unseen


def watched_item_weight(
    item: Mapping[str, Any], now: datetime, recency_half_life_days: float,
) -> float:
    user_data = item.get("UserData")
    user_data = user_data if isinstance(user_data, Mapping) else {}
    weight = 1.0

    if user_data.get("IsFavorite") is True:
        weight += 1.0

    rating = _finite_float(user_data.get("Rating"))
    if rating is not None:
        weight += min(1.0, max(0.0, (rating - 5.0) / 5.0))

    if recency_half_life_days > 0:
        last_played = _parse_datetime(user_data.get("LastPlayedDate"))
        if last_played is not None:
            age_days = max(0.0, (now - last_played).total_seconds() / 86400.0)
            weight += 0.5 * (2.0 ** (-age_days / recency_half_life_days))

    return weight


def build_profile(
    watched: Iterable[Mapping[str, Any]],
    recency_half_life_days: float = 180.0,
    now: datetime | None = None,
) -> dict[str, dict[str, float]]:
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)

    raw: dict[str, Counter[str]] = {
        category: Counter() for category in CATEGORY_WEIGHTS
    }
    for item in watched:
        weight = watched_item_weight(item, current_time, recency_half_life_days)
        for category, values in item_attributes(item).items():
            if not values:
                continue
            contribution = weight / len(values)
            for value in values:
                raw[category][value] += contribution

    return {
        category: {
            value: math.log1p(weight)
            for value, weight in counter.items()
            if weight > 0
        }
        for category, counter in raw.items()
    }


def score_item(
    item: dict[str, Any],
    profile: Mapping[str, Mapping[str, float]],
    profile_norms: Mapping[str, float] | None = None,
) -> Recommendation:
    attributes = item_attributes(item)
    weighted_similarity = 0.0
    active_weight = 0.0
    matches: dict[str, tuple[str, ...]] = {}

    for category, category_weight in CATEGORY_WEIGHTS.items():
        category_profile = profile.get(category) or {}
        if not category_profile:
            continue
        active_weight += category_weight
        values = attributes.get(category) or []
        if not values:
            continue

        matched = tuple(value for value in values if value in category_profile)
        if matched:
            matches[category] = matched
        dot_product = sum(category_profile.get(value, 0.0) for value in values)
        profile_norm = (
            profile_norms.get(category, 0.0)
            if profile_norms is not None
            else math.sqrt(sum(value * value for value in category_profile.values()))
        )
        candidate_norm = math.sqrt(len(values))
        if profile_norm and candidate_norm:
            weighted_similarity += category_weight * (
                dot_product / (profile_norm * candidate_norm)
            )

    content_score = weighted_similarity / active_weight if active_weight else 0.0
    community_rating = _finite_float(item.get("CommunityRating")) or 0.0
    rating_bonus = 0.05 * min(1.0, max(0.0, (community_rating - 5.0) / 5.0))
    return Recommendation(
        item=item,
        score=content_score + rating_bonus,
        content_score=content_score,
        rating_bonus=rating_bonus,
        matches=matches,
    )


def rank_recommendations(
    unseen: Iterable[dict[str, Any]],
    profile: Mapping[str, Mapping[str, float]],
    top_n: int,
) -> list[Recommendation]:
    scored: list[Recommendation] = []
    profile_norms = {
        category: math.sqrt(sum(value * value for value in values.values()))
        for category, values in profile.items()
    }
    for item in unseen:
        recommendation = score_item(item, profile, profile_norms)
        matches = ", ".join(
            f"{CATEGORY_LABELS[category]}={'+'.join(values)}"
            for category, values in recommendation.matches.items()
        ) or "keine"
        LOGGER.info(
            "Bewertet: %s (%s, %s) | Inhalt=%.4f Bonus=%.4f Gesamt=%.4f | %s",
            item.get("Name") or item.get("Id"),
            item.get("Type") or "?",
            item.get("ProductionYear") or "?",
            recommendation.content_score,
            recommendation.rating_bonus,
            recommendation.score,
            matches,
        )
        scored.append(recommendation)

    def sort_key(recommendation: Recommendation) -> tuple[Any, ...]:
        item = recommendation.item
        rating = _finite_float(item.get("CommunityRating")) or 0.0
        year = _finite_float(item.get("ProductionYear")) or 0.0
        return (
            -recommendation.score,
            -recommendation.content_score,
            -rating,
            -year,
            normalize_text(item.get("Name")),
            str(item.get("Id") or ""),
        )

    return sorted(scored, key=sort_key)[:top_n]


class JellyfinAPI:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 120.0,
        page_size: int = 100,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.page_size = page_size
        self.session = session or requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Authorization": f'MediaBrowser Token="{api_key}"',
            "User-Agent": "Jellyfin-Content-Recommender/1.0",
        })

    def _request(
        self,
        method: str,
        path: str,
        params: Mapping[str, Any] | None = None,
        data: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        allowed_statuses: Sequence[int] = (),
    ) -> requests.Response:
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                params=params,
                data=data,
                headers=headers,
                timeout=(min(10.0, self.timeout), self.timeout),
            )
            if getattr(response, "status_code", 200) not in allowed_statuses:
                response.raise_for_status()
            return response
        except requests.RequestException as exc:
            raise RecommenderError(
                f"Jellyfin {method} {path} fehlgeschlagen: {exc}"
            ) from exc

    @staticmethod
    def _response_json(response: requests.Response, label: str) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise RecommenderError(f"{label} lieferte kein gültiges JSON") from exc
        if not isinstance(payload, Mapping):
            raise RecommenderError(f"{label} lieferte ein ungültiges JSON-Objekt")
        return payload

    def query_items(self, params: Mapping[str, Any]) -> list[dict[str, Any]]:
        start_index = 0
        result: list[dict[str, Any]] = []
        while True:
            page_params = dict(params)
            page_params.update({
                "startIndex": start_index,
                "limit": self.page_size,
                "enableTotalRecordCount": "true",
            })
            page_params.setdefault("sortBy", "SortName")
            page_params.setdefault("sortOrder", "Ascending")
            response = self._request("GET", "/Items", page_params)
            payload = self._response_json(response, "GET /Items")
            page = payload.get("Items")
            if not isinstance(page, list) or not all(isinstance(item, dict) for item in page):
                raise RecommenderError("GET /Items lieferte ungültige Items")

            result.extend(page)
            start_index += len(page)
            total_value = payload.get("TotalRecordCount")
            try:
                total = int(total_value) if total_value is not None else None
            except (TypeError, ValueError) as exc:
                raise RecommenderError("GET /Items lieferte einen ungültigen Gesamtwert") from exc

            if total is not None and start_index >= total:
                break
            if not page:
                if total is not None and start_index < total:
                    raise RecommenderError("GET /Items endete vorzeitig; Collection bleibt unverändert")
                break
            if total is None and len(page) < self.page_size:
                break
        return result

    def list_media_items(self, user_id: str) -> list[dict[str, Any]]:
        # CommunityRating und ProductionYear sind Basisfelder; UserData wird
        # über userId + enableUserData geliefert und gehört nicht in fields.
        return self.query_items({
            "userId": user_id,
            "recursive": "true",
            "includeItemTypes": MEDIA_TYPES,
            "fields": ITEM_FIELDS,
            "enableUserData": "true",
            "collapseBoxSetItems": "false",
            "enableImages": "false",
        })

    def list_collections(self, user_id: str) -> list[dict[str, Any]]:
        return self.query_items({
            "userId": user_id,
            "recursive": "true",
            "includeItemTypes": "BoxSet",
            "enableImages": "false",
        })

    def find_collection(self, user_id: str, name: str) -> dict[str, Any] | None:
        wanted = normalize_text(name)
        matches = [
            item
            for item in self.list_collections(user_id)
            if normalize_text(item.get("Name")) == wanted
        ]
        if len(matches) > 1:
            ids = ", ".join(str(item.get("Id") or "?") for item in matches)
            raise RecommenderError(
                f"Mehrere Collections heißen {name!r} ({ids}); keine Änderung"
            )
        return matches[0] if matches else None

    def create_collection(self, name: str) -> str:
        response = self._request(
            "POST", "/Collections", {"name": name, "isLocked": "false"},
        )
        payload = self._response_json(response, "POST /Collections")
        collection_id = str(payload.get("Id") or payload.get("id") or "").strip()
        if not collection_id:
            raise RecommenderError("Jellyfin lieferte keine ID für die neue Collection")
        return collection_id

    def get_or_create_collection(self, user_id: str, name: str) -> tuple[str, bool]:
        existing = self.find_collection(user_id, name)
        if existing:
            collection_id = str(existing.get("Id") or "").strip()
            if not collection_id:
                raise RecommenderError("Bestehende Collection hat keine ID")
            return collection_id, False
        return self.create_collection(name), True

    @staticmethod
    def _moonfin_home_row_order(value: Any) -> list[str]:
        order: list[str] = []
        if isinstance(value, list):
            for entry in value:
                name = str(entry or "").strip()
                if name and name != "collections" and name not in order:
                    order.append(name)
        if not order:
            order = ["smalllibrarytiles", "resume", "nextup", "latestmedia"]
        insert_at = order.index("resume") + 1 if "resume" in order else min(2, len(order))
        order.insert(insert_at, "collections")
        return order

    def _moonfin_home_sections(
        self,
        value: Any,
        collection_id: str,
        collection_name: str,
    ) -> list[dict[str, Any]]:
        sections: list[dict[str, Any]] = []
        if isinstance(value, list):
            for entry in value:
                if not isinstance(entry, Mapping):
                    continue
                section = dict(entry)
                is_target = (
                    section.get("pluginSource") == "collections"
                    and str(section.get("pluginAdditionalData") or "") == collection_id
                )
                if not is_target:
                    sections.append(section)
        if not sections:
            sections = [
                {"kind": "builtin", "type": "smalllibrarytiles", "enabled": True},
                {"kind": "builtin", "type": "resume", "enabled": True},
                {"kind": "builtin", "type": "nextup", "enabled": True},
                {"kind": "builtin", "type": "latestmedia", "enabled": True},
            ]

        recommendation = {
            "kind": "pluginDynamic",
            "type": "none",
            "enabled": True,
            "serverId": self.base_url,
            "pluginSource": "collections",
            "pluginSection": "collection",
            "pluginAdditionalData": collection_id,
            "pluginDisplayText": collection_name,
        }
        resume_index = next(
            (index for index, section in enumerate(sections) if section.get("type") == "resume"),
            None,
        )
        insert_at = resume_index + 1 if resume_index is not None else min(2, len(sections))
        sections.insert(insert_at, recommendation)
        for index, section in enumerate(sections):
            section["order"] = index
        return sections

    def _moonfin_profile(
        self,
        value: Any,
        collection_id: str,
        collection_name: str,
    ) -> dict[str, Any]:
        profile = dict(value) if isinstance(value, Mapping) else {}
        previous_ids = profile.get("mediaBarCollectionIds")
        collection_ids = [collection_id]
        if isinstance(previous_ids, list):
            collection_ids.extend(
                item_id
                for item_id in (str(item or "").strip() for item in previous_ids)
                if item_id and item_id != collection_id
            )
        profile.update({
            "displayCollectionsRows": True,
            "homeRowOrder": self._moonfin_home_row_order(profile.get("homeRowOrder")),
            "homeSections": self._moonfin_home_sections(
                profile.get("homeSections"), collection_id, collection_name,
            ),
            "homeRowsStyle": "v2",
            "mediaBarMode": "moonfin",
            "mediaBarSourceType": "collection",
            "mediaBarCollectionIds": collection_ids,
            "mediaBarItemCount": 10,
            "mediaBarAutoAdvance": True,
            "mediaBarTrailerPreview": True,
            "mediaBarTrailerAudio": False,
            "episodePreviewEnabled": True,
            "previewAudioEnabled": False,
            # Stable Moonfin 2.2.0/Plugin 1.9.1 importiert den historischen
            # Profil-Key auch für den aktuellen Seerr-Bereich auf Fire TV.
            "jellyseerrEnabled": True,
        })
        return profile

    def configure_moonfin_dashboard(
        self,
        user_id: str,
        collection_id: str,
        collection_name: str,
    ) -> bool:
        """Bindet die Empfehlung an Moonfins TV-Startseite und Media Bar."""
        ping = self._request("GET", "/Moonfin/Ping", allowed_statuses=(404,))
        if getattr(ping, "status_code", 200) == 404:
            return False
        ping_payload = self._response_json(ping, "GET /Moonfin/Ping")
        if ping_payload.get("installed") is False:
            return False

        encoded_user_id = quote(str(user_id), safe="")
        settings_response = self._request(
            "GET",
            f"/Moonfin/Settings/{encoded_user_id}",
            allowed_statuses=(404,),
        )
        if getattr(settings_response, "status_code", 200) == 404:
            current: dict[str, Any] = {}
        else:
            current = dict(self._response_json(
                settings_response, "GET /Moonfin/Settings/{userId}",
            ))

        settings = dict(current)
        settings["schemaVersion"] = 2
        settings["syncEnabled"] = True
        settings["global"] = self._moonfin_profile(
            current.get("global"), collection_id, collection_name,
        )
        settings["tv"] = self._moonfin_profile(
            current.get("tv"), collection_id, collection_name,
        )
        payload = {
            "settings": settings,
            "clientId": "jellyfin-content-recommender",
            "mergeMode": "merge",
        }
        self._request(
            "POST",
            f"/Moonfin/Settings/{encoded_user_id}",
            data=json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"),
            ).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )

        saved = self._response_json(
            self._request("GET", f"/Moonfin/Settings/{encoded_user_id}"),
            "GET /Moonfin/Settings/{userId}",
        )
        for profile_name in ("global", "tv"):
            profile = saved.get(profile_name)
            if not isinstance(profile, Mapping):
                raise RecommenderError(f"Moonfin-Profil {profile_name!r} fehlt")
            if profile.get("displayCollectionsRows") is not True:
                raise RecommenderError("Moonfin-Collections wurden nicht aktiviert")
            if collection_id not in (profile.get("mediaBarCollectionIds") or []):
                raise RecommenderError("Moonfin-Media-Bar hat die Collection nicht gespeichert")
            if "collections" not in (profile.get("homeRowOrder") or []):
                raise RecommenderError("Moonfin-Collections-Zeile wurde nicht gespeichert")
        return True

    def list_collection_items(
        self, user_id: str, collection_id: str,
    ) -> list[dict[str, Any]]:
        return self.query_items({
            "userId": user_id,
            "parentId": collection_id,
            "recursive": "false",
            "enableImages": "false",
        })

    def item_has_primary_image(self, item_id: str) -> bool:
        encoded_id = quote(str(item_id), safe="")
        response = self._request("GET", f"/Items/{encoded_id}/Images")
        try:
            payload = response.json()
        except ValueError as exc:
            raise RecommenderError("Jellyfin lieferte ungültige Bildinformationen") from exc
        if not isinstance(payload, list):
            raise RecommenderError("Jellyfin lieferte ungültige Bildinformationen")
        return any(
            isinstance(image, Mapping)
            and normalize_text(image.get("ImageType") or image.get("Type")) == "primary"
            for image in payload
        )

    def ensure_collection_primary_image(
        self, collection_id: str, candidates: Sequence[Mapping[str, Any]],
    ) -> bool:
        """Kopiert einmalig das Poster der besten Empfehlung auf die Collection."""
        try:
            if self.item_has_primary_image(collection_id):
                return False
            for item in candidates:
                item_id = str(item.get("Id") or "").strip()
                if not item_id or not self.item_has_primary_image(item_id):
                    continue
                encoded_source = quote(item_id, safe="")
                source = self._request(
                    "GET",
                    f"/Items/{encoded_source}/Images/Primary",
                    {"maxWidth": 1000, "maxHeight": 1500},
                )
                content = bytes(source.content or b"")
                content_type = str(source.headers.get("Content-Type") or "").split(";", 1)[0]
                if not content or not content_type.startswith("image/"):
                    LOGGER.warning("Poster von %s ist leer oder ungültig", item_id)
                    return False
                encoded_collection = quote(str(collection_id), safe="")
                self._request(
                    "POST",
                    f"/Items/{encoded_collection}/Images/Primary",
                    # Jellyfin liest diesen Body trotz image/*-Content-Type
                    # über FromBase64Transform und erwartet daher Base64.
                    data=base64.b64encode(content),
                    headers={"Content-Type": content_type},
                )
                return True
        except RecommenderError as exc:
            # Das Cover ist optional; ein Fehler darf die aktualisierte
            # Empfehlungsliste nicht wieder als fehlgeschlagen markieren.
            LOGGER.warning("Collection-Cover konnte nicht gesetzt werden: %s", exc)
        return False

    @staticmethod
    def _batches(ids: Sequence[str]) -> Iterable[Sequence[str]]:
        for index in range(0, len(ids), BATCH_SIZE):
            yield ids[index:index + BATCH_SIZE]

    def add_to_collection(self, collection_id: str, ids: Sequence[str]) -> None:
        for batch in self._batches(ids):
            self._request(
                "POST",
                f"/Collections/{quote(collection_id, safe='')}/Items",
                {"ids": ",".join(batch)},
            )

    def remove_from_collection(self, collection_id: str, ids: Sequence[str]) -> None:
        for batch in self._batches(ids):
            self._request(
                "DELETE",
                f"/Collections/{quote(collection_id, safe='')}/Items",
                {"ids": ",".join(batch)},
            )

    def sync_collection(
        self, user_id: str, collection_id: str, desired_ids: Sequence[str],
    ) -> SyncResult:
        ordered_target = list(dict.fromkeys(item_id for item_id in desired_ids if item_id))
        target = set(ordered_target)
        current = {
            str(item.get("Id") or "").strip()
            for item in self.list_collection_items(user_id, collection_id)
            if item.get("Id")
        }

        to_add = [item_id for item_id in ordered_target if item_id not in current]
        if not to_add and current == target:
            return SyncResult(added=0, removed=0, unchanged=len(target))

        if to_add:
            self.add_to_collection(collection_id, to_add)

        after_add = {
            str(item.get("Id") or "").strip()
            for item in self.list_collection_items(user_id, collection_id)
            if item.get("Id")
        }
        missing = target - after_add
        if missing:
            raise RecommenderError(
                f"Hinzufügen nicht bestätigt ({len(missing)} Items); nichts entfernt"
            )

        to_remove = sorted(after_add - target)
        if to_remove:
            self.remove_from_collection(collection_id, to_remove)

        final = {
            str(item.get("Id") or "").strip()
            for item in self.list_collection_items(user_id, collection_id)
            if item.get("Id")
        }
        if final != target:
            raise RecommenderError(
                "Collection-Prüfung fehlgeschlagen; nächster Lauf repariert den Mengen-Diff"
            )
        return SyncResult(
            added=len(to_add),
            removed=len(to_remove),
            unchanged=len(current & target),
        )


def _log_profile(profile: Mapping[str, Mapping[str, float]]) -> None:
    for category in CATEGORY_WEIGHTS:
        values = profile.get(category) or {}
        strongest = sorted(values.items(), key=lambda pair: (-pair[1], pair[0]))[:5]
        LOGGER.info(
            "Profil %s: %s",
            CATEGORY_LABELS[category],
            ", ".join(f"{name}={weight:.2f}" for name, weight in strongest) or "leer",
        )


def run_once(config: Config, api: JellyfinAPI | None = None) -> list[Recommendation]:
    client = api or JellyfinAPI(
        config.jellyfin_url,
        config.api_key,
        config.request_timeout,
        config.page_size,
    )
    items = client.list_media_items(config.user_id)
    watched, unseen = split_watched(items)
    LOGGER.info(
        "Bibliothek: %d Filme/Serien, %d gesehen, %d ungesehen",
        len(watched) + len(unseen),
        len(watched),
        len(unseen),
    )
    if not watched:
        raise RecommenderError("Keine gesehenen Filme/Serien; Collection bleibt unverändert")
    profile = build_profile(watched, config.recency_half_life_days)
    if not any(profile.values()):
        raise RecommenderError("Gesehene Items haben keine Profil-Metadaten")
    _log_profile(profile)

    recommendations = rank_recommendations(unseen, profile, config.top_n)
    LOGGER.info(
        "Auswahl für %r: %d Item(s)", config.collection_name, len(recommendations),
    )
    for rank, recommendation in enumerate(recommendations, start=1):
        item = recommendation.item
        LOGGER.info(
            "%02d. %s (%s, %s) | Score=%.4f",
            rank,
            item.get("Name") or item.get("Id"),
            item.get("Type") or "?",
            item.get("ProductionYear") or "?",
            recommendation.score,
        )

    collection_id, created = client.get_or_create_collection(
        config.user_id, config.collection_name,
    )
    LOGGER.info(
        "Collection %s: %s (%s)",
        "angelegt" if created else "gefunden",
        config.collection_name,
        collection_id,
    )
    sync = client.sync_collection(
        config.user_id,
        collection_id,
        [str(recommendation.item["Id"]) for recommendation in recommendations],
    )
    LOGGER.info(
        "Collection aktualisiert: +%d, -%d, unverändert=%d",
        sync.added,
        sync.removed,
        sync.unchanged,
    )
    if recommendations and client.ensure_collection_primary_image(
        collection_id,
        [recommendation.item for recommendation in recommendations],
    ):
        LOGGER.info("Collection-Cover aus der besten Empfehlung gesetzt")
    configure_moonfin = getattr(client, "configure_moonfin_dashboard", None)
    if callable(configure_moonfin):
        try:
            configured = configure_moonfin(
                config.user_id, collection_id, config.collection_name,
            )
        except RecommenderError as exc:
            LOGGER.warning("Moonfin-Dashboard konnte nicht aktualisiert werden: %s", exc)
        else:
            if configured:
                LOGGER.info("Moonfin-Dashboard und Media Bar aktualisiert")
            else:
                LOGGER.info("Moonfin-Plugin nicht installiert; Dashboard-Sync übersprungen")
    return recommendations


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        stream=sys.stdout,
        force=True,
    )


def mark_successful_run() -> None:
    default_file = Path(tempfile.gettempdir()) / "jellyfin-recommender-last-success"
    health_file = os.environ.get(
        "HEALTH_FILE", str(default_file),
    )
    try:
        Path(health_file).touch()
    except OSError as exc:
        LOGGER.warning("Health-Datei konnte nicht aktualisiert werden: %s", exc)


def main() -> int:
    try:
        config = Config.from_env()
    except ConfigurationError as exc:
        configure_logging("ERROR")
        LOGGER.error("Konfiguration: %s", exc)
        return 2

    configure_logging(config.log_level)
    api = JellyfinAPI(
        config.jellyfin_url,
        config.api_key,
        config.request_timeout,
        config.page_size,
    )

    if config.run_interval_seconds == 0:
        try:
            run_once(config, api)
            mark_successful_run()
        except RecommenderError as exc:
            LOGGER.error("Lauf fehlgeschlagen: %s", exc)
            return 1
        return 0

    stop_event = threading.Event()

    def stop(_signum: int, _frame: Any) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stop_event.is_set():
        try:
            run_once(config, api)
            mark_successful_run()
        except RecommenderError as exc:
            LOGGER.error("Lauf fehlgeschlagen: %s", exc)
        if not stop_event.is_set():
            LOGGER.info("Nächster Lauf in %d Sekunden", config.run_interval_seconds)
            stop_event.wait(config.run_interval_seconds)
    LOGGER.info("Beendet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
