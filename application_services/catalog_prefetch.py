"""Bound distinct speculative catalog jobs, including queued jobs."""


def schedule_prefetch(pool, pending, lock, key, work, capacity):
    with lock:
        if key in pending or len(pending) >= capacity:
            return False
        pending.add(key)

    def finished(_future=None):
        with lock:
            pending.discard(key)

    try:
        future = pool.submit(work)
    except BaseException:
        finished()
        raise
    # Also releases admission when queued work is cancelled before it starts.
    future.add_done_callback(finished)
    return True
