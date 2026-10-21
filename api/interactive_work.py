"""Keep provider browsing from exhausting auth and static-file workers."""

import asyncio
from contextvars import copy_context
from functools import partial

from fastapi import HTTPException

from application_services.series_detail_work import SeriesDetailWork, SeriesDetailsBusy


_BROWSE_WORK = SeriesDetailWork(
    workers=8, capacity=24, retain_seconds=0, thread_name="interactive-browse",
)


async def run_browse_work(function, *args, **kwargs):
    context = copy_context()
    work = partial(function, *args, **kwargs)
    try:
        future = _BROWSE_WORK.submit(object(), lambda: context.run(work))
    except SeriesDetailsBusy as exc:
        raise HTTPException(
            503, detail={"code": "browse_busy", "message": "Katalogabfragen sind ausgelastet."},
            headers={"Retry-After": "2"},
        ) from exc
    waiting = asyncio.wrap_future(future)
    waiting.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    try:
        return await asyncio.shield(waiting)
    except asyncio.CancelledError:
        # Remove queued work immediately. Running work retains its admission
        # slot until it actually exits, even after the client has left.
        future.cancel()
        raise
