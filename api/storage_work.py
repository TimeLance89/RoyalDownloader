"""Isolate slow mount/durable-state work from auth and static-file workers."""

import asyncio
import threading
from contextvars import copy_context
from copy import deepcopy
from functools import partial

from fastapi import HTTPException

from application_services.series_detail_work import SeriesDetailWork, SeriesDetailsBusy


_STORAGE_WORK = SeriesDetailWork(workers=2, capacity=4, retain_seconds=0, thread_name="storage-http")
_TELEMETRY_WORK = SeriesDetailWork(workers=1, capacity=2, retain_seconds=1, thread_name="storage-telemetry")
TELEMETRY_WAIT_SECONDS = 3
_REVISION_LOCK = threading.Lock()
_REVISION = 0


def invalidate_storage_telemetry():
    global _REVISION
    with _REVISION_LOCK:
        _REVISION += 1


def _busy(code, message):
    return HTTPException(503, detail={"code": code, "message": message}, headers={"Retry-After": "3"})


async def _run(pool, key, function, args, kwargs, *, timeout=None):
    context = copy_context()
    work = partial(function, *args, **kwargs)
    try:
        future = pool.submit(key, lambda: context.run(work))
    except SeriesDetailsBusy as exc:
        raise _busy("storage_busy", "Speicherzugriffe sind ausgelastet. Bitte kurz warten.") from exc
    waiting = asyncio.wrap_future(future)
    waiting.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    try:
        if timeout is not None:
            return deepcopy(await asyncio.wait_for(asyncio.shield(waiting), timeout))
        return await asyncio.shield(waiting)
    except TimeoutError as exc:
        # Do not free admission or launch a replacement while the filesystem
        # syscall is still blocked. Polls continue to join the same future.
        raise _busy("storage_timeout", "Der Speicher antwortet zu langsam. Bitte später erneut versuchen.") from exc
    except asyncio.CancelledError:
        if timeout is None:
            future.cancel()  # only queued mutations may be cancelled
        raise


async def run_storage_work(function, *args, **kwargs):
    # Mutations are never cached, shared or retried automatically.
    def invoke():
        try:
            return function(*args, **kwargs)
        finally:
            # Invalidate when the actual work ends, even if its HTTP caller
            # disconnected earlier or a partially completed operation raised.
            invalidate_storage_telemetry()
    return await _run(_STORAGE_WORK, object(), invoke, (), {})


async def read_storage_telemetry(key, function, *args, **kwargs):
    with _REVISION_LOCK:
        revision = _REVISION
    return await _run(_TELEMETRY_WORK, (revision, key), function, args, kwargs, timeout=TELEMETRY_WAIT_SECONDS)
