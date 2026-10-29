"""Retry periodic housekeeping independently after an individual failure."""

import asyncio
import logging


logger = logging.getLogger(__name__)


def start_storage_services():
    from application_services.storage_autopilot_runtime import start
    from application_services.media_scans import start_media_scans
    start()
    start_media_scans()


def stop_storage_services():
    from application_services.storage_autopilot_runtime import stop
    from application_services.media_scans import stop_media_scans
    stop_media_scans()
    stop()


async def maintain_runtime(state):
    while True:
        await asyncio.sleep(60)
        for operation in (state.maintain_runtime_caches, state.module_manager.reconcile_all):
            try:
                await asyncio.to_thread(operation)
            except Exception:
                logger.exception("Runtime maintenance failed; retrying next cycle")
