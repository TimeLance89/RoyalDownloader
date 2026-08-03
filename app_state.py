"""Application-owned mutable runtime state and lock ownership."""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from pathlib import Path

import config as appconfig
from downloader import DownloadQueue
from extractor import VOEBrowserPool
from hoster_intel import HosterIntel
from provider_health import ProviderHealth
from providers.filmpalast import FilmpalastScraper
from providers.huhu import HuhuScraper
from providers.mkissa import MkissaScraper
from providers.models import FilmpalastMovie, FilmpalastSeries
from providers.moflix import MoflixScraper
from providers.serienstream import SerienstreamScraper
from resolved_link_cache import ResolvedLinkCache
from runtime_cache import BoundedTTLCache
from runtime_paths import data_dir
from taste_profile import TasteProfileStore
from tmdb_client import TMDBClient

logger = logging.getLogger(__name__)

class _PreparationSlots:
    """Begrenzt teure Vorbereitungen, ohne sie global zu serialisieren.

    Provider- und Browseradapter besitzen weiterhin ihre eigenen Locks. Zwei
    Slots erlauben aber, dass eine langsame Katalogsuche einer Serie nicht alle
    anderen Serien hinter sich festhaelt. ``locked`` bedeutet hier bewusst
    "mindestens ein Slot aktiv" und erhaelt damit die bestehende Busy-Pruefung.
    """

    def __init__(self, limit: int):
        self._limit = max(1, int(limit))
        self._semaphore = threading.BoundedSemaphore(self._limit)
        self._state_lock = threading.Lock()
        self._active = 0

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if not blocking:
            acquired = self._semaphore.acquire(blocking=False)
        elif timeout is None or timeout < 0:
            acquired = self._semaphore.acquire()
        else:
            acquired = self._semaphore.acquire(timeout=timeout)
        if acquired:
            with self._state_lock:
                self._active += 1
        return acquired

    def release(self) -> None:
        with self._state_lock:
            if self._active <= 0:
                raise RuntimeError("Vorbereitungs-Slot wurde zu oft freigegeben")
            self._active -= 1
        self._semaphore.release()

    def locked(self) -> bool:
        with self._state_lock:
            return self._active > 0

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.release()
        return False


class AppState:
    def __init__(self):
        self.save_path: str = appconfig.load()              # Zielordner Filme
        self.series_path: str = appconfig.load_series_path()  # Zielordner Serien (getrennt)
        self.ui_language: str = appconfig.load_ui_language()
        self.ui_language_lock = threading.RLock()
        # Der Setup-Abschluss enthält absichtlich langsame Prüfungen. Ein
        # nicht-blockierender Prozess-Lock verhindert, dass zwei Requests
        # gleichzeitig dasselbe erste Administratorkonto beanspruchen.
        self.setup_completion_lock = threading.Lock()
        self.watchlist: list[dict] = appconfig.load_watchlist()
        self.watchlist_lock = threading.RLock()
        self.movie_subscriptions: list[dict] = appconfig.load_movie_subscriptions()
        self.movie_subscriptions_lock = threading.RLock()
        self.persistence_status_lock = threading.RLock()
        self.persistence_write_locks = {
            "queue": threading.RLock(),
            "watchlist": threading.RLock(),
            "movie_subscriptions": threading.RLock(),
        }
        self.persistence_pending: dict[str, dict] = {}
        self.persistence_errors: dict[str, dict] = {}
        self.persistence_generations: dict[str, int] = {}
        self.persistence_retrying: set[str] = set()
        self.movie_subscription_check_lock = threading.Lock()
        self.auto_download_lock = threading.Lock()
        self.hoster_intel = HosterIntel()
        self.taste_profile = TasteProfileStore(appconfig.taste_profile_file())

        self.jellyfin_cfg: dict = appconfig.load_jellyfin()
        self.tmdb_cfg: dict = appconfig.load_tmdb()
        self.tmdb_client = TMDBClient(**self.tmdb_cfg)
        self.telegram_cfg: dict = appconfig.load_telegram()
        self.seerr_cfg: dict = appconfig.load_seerr()
        self.seerr_requests: dict[str, dict] = appconfig.load_seerr_requests()
        self.seerr_requests_lock = threading.RLock()
        self.seerr_jobs: dict[str, list[dict]] = {}
        self.seerr_jobs_lock = threading.RLock()
        self.seerr_poll_lock = threading.Lock()
        self.seerr_last_poll: float = 0.0
        self.seerr_last_success: float = 0.0
        self.seerr_last_error: str = ""
        self.seerr_last_scan_retry: float = 0.0
        self.seerr_scan_retry_lock = threading.Lock()
        self.seerr_moonfin_configured: bool = False
        self.seerr_moonfin_error: str = ""
        # Automatik (24/7): Auto-Download abonnierter Serien + Zeitsteuerung.
        self.automation: dict = appconfig.load_automation()
        self.updater_cfg: dict = appconfig.load_updater()
        self.updater_config_lock = threading.RLock()
        self.updater_runtime_lock = threading.RLock()
        self.updater_runtime: dict = {
            "last_auto_check": None,
            "auto_update_state": "idle",
            "auto_update_message": "",
        }
        self.provider_priorities: dict = appconfig.load_provider_priorities()
        self.provider_enabled: dict = appconfig.load_provider_enabled()
        self.content_languages: set[str] = set(appconfig.load_content_languages())
        self.provider_priority_lock = threading.RLock()
        self.provider_health = ProviderHealth(
            data_dir() / "provider_health.json",
            initial_cooldown=appconfig.SERIES_PROVIDER_COOLDOWN_INITIAL_SECONDS,
            maximum_cooldown=appconfig.SERIES_PROVIDER_COOLDOWN_MAX_SECONDS,
            multiplier=appconfig.SERIES_PROVIDER_COOLDOWN_MULTIPLIER,
        )
        self.resolved_link_cache = ResolvedLinkCache(
            data_dir() / "resolved_provider_links.json",
            ttl_seconds=appconfig.SERIES_RESOLVED_LINK_CACHE_TTL_SECONDS,
            max_entries=appconfig.SERIES_RESOLVED_LINK_CACHE_MAX_ENTRIES,
        )
        self.jellyfin_library: list[dict] | None = None
        self.jellyfin_library_time: float = 0.0
        self.jellyfin_library_available: bool = False
        self.jellyfin_library_retry_after: float = 0.0
        self.jellyfin_movie_identities: list[dict] | None = None
        self.jellyfin_movie_identities_time: float = 0.0
        self.jellyfin_movie_identities_available: bool = False
        self.jellyfin_movie_identities_retry_after: float = 0.0
        self.jellyfin_episodes: list[dict] | None = None
        self.jellyfin_episodes_time: float = 0.0
        self.jellyfin_episodes_available: bool = False
        self.jellyfin_episodes_retry_after: float = 0.0
        self.jellyfin_series: list[dict] | None = None
        self.jellyfin_series_time: float = 0.0
        self.jellyfin_series_available: bool = False
        self.jellyfin_series_retry_after: float = 0.0
        # Kleine, serienbezogene Episoden-Caches für die Detailansicht. Diese
        # laufen unabhängig vom großen Watchlist-Gesamtindex und blockieren
        # daher nicht hinter einer vollständigen Bibliotheksabfrage.
        self.jellyfin_targeted_episodes = BoundedTTLCache[str, dict](
            "jellyfin_targeted_episodes", max_entries=256, ttl_seconds=6 * 60 * 60,
        )
        self.jellyfin_user_episodes: list[dict] | None = None
        self.jellyfin_user_episodes_time: float = 0.0
        self.jellyfin_user_episodes_available: bool = False
        self.jellyfin_user_episodes_retry_after: float = 0.0
        self.jellyfin_config_generation: int = 0
        self.jellyfin_movie_data_generation: int = 0
        self.jellyfin_episode_data_generation: int = 0
        self.jellyfin_cache_lock = threading.RLock()
        self.jellyfin_config_update_lock = threading.Lock()
        self.jellyfin_library_fetch_lock = threading.Lock()
        self.jellyfin_movie_identities_fetch_lock = threading.Lock()
        self.jellyfin_episodes_fetch_lock = threading.Lock()
        self.jellyfin_series_fetch_lock = threading.Lock()
        self.jellyfin_targeted_fetch_lock = threading.Lock()
        self.jellyfin_user_fetch_lock = threading.Lock()
        self.jellyfin_refresh_lock = threading.Lock()
        self.jellyfin_refresh_request_lock = threading.Lock()
        self.jellyfin_refresh_running = False
        self.jellyfin_refresh_pending = False

        def active_movie_slug(slug) -> bool:
            key = str(slug)
            if key in getattr(self, "picked", set()):
                return True
            return any(
                key in {
                    str(entry.get("source_slug") or ""),
                    str(entry.get("pending_slug") or ""),
                }
                for entry in getattr(self, "movie_subscriptions", [])
            )

        def active_series_slug(slug) -> bool:
            key = str(slug)
            return any(
                key == str(entry.get("base_slug") or "")
                for entry in getattr(self, "watchlist", [])
            )

        self.fp_movies = BoundedTTLCache[str, FilmpalastMovie](
            "fp_movies", max_entries=1024, ttl_seconds=6 * 60 * 60,
            is_pinned=active_movie_slug,
        )
        # Virtuelle ``tmdb:<id>``-Treffer bündeln alle tatsächlich gefundenen
        # Anbieterquellen in Nutzerpriorität. Index 0 ist die Primärquelle,
        # alle weiteren Einträge sind Download-Fallbacks.
        self.movie_source_cache = BoundedTTLCache[str, list[FilmpalastMovie]](
            "movie_source_cache", max_entries=512, ttl_seconds=2 * 60 * 60,
            is_pinned=active_movie_slug,
        )
        self.movie_source_cache_lock = threading.RLock()
        self.movie_list_cache: dict[tuple, tuple] = {}
        self.movie_list_cache_lock = threading.Lock()
        self.series_list_cache: dict[tuple, tuple] = {}
        self.series_list_cache_lock = threading.Lock()
        self.series_catalog_lock = threading.Lock()
        queue_document, queue_migrated = appconfig.load_queue_state()
        self.queue_jobs: "OrderedDict[str, dict]" = OrderedDict(
            (job["job_id"], job) for job in queue_document["jobs"]
        )
        self.queue_job_by_slug: dict[str, str] = {
            job["slug"]: job["job_id"] for job in self.queue_jobs.values()
        }
        self.queue_history: list[dict] = list(queue_document["history"])
        self.queue_persistence_revision = int(queue_document.get("revision") or 0)
        self.queue_job_persist_times: dict[str, float] = {}
        self.picked: set = set(self.queue_job_by_slug)
        self.queue_content_keys: dict[str, str] = {}
        self.done_slugs: set = set()
        self.queue_claim_lock = threading.RLock()
        if queue_migrated and not appconfig.save_queue_state(queue_document):
            logger.error(
                "Die alte Download-Queue konnte nicht in das Job-Format migriert werden."
            )

        self.fp_scraper: FilmpalastScraper | None = None
        self.fp_lock = threading.Lock()
        # Hoster-Auflösung nutzt gemeinsame Browser-/Session-Objekte und muss
        # auch bei parallelen Download-Fallbacks seriell bleiben.
        self.hoster_extract_lock = threading.Lock()

        # serienstream.to – eigener Singleton, damit SessionManager (Cookies /
        # Rate-Limiting) über alle Aufrufe erhalten bleibt.
        self.sto_scraper: SerienstreamScraper | None = None
        self.sto_lock = threading.Lock()
        self.moflix_scraper: MoflixScraper | None = None
        self.moflix_lock = threading.RLock()
        self.huhu_scraper: HuhuScraper | None = None
        self.huhu_lock = threading.RLock()
        self.mkissa_scraper: MkissaScraper | None = None
        self.mkissa_lock = threading.RLock()

        self.fp_provider_genres: set = set()
        self.filmfrei24_provider_genres: set = set()
        self.moflix_provider_genres: set = set()
        self.huhu_provider_genres: set = set()
        self.einschalten_provider_genres: set = set()
        self.kinox_provider_genres: set = set()
        self.kinoger_provider_genres: set = set()
        self.megakino_provider_genres: set = set()
        self.xcine_provider_genres: set = set()
        self.sflix_provider_genres: set = set()
        self.ridomovies_provider_genres: set = set()

        self.series_cache = BoundedTTLCache[str, FilmpalastSeries](
            "series_cache", max_entries=512, ttl_seconds=6 * 60 * 60,
            is_pinned=active_series_slug,
        )
        self.series_dir_cache = BoundedTTLCache[tuple, Path](
            "series_dir_cache", max_entries=1024, ttl_seconds=60 * 60,
        )
        self.media_validation_cache = BoundedTTLCache[str, tuple](
            "media_validation_cache", max_entries=2048, ttl_seconds=30 * 60,
        )
        self.media_validation_lock = threading.Lock()
        self.series_page_size_ref: int = 1

        # Provider/Serie-Strukturen werden laufübergreifend mit TTL wiederverwendet.
        # Netzwerk-/Cloudflare-Fehler werden bewusst nicht negativ gecacht.
        self.fallback_series_cache: dict[str, tuple[float, FilmpalastSeries | None]] = {}
        self.fallback_series_cache_lock = threading.RLock()
        self.fallback_provider_errors: dict[str, tuple[float, str]] = {}

        self.watchlist_new_slugs: dict[str, set] = {}

        self.voe_pool: VOEBrowserPool | None = None
        self.embed_pool: VOEBrowserPool | None = None

        # Zwei echte Downloads plus zwei separat begrenzte Vorbereitungen. Die
        # Vorbereitung belegt keinen Download-Slot; provider-spezifische Locks
        # verhindern weiterhin paralleles Hämmern derselben Quelle.
        self.dl_queue = DownloadQueue(max_parallel=2, max_preparations=2)
        self.download_state_lock = threading.Lock()
        self.queue_prepare_lock = _PreparationSlots(2)
        self.queue_lifecycle_lock = threading.RLock()
        self.total_jobs = 0
        self.done_jobs = 0
        self.counted_queue_slugs: set[str] = set()
        # Nur die Slugs, deren Katalog-/Hoster-Vorbereitung gerade wirklich
        # läuft. Die UI darf nicht die komplette Staffel als gleichzeitig
        # geprüft darstellen.
        self.preparing_queue_slugs: set[str] = set()
        # Logische Queue-Jobs, die auf den persistenten Provider-Circuit-Breaker
        # warten. Sie bleiben in ``picked`` und werden nicht terminal gezählt.
        self.provider_waiting_jobs: dict[str, dict] = {}
        self.provider_retry_worker_running = False
        self.provider_retry_wake_event = threading.Event()
        self.ytdlp_update_active = False

        self.cover_cache: OrderedDict[str, tuple] = OrderedDict()
        # Fehlschläge nur kurz merken (Timestamp), damit transiente Fehler
        # nicht bis zum Neustart als 502 hängen bleiben.
        self.cover_fail_cache: OrderedDict[str, float] = OrderedDict()
        self.cover_cache_lock = threading.Lock()

        # Telegram-Anfragen werden über den Film-Slug bis zum Download-Ende
        # verfolgt, damit anschließend auf die Jellyfin-Erkennung gewartet wird.
        self.telegram_jobs: dict[str, dict] = {}
        self.telegram_series_requests: dict[str, dict] = {}
        self.telegram_series_choices: dict[str, dict] = {}
        self.telegram_jobs_lock = threading.Lock()
        self.telegram_choices_lock = threading.Lock()
        self.telegram_choices_publish_lock = threading.Lock()
        self.telegram_request_lock = threading.Lock()

        self.runtime_caches = (
            self.fp_movies,
            self.movie_source_cache,
            self.series_cache,
            self.series_dir_cache,
            self.media_validation_cache,
            self.jellyfin_targeted_episodes,
        )

    def maintain_runtime_caches(self) -> None:
        for cache in self.runtime_caches:
            result = cache.cleanup()
            removed = result["expired"] + result["evicted"]
            if removed:
                logger.info(
                    "Runtime-Cache %s: %d Einträge bereinigt (Größe %d/%d)",
                    cache.name, removed, len(cache), cache.max_entries,
                )

    def runtime_cache_diagnostics(self) -> list[dict]:
        return [cache.diagnostics() for cache in self.runtime_caches]
