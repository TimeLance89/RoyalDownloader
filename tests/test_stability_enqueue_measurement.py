"""Enqueue timing settles prior debt without masking work or disabling GC."""
import gc
import importlib.util
from pathlib import Path
import threading
import weakref

import pytest

spec = importlib.util.spec_from_file_location("enqueue_measurement", Path(__file__).resolve().parents[1] / "scripts/stability/enqueue_measurement.py")
measurement = importlib.util.module_from_spec(spec)
spec.loader.exec_module(measurement)


def test_prior_cycles_are_collected_before_jobs_and_gc_stays_enabled():
    class Cycle:
        pass
    item = Cycle()
    item.self = item
    reference = weakref.ref(item)
    del item
    jobs = []
    class Queue:
        def add(self, job):
            assert reference() is None
            assert gc.isenabled()
            jobs.append(job)
    result = measurement.measure_enqueue(Queue(), object, 40)
    assert len(jobs) == 40
    assert result["enqueue_ms"] >= 0
    assert result["enqueue_preparation_gc_ms"] >= 0
    assert gc.isenabled()


def test_preparation_is_reported_separately_but_every_enqueue_cost_is_measured(monkeypatch):
    clock = [0.0]
    lock = threading.Lock()
    def collect():
        clock[0] += 0.5
        return 123
    monkeypatch.setattr(measurement.gc, "collect", collect)
    monkeypatch.setattr(measurement.time, "perf_counter", lambda: clock[0])
    class Queue:
        def add(self, job):
            with lock:
                clock[0] += 0.002
    result = measurement.measure_enqueue(Queue(), object, 100)
    assert result["enqueue_preparation_gc_ms"] == pytest.approx(500)
    assert result["enqueue_preparation_collected"] == 123
    assert result["enqueue_ms"] == pytest.approx(200)
