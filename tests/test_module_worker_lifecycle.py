import threading

from modules.runtime import WorkerModuleController


def test_worker_controller_stops_and_restarts_exactly_one_real_worker():
    stop = threading.Event()
    threads = []

    def alive():
        return any(thread.is_alive() for thread in threads)

    def start():
        if alive():
            return
        stop.clear()
        thread = threading.Thread(target=lambda: stop.wait(1), daemon=True)
        threads.append(thread)
        thread.start()

    def halt():
        stop.set()
        for thread in threads:
            thread.join(0.2)
        return not alive()

    controller = WorkerModuleController(start, halt, alive, lambda: (True, "configured"))
    controller.start()
    assert controller.health()[0] is True
    assert len(threads) == 1
    assert controller.stop() is True
    assert controller.health()[0] is False
    controller.start()
    assert controller.health()[0] is True
    assert len(threads) == 2


def test_worker_controller_never_starts_when_configuration_is_missing():
    controller = WorkerModuleController(lambda: (_ for _ in ()).throw(AssertionError()), lambda: None, lambda: False, lambda: (False, "Token fehlt"))
    try:
        controller.start()
    except RuntimeError as exc:
        assert "Token fehlt" in str(exc)
    else:
        raise AssertionError("unconfigured worker must not start")


def test_worker_controller_serializes_parallel_starts_without_double_worker():
    stop = threading.Event()
    workers = []
    start_gate = threading.Barrier(6)

    def alive():
        return any(worker.is_alive() for worker in workers)

    def start():
        if alive():
            return
        worker = threading.Thread(target=lambda: stop.wait(1), daemon=True)
        workers.append(worker)
        worker.start()

    def halt():
        stop.set()
        for worker in workers:
            worker.join(0.2)
        return not alive()

    controller = WorkerModuleController(start, halt, alive, lambda: (True, "configured"))
    callers = [threading.Thread(target=lambda: (start_gate.wait(), controller.start())) for _ in range(5)]
    for caller in callers:
        caller.start()
    start_gate.wait()
    for caller in callers:
        caller.join(1)

    assert len(workers) == 1
    assert controller.stop() is True
