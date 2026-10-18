"""Retry periodic housekeeping independently after an individual failure."""

import asyncio
import logging


logger = logging.getLogger(__name__)


async def maintain_runtime(state):
    while True:
        await asyncio.sleep(60)
        for operation in (state.maintain_runtime_caches, state.module_manager.reconcile_all):
            try:
                await asyncio.to_thread(operation)
            except Exception:
                logger.exception("Runtime maintenance failed; retrying next cycle")
