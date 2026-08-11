"""Bounded, stale-aware runtime cache for series provider catalog pages."""
# Runtime dependencies are supplied by the server composition root.
# ruff: noqa: F821

import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from typing import Callable, Dict, List, Optional

from application_services.runtime import import_backend_namespace

globals().update(import_backend_namespace())


_LOAD_POOL = ThreadPoolExecutor(max_workers=16, thread_name_prefix="series-catalog")
_INFLIGHT = {}
_INFLIGHT_LOCK = threading.Lock()
_PREFETCH_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="series-prefetch")
_PREFETCH_INFLIGHT = set()
_PREFETCH_LOCK = threading.Lock()


def cache_state(cache_key: tuple) -> tuple[Optional[list], str]:
    with state.series_list_cache_lock:
        cached = state.series_list_cache.get(cache_key)
        ttl = cached[2] if cached and len(cached) > 2 else SERIES_LIST_CACHE_TTL
        age = time.time() - cached[0] if cached else 0.0
        if cached and age < ttl:
            return list(cached[1]), "fresh"
        if cached and age < SERIES_LIST_STALE_TTL:
            return list(cached[1]), "stale"
        if cached:
            state.series_list_cache.pop(cache_key, None)
    return None, "missing"


def cached_page(cache_key: tuple) -> Optional[list]:
    results, freshness = cache_state(cache_key)
    return results if freshness == "fresh" else None


def cache_page(cache_key: tuple, results: list, ttl: int = SERIES_LIST_CACHE_TTL) -> None:
    now = time.time()
    with state.series_list_cache_lock:
        expired = [
            key for key, cached in state.series_list_cache.items()
            if now - cached[0] >= SERIES_LIST_STALE_TTL
        ]
        for key in expired:
            state.series_list_cache.pop(key, None)
        while len(state.series_list_cache) >= SERIES_LIST_CACHE_MAX_ENTRIES:
            oldest = min(
                state.series_list_cache,
                key=lambda key: state.series_list_cache[key][0],
            )
            state.series_list_cache.pop(oldest, None)
        state.series_list_cache[cache_key] = (now, list(results), ttl)


def load_pages(
    mode: str,
    letter: str,
    requests_to_load: List[tuple[str, int]],
    fetch_provider_page: Callable,
    cold_wave_budget: Optional[List[int]] = None,
    deadline: Optional[float] = None,
    timed_out: Optional[List[bool]] = None,
    cold_load_error: type[RuntimeError] = RuntimeError,
) -> Dict[tuple[str, int], list]:
    loaded = {}
    missing = []
    stale = []
    letter_key = str(letter or "").strip().upper()
    for provider, source_page in dict.fromkeys(requests_to_load):
        cache_mode = (
            "updates"
            if provider != "serienstream" and mode in {"discover", "new"}
            else mode
        )
        cache_key = ("series-provider", cache_mode, letter_key, provider, int(source_page))
        cached, freshness = cache_state(cache_key)
        if freshness == "missing":
            missing.append((provider, source_page, cache_key))
        else:
            loaded[(provider, source_page)] = list(cached or [])
            if freshness == "stale":
                stale.append((provider, source_page, cache_key, list(cached or [])))

    if not missing and not stale:
        return loaded
    if missing and cold_wave_budget is not None:
        if cold_wave_budget[0] <= 0:
            raise cold_load_error(
                "Dieser Serienabschnitt wird noch vorbereitet. Bitte kurz warten und erneut versuchen."
            )
        cold_wave_budget[0] -= 1
    deadline = deadline or (time.monotonic() + SERIES_CATALOG_PAGE_BUDGET_SECONDS)

    def complete(future, provider, source_page, cache_key, stale_fallback=None):
        try:
            results = list(future.result())
        except Exception as exc:
            log(
                f"{PROVIDER_LABELS.get(provider, provider)} Serienliste "
                f"(Quellseite {source_page}) übersprungen: {exc}",
                "warn",
            )
            results = list(stale_fallback or [])
            cache_page(cache_key, results, ttl=SERIES_LIST_FAILURE_CACHE_TTL)
        else:
            cache_page(cache_key, results)
        finally:
            with _INFLIGHT_LOCK:
                if _INFLIGHT.get(cache_key) is future:
                    _INFLIGHT.pop(cache_key, None)

    futures = []
    work = [
        (provider, source_page, cache_key, None, True)
        for provider, source_page, cache_key in missing
    ] + [
        (provider, source_page, cache_key, fallback, False)
        for provider, source_page, cache_key, fallback in stale
    ]
    for provider, source_page, cache_key, stale_fallback, should_wait in work:
        created = False
        with _INFLIGHT_LOCK:
            future = _INFLIGHT.get(cache_key)
            if future is None:
                future = _LOAD_POOL.submit(
                    fetch_provider_page, provider, mode, letter, source_page,
                )
                _INFLIGHT[cache_key] = future
                created = True
        if created:
            future.add_done_callback(
                lambda done, p=provider, s=source_page, key=cache_key,
                fallback=stale_fallback: complete(done, p, s, key, fallback)
            )
        if should_wait:
            futures.append((provider, source_page, cache_key, future))
    if not futures:
        return loaded

    remaining = max(0.0, deadline - time.monotonic())
    done, pending = wait({future for *_meta, future in futures}, timeout=remaining)
    if pending:
        if timed_out is not None:
            timed_out[0] = True
        labels = sorted({
            PROVIDER_LABELS.get(provider, provider)
            for provider, _source_page, _cache_key, future in futures
            if future in pending
        })
        log(
            "Serienkatalog-Zeitbudget erreicht; lädt im Hintergrund weiter: "
            + ", ".join(labels),
            "warn",
        )
    for provider, source_page, _cache_key, future in futures:
        if future not in done:
            continue
        try:
            loaded[(provider, source_page)] = list(future.result())
        except Exception:
            loaded[(provider, source_page)] = []
    return loaded


def schedule_prefetch(
    mode: str,
    letter: str,
    requests_to_load: List[tuple[str, int]],
    fetch_provider_page: Callable,
) -> None:
    requests = tuple(dict.fromkeys(requests_to_load))
    if not requests:
        return
    key = (mode, str(letter or "").strip().upper(), requests)
    with _PREFETCH_LOCK:
        if key in _PREFETCH_INFLIGHT:
            return
        _PREFETCH_INFLIGHT.add(key)

    def work():
        try:
            load_pages(
                mode,
                letter,
                list(requests),
                fetch_provider_page,
                deadline=time.monotonic() + SERIES_CATALOG_PAGE_BUDGET_SECONDS,
            )
        except Exception as exc:
            log(f"Serienkatalog-Prefetch übersprungen: {exc}", "warn")
        finally:
            with _PREFETCH_LOCK:
                _PREFETCH_INFLIGHT.discard(key)

    _PREFETCH_POOL.submit(work)
