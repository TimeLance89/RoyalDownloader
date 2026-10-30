"""Controlled source reads share the existing SerienStream recovery ownership."""

from contextlib import nullcontext

from media.session_manager import ProviderBlockedError
from providers.sentinel_runtime import runtime_recovery


def read_serienstream(operation, *, health, lock, scraper_factory, on_blocked):
    """One source read owns recovery after an expired cooldown, including browse."""
    recovery = not health.request_allowed("serienstream")
    if recovery and not health.begin_probe("serienstream"):
        raise RuntimeError("SerienStream befindet sich im Provider-Cooldown")
    try:
        with lock, (runtime_recovery("serienstream") if recovery else nullcontext()):
            scraper = scraper_factory()
            if recovery:
                # A cached catalog is not evidence that the source recovered.
                for name in ("_catalog_cache", "_browse_catalog_cache", "_beliebte_cache"):
                    setattr(scraper, name, None)
            result = operation(scraper)
        if recovery:
            if result:
                health.mark_success("serienstream")
            else:
                health.finish_probe_error("serienstream", "runtime_recovery_empty")
        return result
    except ProviderBlockedError as exc:
        on_blocked(exc.reason, str(exc))
        raise
    except Exception:
        if recovery and health.status("serienstream")["state"] == "probing":
            health.finish_probe_error("serienstream", "runtime_recovery_failed")
        raise

