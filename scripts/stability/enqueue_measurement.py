"""Isolate enqueue latency from GC debt accumulated by earlier workloads."""
import concurrent.futures
import gc
import time


def measure_enqueue(queue, make_job, size):
    # Imports and earlier metadata probes leave different collector debt for
    # otherwise identical queues. Settle it before this phase on BOTH revisions.
    # GC remains enabled during enqueue; the encompassing CPU measurement still
    # includes this collection, and no comparison threshold is changed.
    preparation = time.perf_counter()
    collected = gc.collect()
    preparation_ms = (time.perf_counter() - preparation) * 1000
    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _index: queue.add(make_job()), range(size)))
    return {"enqueue_ms": (time.perf_counter() - started) * 1000,
            "enqueue_preparation_gc_ms": preparation_ms,
            "enqueue_preparation_collected": collected}
