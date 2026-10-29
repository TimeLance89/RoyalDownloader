"""Owned process and browser lifecycle regression tests, no external websites."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from core import owned_process as owned
from media.extractor import VOEBrowserPool
from integrations import serienstream_shared_session as shared, serienstream_verification as verification


class Process:
    def __init__(self, *, waits=(), exited=False, signal_error=False):
        self.returncode = 0 if exited else None
        self.waits = iter(waits)
        self.events = []
        self.signal_error = signal_error
    def poll(self):
        return self.returncode
    def terminate(self):
        self.events.append('terminate')
        if self.signal_error:
            raise OSError('private value')
    def kill(self):
        self.events.append('kill')
    def wait(self, timeout):
        self.events.append(('wait', timeout))
        failure = next(self.waits, None)
        if failure:
            raise failure
        self.returncode = -9 if 'kill' in self.events else 0
        return self.returncode


@pytest.mark.parametrize('first_error', [subprocess.TimeoutExpired('fixture', 3), OSError('fixture')])
def test_terminate_wait_kill_wait_even_after_wait_exception(first_error):
    process = Process(waits=[first_error])
    assert owned.stop(process)
    assert process.events == ['terminate', ('wait', 3), 'kill', ('wait', 3)]


def test_already_exited_process_is_waited_without_signalling():
    process = Process(exited=True)
    assert owned.stop(process)
    assert owned.stop(process)
    assert process.events == [('wait', 3), ('wait', 3)]


def test_signal_errors_do_not_skip_wait():
    process = Process(signal_error=True)
    assert owned.stop(process)
    assert process.events == ['terminate', ('wait', 3)]


@pytest.mark.parametrize('module,attributes', [(shared, ('chrome', 'xvfb')), (verification, ('_chrome', '_xvfb'))])
def test_both_browser_handles_reaped_and_close_is_idempotent(module, attributes):
    owner = shared._BrowserRuntime() if module is shared else verification.SerienStreamVerificationManager()
    processes = [Process(waits=[subprocess.TimeoutExpired('fixture', 3)]), Process(exited=True)]
    for attr, process in zip(attributes, processes):
        setattr(owner, attr, process)
    owner.close()
    owner.close()
    assert all(getattr(owner, attr) is None for attr in attributes)
    assert processes[0].events == ['terminate', ('wait', 3), 'kill', ('wait', 3)]
    assert processes[1].events == [('wait', 3)]


@pytest.mark.parametrize('module,attributes', [(shared, ('chrome', 'xvfb')), (verification, ('_chrome', '_xvfb'))])
def test_unreaped_handle_is_retained_and_does_not_prevent_other_cleanup(module, attributes):
    owner = shared._BrowserRuntime() if module is shared else verification.SerienStreamVerificationManager()
    stuck = Process(waits=[OSError('x'), OSError('x')])
    other = Process()
    setattr(owner, attributes[0], stuck)
    setattr(owner, attributes[1], other)
    owner.close()
    assert getattr(owner, attributes[0]) is stuck
    assert getattr(owner, attributes[1]) is None
    owner.close()
    assert getattr(owner, attributes[0]) is None


@pytest.mark.parametrize('module', [shared, verification])
def test_partial_chromium_spawn_failure_reaps_xvfb(monkeypatch, tmp_path, module):
    monkeypatch.setattr(module.shutil, 'which', lambda name: name)
    monkeypatch.setattr(module, '_free_local_port', lambda: 9300)
    if module is shared:
        monkeypatch.setattr(module, '_profile_dir', lambda: tmp_path)
        owner, start = shared._BrowserRuntime(), 'start'
    else:
        monkeypatch.setattr(module, 'data_dir', lambda: tmp_path)
        owner, start = verification.SerienStreamVerificationManager(), '_start_processes_locked'
    xvfb = Process()
    calls = []
    def spawn(*args, **kwargs):
        calls.append(True)
        if len(calls) == 1:
            return xvfb
        raise OSError('fixture chromium failed to spawn')
    monkeypatch.setattr(module.subprocess, 'Popen', spawn)
    with pytest.raises(OSError):
        getattr(owner, start)()
    assert xvfb.events == ['terminate', ('wait', 3)]


class AsyncProcess(Process):
    async def wait(self):
        self.events.append('wait')
        if self.returncode is None:
            await asyncio.sleep(60)
        return self.returncode
    def kill(self):
        self.events.append('kill')
        self.returncode = -9


def test_async_timeout_and_cancellation_reap_before_loop_closes():
    async def run():
        process = AsyncProcess()
        assert await owned.stop_async(process, timeout=.01)
        assert process.events == ['terminate', 'wait', 'kill', 'wait']
        second = AsyncProcess()
        task = asyncio.create_task(owned.stop_async(second, timeout=.1))
        await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert second.returncode == -9
        assert second.events[-2:] == ['kill', 'wait']
    asyncio.run(run())


def test_browser_proxy_is_module_local_and_only_tags_created_process(monkeypatch):
    calls = []
    process = SimpleNamespace(pid=123)
    async def create(*args, **kwargs):
        calls.append(kwargs)
        return process
    proxy = owned.BrowserAsyncio(SimpleNamespace(create_subprocess_exec=create, marker=True))
    assert asyncio.run(proxy.create_subprocess_exec('fixture')) is process
    assert proxy.marker is True
    assert calls == ([{'start_new_session': True}] if os.name == 'posix' else [{}])
    assert not isinstance(asyncio, owned.BrowserAsyncio)


def test_process_group_signal_requires_spawned_live_leader(monkeypatch):
    calls = []
    monkeypatch.setattr(owned.os, 'name', 'posix')
    monkeypatch.setattr(owned.os, 'getpgrp', lambda: 500, raising=False)
    monkeypatch.setattr(owned.os, 'getpgid', lambda pid: pid, raising=False)
    monkeypatch.setattr(owned.os, 'killpg', lambda *args: calls.append(args), raising=False)
    process = Process()
    process.pid = 600
    owned._signal(process)
    assert calls == []
    process._royal_process_group = 600
    owned._signal(process)
    assert calls[0][0] == 600
    process.returncode = 0
    owned._signal(process, force=True)
    assert len(calls) == 1
    process.returncode = None
    process._royal_process_group = 500  # never our own/session's group
    owned._signal(process, force=True)
    assert len(calls) == 1


@pytest.mark.parametrize('phase', ['startup', 'setup', 'cancelled'])
def test_pool_owner_finally_cleans_partial_start_before_loop_close(monkeypatch, phase):
    pool = VOEBrowserPool(setup_voe=phase == 'setup')
    process = AsyncProcess(exited=True)
    browser = SimpleNamespace(_process=process, _process_pid=123)
    async def start():
        pool._browser = browser
        if phase == 'startup':
            raise RuntimeError('fixture startup failure')
        if phase == 'cancelled':
            raise asyncio.CancelledError
        return browser
    async def setup():
        raise RuntimeError('fixture setup failure')
    monkeypatch.setattr(pool, '_async_browser_start', start)
    monkeypatch.setattr(pool, '_async_setup_voe_token', setup)
    with pytest.raises(RuntimeError):
        pool._start_once()
    pool._cleanup_failed_start()
    assert process.events == ['wait']
    assert pool._loop is None
    assert pool._browser is None
    assert pool._thread is None
    pool.close()


def test_pool_reuses_live_owner_and_closes_worker_and_tasks(monkeypatch):
    pool = VOEBrowserPool(setup_voe=False)
    calls = []
    process = AsyncProcess(exited=True)
    async def background():
        try:
            await asyncio.sleep(60)
        finally:
            calls.append('cancelled')
    async def start():
        asyncio.create_task(background())
        calls.append('start')
        return SimpleNamespace(_process=process)
    monkeypatch.setattr(pool, '_async_browser_start', start)
    monkeypatch.setattr(pool, '_do_extract', lambda *args: 'result')
    assert pool.extract('fixture') == pool.extract('fixture') == 'result'
    worker = pool._thread
    assert calls == ['start']
    pool.close()
    pool.close()
    assert not worker.is_alive()
    assert calls == ['start', 'cancelled']
    assert process.events == ['wait']


def test_cleanup_cannot_drop_thread_or_allow_retry_if_worker_still_alive():
    pool = VOEBrowserPool(setup_voe=False)
    pool._thread = SimpleNamespace(join=lambda **kwargs: None, is_alive=lambda: True)
    original = pool._thread
    with pytest.raises(RuntimeError, match='owner retained'):
        pool._cleanup_failed_start()
    assert pool._thread is original


def test_container_has_reaper_even_when_compose_init_is_not_configured():
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / 'Dockerfile').read_text(encoding='utf-8')
    assert '        tini \\' in dockerfile
    assert 'ENTRYPOINT ["/usr/bin/tini", "-s", "--"]' in dockerfile
    assert 'init: true' in (root / 'docker-compose.yml').read_text(encoding='utf-8')


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux process adoption and /proc integration')
def test_real_process_tree_has_no_accumulating_zombies_or_foreign_kills():
    fixture = Path(__file__).parent / 'fixtures' / 'reaping_probe.py'
    # Own isolated test supervisor; never become a subreaper inside pytest/Royal.
    code = ('import ctypes,runpy,sys; '
            'assert ctypes.CDLL(None).prctl(36,1,0,0,0)==0; '
            'sys.argv=[sys.argv[1],"--reap-adopted"]; '
            'runpy.run_path(sys.argv[0],run_name="__main__")')
    result = subprocess.run([sys.executable, '-c', code, str(fixture)],
                            capture_output=True, text=True, timeout=25)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'reaping-ok' in result.stdout

def test_failed_download_callback_cannot_leave_its_child_running(monkeypatch, tmp_path):
    from media.downloader import DownloadJob
    process = Process(waits=[subprocess.TimeoutExpired('fixture', 3)])
    results = []
    job = DownloadJob('https://fixture.invalid/stream', 'hls', tmp_path / 'movie.mp4',
                      on_done=lambda ok, message: results.append((ok, process.returncode)))
    def fail(**kwargs):
        job._proc = process
        raise RuntimeError('fixture progress callback failed')
    monkeypatch.setattr(job, '_download_ytdlp', fail)
    monkeypatch.setattr(job, '_cleanup_staging', lambda: None)
    monkeypatch.setattr(job, '_terminate_process_tree', lambda **kwargs: None)
    job._run()
    assert results == [(False, -9)]
    assert job._proc is None
    assert process.events == ['terminate', ('wait', 3), 'kill', ('wait', 3)]


def test_browser_sidecar_signal_unwinds_wait_then_reaps_and_stops_guard(monkeypatch):
    from core import browser_egress
    handlers, calls = {}, []
    process = Process()
    monkeypatch.setattr(browser_egress.signal, 'signal', lambda number, callback: handlers.setdefault(number, callback))
    monkeypatch.setattr(browser_egress, 'command', lambda arguments: ['fixture'])
    monkeypatch.setattr(browser_egress, 'spawn', lambda *args, **kwargs: process)
    def wait():
        handlers[browser_egress.signal.SIGTERM](browser_egress.signal.SIGTERM, None)
    process.wait = wait
    monkeypatch.setattr(browser_egress, 'stop', lambda child: calls.append('reaped'))
    monkeypatch.setattr(browser_egress, 'stop_safe_proxy', lambda: calls.append('proxy'))
    with pytest.raises(SystemExit):
        browser_egress.main()
    assert calls == ['reaped', 'proxy']


def test_process_diagnostics_are_aggregate_and_have_no_command_or_pid_data():
    assert set(owned.snapshot()) == {'started', 'reaped', 'cleanup_errors', 'open_handles'}

def test_real_async_child_pipes_are_drained_and_transport_closes():
    async def run():
        code = "import sys,time; print('ready',flush=True); sys.stdout.write('x'*1000000); sys.stdout.flush(); time.sleep(60)"
        process = await owned.BrowserAsyncio(asyncio).create_subprocess_exec(
            sys.executable, '-c', code, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            assert (await asyncio.wait_for(process.stdout.readline(), timeout=3)).strip() == b'ready'
            assert await owned.stop_async(process, timeout=1)
            assert process.returncode is not None
            assert process._transport.is_closing()
        finally:
            await owned.stop_async(process, timeout=1)
    asyncio.run(run())


def test_unstarted_thread_can_be_cleaned_after_thread_creation_failure(monkeypatch):
    pool = VOEBrowserPool(setup_voe=False)
    def fail(_thread):
        raise RuntimeError('fixture cannot start thread')
    monkeypatch.setattr(threading.Thread, 'start', fail)
    with pytest.raises(RuntimeError, match='cannot start thread'):
        pool._start_once()
    pool._cleanup_failed_start()
    assert pool._thread is pool._loop is pool._browser is None
    pool.close()


def test_loop_creation_failure_signals_startup_failure_without_timeout(monkeypatch):
    pool = VOEBrowserPool(setup_voe=False)
    def fail():
        raise OSError('fixture loop resource limit')
    monkeypatch.setattr(asyncio, 'new_event_loop', fail)
    with pytest.raises(OSError, match='resource limit'):
        pool._start_once()
    pool._cleanup_failed_start()
    assert pool._thread is pool._loop is pool._browser is None


def test_loop_published_during_join_is_cleaned_before_owner_is_cleared(monkeypatch):
    pool = VOEBrowserPool(setup_voe=False)
    loop = asyncio.new_event_loop()
    calls = []
    async def cleanup():
        calls.append(True)
        return True
    monkeypatch.setattr(pool, '_async_browser_stop', cleanup)
    def join(**kwargs):
        pool._loop = loop
    pool._thread = SimpleNamespace(ident=1, join=join, is_alive=lambda: False)
    pool._cleanup_failed_start()
    assert calls == [True]
    assert loop.is_closed()
    assert pool._loop is None
