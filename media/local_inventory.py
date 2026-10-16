"""Share cold file probes and bound media subprocesses across series scans."""

from concurrent.futures import Future, ThreadPoolExecutor
import threading

media_probe_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="local-media-probe")
_lock = threading.Lock()
_probes = {}


def validate_cached_media(path, *, cache, cache_lock, validate):
    try:
        stat = path.stat()
        signature = (stat.st_size, stat.st_mtime_ns)
    except OSError as exc:
        return False, f"Datei nicht lesbar: {exc}"
    key = str(path.resolve(strict=False))
    with cache_lock:
        cached = cache.get(key)
        if cached and cached[:2] == signature:
            return bool(cached[2]), str(cached[3])
    # Cache identity keeps isolated runtimes/tests from sharing verification.
    probe_key = (id(cache), key, signature)
    with _lock:
        future = _probes.get(probe_key)
        leader = future is None
        if leader:
            future = Future()
            _probes[probe_key] = future
    if not leader:
        return future.result()
    try:
        with cache_lock:
            cached = cache.get(key)
        if cached and cached[:2] == signature:
            result = (bool(cached[2]), str(cached[3]))
        else:
            result = validate(path)
            with cache_lock:
                cache[key] = (*signature, *result)
        future.set_result(result)
        return result
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with _lock:
            _probes.pop(probe_key, None)
