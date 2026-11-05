"""Coalesce inventory I/O without extending successful snapshot lifetimes."""
from collections import Counter, OrderedDict
from concurrent.futures import Future
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import threading
from time import perf_counter

_background = ContextVar('jellyfin_background_read', default=False)
_init_lock = threading.Lock()


@contextmanager
def background_inventory_reads():
    token = _background.set(True)
    try:
        yield
    finally:
        _background.reset(token)


def is_background_read():
    return _background.get()


@dataclass(frozen=True)
class ReadResult:
    value: object
    serial: int
    finished: float
    retry_until: float


class InventoryReads:
    def __init__(self, *, clock=perf_counter, max_entries=16):
        self.clock, self.max_entries = clock, max_entries
        self.lock = threading.Lock()
        self.active = {}
        self.completed = OrderedDict()
        self.counts = Counter()
        self.serial = 0

    def read(self, key, loader, *, requested=None, background=False, retry_seconds=30, on_start=None):
        requested = self.clock() if requested is None else requested
        with self.lock:
            previous = self.completed.get(key)
            if previous and (previous.finished > requested or
                             (background and previous.value is None and self.clock() < previous.retry_until)):
                self.counts['reused'] += 1
                return previous
            future = self.active.get(key)
            owner = future is None
            if owner:
                future = self.active[key] = Future()
                self.serial += 1
                serial = self.serial
                self.counts['started'] += 1
            else:
                self.counts['joined'] += 1
        if not owner:
            return future.result()
        try:
            if on_start is not None:
                on_start()
            value = loader()
            finished = self.clock()
            result = ReadResult(value, serial, finished, finished + retry_seconds if value is None else 0)
            with self.lock:
                self.completed[key] = result
                self.completed.move_to_end(key)
                while len(self.completed) > self.max_entries:
                    self.completed.popitem(last=False)
                self.active.pop(key, None)
                if value is None:
                    self.counts['failed'] += 1
            future.set_result(result)
            return result
        except BaseException as exc:
            with self.lock:
                self.active.pop(key, None)
            future.set_exception(exc)
            raise

    def clear(self):
        with self.lock:
            self.completed.clear()

    def forget(self, dataset):
        with self.lock:
            for key in list(self.completed):
                if key[2] == dataset:
                    self.completed.pop(key)

    def snapshot(self):
        with self.lock:
            return {**{key: self.counts[key] for key in ('started', 'joined', 'reused', 'failed')},
                    'inflight': len(self.active), 'retained_results': len(self.completed)}


def inventory_reads(state):
    with _init_lock:
        reader = getattr(state, '_jellyfin_inventory_reads', None)
        if reader is None:
            reader = state._jellyfin_inventory_reads = InventoryReads()
        return reader


def scope_key(client, generation, dataset, user=''):
    # Credentials stay in memory only, hashed, never exposed in diagnostics.
    origin = getattr(client, 'base_url', '')
    scope = (origin or id(client), getattr(client, 'api_key', ''),
             getattr(client, 'provider', 'jellyfin'), tuple(getattr(client, 'libraries', ())),
             getattr(client, 'server_id', ''))
    digest = hashlib.sha256(repr(scope).encode()).digest()
    return generation, digest, dataset, user


def movie_identities(items):
    return [{key: str(item.get(key) or '') for key in
             ('id', 'name', 'original_title', 'sort_name', 'tmdb_id')} | {'year': item.get('year')}
            for item in items]
