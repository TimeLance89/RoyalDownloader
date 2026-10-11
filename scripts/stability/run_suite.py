"""One offline runner: complete suite or fresh bounded module processes."""
import argparse
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET


def resolve_process_pid(pid):
    """Resolve PID when the host procfs is mounted in a nested PID namespace."""
    try:
        parent = int(next(line.split()[1] for line in
                          Path('/proc/self/status').read_text().splitlines()
                          if line.startswith('Pid:')))
        for status in Path('/proc').glob('[0-9]*/status'):
            try:
                fields = dict(line.split(':', 1) for line in status.read_text().splitlines()
                              if ':' in line)
                namespace_pid = int(fields.get('NSpid', fields['Pid']).split()[-1])
                if namespace_pid == pid and int(fields['PPid']) == parent:
                    return int(fields['Pid'])
            except (OSError, ValueError, KeyError):
                continue
    except (OSError, ValueError, StopIteration):
        pass
    return pid


def process_sample(pid):
    """Linux diagnostic; child RSS is not the whole container's memory."""
    try:
        fields = {}
        for line in Path(f'/proc/{pid}/status').read_text().splitlines():
            key, _, value = line.partition(':')
            if key in {'VmHWM', 'VmRSS', 'Threads'}:
                fields[key] = int(value.strip().split()[0])
        return fields
    except (OSError, ValueError):
        return {}


def run_process(command, root, env, log_path, timeout):
    started = time.monotonic()
    cpu_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    peak_kib = threads = 0
    with log_path.open('w') as log:
        child = subprocess.Popen(command, cwd=root, env=env, stdout=log,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        sample_pid = resolve_process_pid(child.pid)
        timed_out = False
        while child.poll() is None:
            sample = process_sample(sample_pid)
            peak_kib = max(peak_kib, sample.get('VmHWM', 0), sample.get('VmRSS', 0))
            threads = max(threads, sample.get('Threads', 0))
            if time.monotonic() - started >= timeout:
                timed_out = True
                break
            time.sleep(0.05)
        # Neither timed-out pytest nor successful pytest may orphan children.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
    cpu_after = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {'exit_code': 124 if timed_out else child.returncode,
            'seconds': time.monotonic() - started,
            'cpu_seconds': (cpu_after.ru_utime + cpu_after.ru_stime
                            - cpu_before.ru_utime - cpu_before.ru_stime),
            'sampled_pytest_max_rss_mib': peak_kib / 1024,
            'children_cumulative_max_rss_mib': cpu_after.ru_maxrss / 1024,
            'sampled_pytest_peak_threads': threads,
            'timeout': timed_out}


def merge_junit(paths, output):
    merged = ET.Element('testsuites')
    for path in paths:
        root = ET.parse(path).getroot()
        merged.extend([root] if root.tag == 'testsuite' else list(root))
    ET.ElementTree(merged).write(output, encoding='utf-8', xml_declaration=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=['suite', 'modules'], default='suite')
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--module-timeout', type=int, default=90)
    parser.add_argument('--test-timeout', type=int, default=30)
    parser.add_argument('tests', nargs='*')
    args = parser.parse_args()
    if min(args.timeout, args.module_timeout, args.test_timeout) <= 0:
        parser.error('Timeouts must be positive')
    root, output = args.root.resolve(), args.output.resolve()
    modules = sorted(root.joinpath('tests').rglob('test_*.py'))
    if not modules:
        parser.error('No Python modules found; refusing an empty green run')
    output.mkdir(parents=True, exist_ok=True)
    keep = {'PATH', 'LANG', 'LC_ALL', 'TZ', 'LD_PRELOAD', 'PYTHONDONTWRITEBYTECODE'}
    env = {key: value for key, value in os.environ.items() if key in keep}
    env.update(PYTHONPATH=str(Path(__file__).resolve().parent),
               ROYAL_STABILITY_OFFLINE='1', SERIENDL_DATA_DIR='')
    cases = [[str(p.relative_to(root))] for p in modules] if args.mode == 'modules' else [args.tests]
    if args.tests and args.mode == 'modules':
        cases = [[p] for p in args.tests]
    started = time.monotonic()
    records, junit = [], []
    for index, tests in enumerate(cases):
        remaining = args.timeout - (time.monotonic() - started)
        if remaining <= 0:
            records.append({'tests': tests, 'exit_code': 124, 'timeout': True})
            break
        name = 'tests' if args.mode == 'suite' else f'module-{index:03d}'
        xml = output / f'{name}.xml'
        command = [sys.executable, '-m', 'pytest', '-p', 'offline_guard', '-q',
                   f'--timeout={args.test_timeout}', '--durations=20',
                   f'--junitxml={xml}', *tests]
        with tempfile.TemporaryDirectory(prefix='stability-fixtures-', dir=output.parent) as fixture_tmp:
            env['TMPDIR'] = fixture_tmp
            env['HOME'] = fixture_tmp
            env['XDG_CACHE_HOME'] = fixture_tmp
            record = run_process(command, root, env, output / f'{name}.log',
                                 min(remaining, args.module_timeout) if args.mode == 'modules' else remaining)
        record.update(tests=tests, command=command)
        if not xml.exists() and record['exit_code'] == 0:
            record['exit_code'] = 2
        records.append(record)
        if xml.exists():
            junit.append(xml)
        print(json.dumps({'case': tests or ['complete suite'], **record}), flush=True)
    if args.mode == 'modules' and junit:
        merge_junit(junit, output / 'tests.xml')
    code = 124 if any(r['exit_code'] == 124 for r in records) else int(any(r['exit_code'] for r in records))
    metadata = {'root': str(root), 'mode': args.mode, 'exit_code': code,
                'modules_discovered': len(modules), 'cases_executed': len(records),
                'seconds': time.monotonic() - started, 'records': records,
                'runner_max_rss_mib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
                'network': 'offline Python/native curl guard; Docker --network none is the OS boundary'}
    try:
        metadata['container_memory_peak_bytes'] = int(Path('/sys/fs/cgroup/memory.peak').read_text())
    except (OSError, ValueError):
        pass
    (output / 'run.json').write_text(json.dumps(metadata, indent=2) + '\n')
    summary = ['# Isolated Python results', '', f'Mode: {args.mode}; exit: {code}', '',
               '| Case | Exit | Seconds | Sampled pytest MaxRSS MiB |', '|---|---:|---:|---:|']
    summary.extend(f"| {','.join(r['tests']) or 'complete suite'} | {r['exit_code']} | {r.get('seconds', 0):.2f} | {r.get('sampled_pytest_max_rss_mib', 0):.2f} |" for r in records)
    (output / 'summary.md').write_text('\n'.join(summary) + '\n')
    print(json.dumps({k: v for k, v in metadata.items() if k != 'records'}))
    raise SystemExit(code)


if __name__ == '__main__':
    main()
