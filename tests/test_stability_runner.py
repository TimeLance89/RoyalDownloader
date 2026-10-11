"""Runner isolation must preserve failures, kill descendants and forbid egress."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stability_runner', ROOT / 'scripts/stability/run_suite.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def stopped(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().split()[2] == 'Z'
    except (FileNotFoundError, ProcessLookupError):
        return True


def owned_descendant_script(pidfile, parent_wait):
    # /proc can expose host PIDs while Python sees nested namespace PIDs.
    child = ("import time; from pathlib import Path; "
             "pid=next(line.split()[1] for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('Pid:')); "
             f"Path({str(pidfile)!r}).write_text(pid); time.sleep(20)")
    return ("import subprocess,sys,time; from pathlib import Path; "
            f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
            f"path=Path({str(pidfile)!r}); "
            "deadline=time.monotonic()+2; "
            "exec('while not path.exists() and time.monotonic()<deadline: time.sleep(.01)'); "
            "assert path.exists(); " + ("time.sleep(20)" if parent_wait else ""))


def test_deadline_kills_owned_descendants_and_records_failure(tmp_path):
    pidfile = tmp_path / 'descendant.pid'
    result = runner.run_process([sys.executable, '-c', owned_descendant_script(pidfile, True)],
                                tmp_path, dict(os.environ), tmp_path / 'timeout.log', 1)
    assert result['exit_code'] == 124 and result['timeout']
    pid = int(pidfile.read_text())
    for _ in range(30):
        if stopped(pid):
            break
        time.sleep(0.01)
    assert stopped(pid), 'timed-out descendant is still executing'


def test_normal_parent_exit_also_cleans_owned_descendants(tmp_path):
    pidfile = tmp_path / 'descendant.pid'
    result = runner.run_process([sys.executable, '-c', owned_descendant_script(pidfile, False)],
                                tmp_path, dict(os.environ), tmp_path / 'clean.log', 3)
    assert result['exit_code'] == 0
    pid = int(pidfile.read_text())
    for _ in range(30):
        if stopped(pid):
            break
        time.sleep(0.01)
    assert stopped(pid)


def test_subprocess_inherits_synthetic_dns_and_native_curl_guard():
    env = dict(os.environ, ROYAL_STABILITY_OFFLINE='1',
               PYTHONPATH=str(ROOT / 'scripts/stability'))
    code = '''
import socket
from curl_cffi import Curl, CurlOpt
import offline_guard
original = Curl.perform
offline_guard.pytest_configure(None)
assert Curl.perform is original
assert socket.getaddrinfo('fixture.invalid',443)[0][4][0] == '93.184.216.34'
try:
    socket.socket().connect(('93.184.216.34',443))
except OSError as exc:
    assert 'OFFLINE TEST' in str(exc)
else:
    raise AssertionError('external Python socket allowed')
c=Curl(); c.setopt(CurlOpt.URL,'https://fixture.invalid/')
try:
    c.perform()
except OSError as exc:
    assert 'OFFLINE TEST' in str(exc)
else:
    raise AssertionError('external native curl allowed')
c.close()
'''
    result = subprocess.run([sys.executable, '-c', code], env=env,
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr


def test_module_mode_discovers_nested_tests_and_preserves_failure(tmp_path):
    tests = tmp_path / 'tests'; tests.mkdir()
    (tests / 'test_ok.py').write_text('def test_ok(): assert True\n')
    nested = tests / 'nested'; nested.mkdir()
    (nested / 'test_bad.py').write_text('def test_bad(): assert False\n')
    output = tmp_path / 'results'
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/stability/run_suite.py'),
                             '--root', str(tmp_path), '--output', str(output),
                             '--mode', 'modules', '--timeout', '15'],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 1, result.stderr
    suites = ET.parse(output / 'tests.xml').getroot()
    assert sum(int(s.attrib['tests']) for s in suites) == 2
    assert sum(int(s.attrib['failures']) for s in suites) == 1


def test_empty_repository_cannot_produce_green_result(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/stability/run_suite.py'),
                             '--root', str(tmp_path), '--output', str(tmp_path / 'out')],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode != 0
    assert not (tmp_path / 'out/tests.xml').exists()


def test_owned_process_rss_is_measured_across_pid_namespace(tmp_path):
    result = runner.run_process([sys.executable, '-c',
        'import time; payload=bytearray(8*1024*1024); time.sleep(.15)'],
        tmp_path, dict(os.environ), tmp_path / 'rss.log', 3)
    assert result['exit_code'] == 0
    assert result['children_cumulative_max_rss_mib'] > 8
    if Path('/proc/self/status').exists():
        assert result['sampled_pytest_max_rss_mib'] > 8
        assert result['sampled_pytest_peak_threads'] >= 1


def test_procfs_reaping_race_is_absent_but_permissions_are_not(monkeypatch):
    import errno
    def vanished(_path, **_kwargs):
        raise ProcessLookupError(errno.ESRCH, 'reaped between open and read')
    monkeypatch.setattr(Path, 'read_text', vanished)
    assert stopped(12345)
    def denied(_path, **_kwargs):
        raise PermissionError(errno.EACCES, 'cannot inspect a live child')
    monkeypatch.setattr(Path, 'read_text', denied)
    import pytest
    with pytest.raises(PermissionError):
        stopped(12345)


def test_junit_merge_rejects_dtd_and_external_entities(tmp_path):
    import pytest
    from defusedxml.common import DefusedXmlException
    private = tmp_path / 'private.txt'
    private.write_text('synthetic-secret-must-not-be-read')
    source = tmp_path / 'malicious.xml'
    source.write_text(f'<!DOCTYPE testsuite [<!ENTITY leaked SYSTEM "{private.as_uri()}">]>'
                      '<testsuite><testcase>&leaked;</testcase></testsuite>')
    output = tmp_path / 'merged.xml'
    with pytest.raises(DefusedXmlException):
        runner.merge_junit([source], output)
    assert not output.exists()
