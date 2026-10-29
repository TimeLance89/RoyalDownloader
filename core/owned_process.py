"""Bounded cleanup of owned subprocess handles, never a global child reaper."""
import asyncio
from collections import Counter
import logging
import os
import signal
import threading

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_counts = Counter()
_open = set()


def register(process, *, group=False):
    pid = getattr(process, 'pid', None)
    if group and os.name == 'posix' and isinstance(pid, int) and pid > 1:
        process._royal_process_group = pid
    with _lock:
        _counts['started'] += 1
        _open.add(id(process))
    return process


def spawn(factory, *args, **kwargs):
    """Create a private POSIX session; mark only handles we actually created."""
    if os.name == 'posix':
        kwargs['start_new_session'] = True
    return register(factory(*args, **kwargs), group=os.name == 'posix')


def _signal(process, *, force=False):
    """Signal a proven owned group only while its unreaped leader still exists."""
    try:
        if getattr(process, 'returncode', None) is not None:
            return
        group = getattr(process, '_royal_process_group', None)
        if os.name == 'posix' and isinstance(group, int) and group > 1:
            if os.getpgid(process.pid) == group == process.pid and group != os.getpgrp():
                os.killpg(group, signal.SIGKILL if force else signal.SIGTERM)
                return
    except OSError:
        pass
    try:
        process.kill() if force else process.terminate()
    except Exception:
        # A concurrent exit or signalling failure must not bypass wait().
        pass


def _result(process, reaped):
    with _lock:
        if reaped:
            if id(process) in _open:
                _counts['reaped'] += 1
                _open.discard(id(process))
        else:
            _counts['cleanup_errors'] += 1
    if not reaped:
        logger.warning('Owned process cleanup incomplete; handle retained')
    return reaped


def stop(process, *, timeout=3):
    if process is None:
        return True
    try:
        running = process.poll() is None
    except Exception:
        running = True
    if running:
        _signal(process)
    try:
        process.wait(timeout=timeout)
        return _result(process, True)
    except Exception:
        _signal(process, force=True)
    try:
        process.wait(timeout=timeout)
        return _result(process, True)
    except Exception:
        return _result(process, False)


async def _drain(stream):
    if stream is not None:
        while await stream.read(65536):
            pass  # Discard output, do not retain potentially sensitive stderr.


async def stop_async(process, *, timeout=3):
    if process is None:
        return True
    drains = [asyncio.create_task(_drain(getattr(process, name, None))) for name in ('stdout', 'stderr')]
    reaped = False
    try:
        if process.returncode is None:
            _signal(process)
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
            reaped = True
        except Exception:
            _signal(process, force=True)
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout)
                reaped = True
            except Exception:
                pass
    except asyncio.CancelledError:
        _signal(process, force=True)
        try:
            await asyncio.wait_for(process.wait(), timeout=timeout)
            reaped = True
        except Exception:
            pass
        _result(process, reaped)
        raise
    finally:
        for task in drains:
            task.cancel()
        await asyncio.gather(*drains, return_exceptions=True)
        if reaped:
            transport = getattr(process, '_transport', None)
            if transport is not None:
                transport.close()
    return _result(process, reaped)


class BrowserAsyncio:
    """Module-local nodriver seam; leave global asyncio/download spawns alone."""
    def __init__(self, delegate):
        self._delegate = delegate

    def __getattr__(self, name):
        return getattr(self._delegate, name)

    async def create_subprocess_exec(self, *args, **kwargs):
        if os.name == 'posix':
            kwargs['start_new_session'] = True
        process = await self._delegate.create_subprocess_exec(*args, **kwargs)
        return register(process, group=os.name == 'posix')


def snapshot():
    with _lock:
        return {**{key: _counts[key] for key in ('started', 'reaped', 'cleanup_errors')}, 'open_handles': len(_open)}
