"""Run an isolated, offline suite with per-test and whole-process timeouts."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=900)
    parser.add_argument('--test-timeout', type=int, default=30)
    parser.add_argument('tests', nargs='*')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = {key: value for key, value in os.environ.items() if 'proxy' not in key.lower()}
    env['PYTHONPATH'] = str(Path(__file__).resolve().parent)
    # A dedicated checkout owns all state; do not override fixtures' local paths.
    env['SERIENDL_DATA_DIR'] = ''
    command = [sys.executable, '-m', 'pytest', '-p', 'offline_guard', '-q',
               f'--timeout={args.test_timeout}', '--durations=20',
               f'--junitxml={output / "tests.xml"}', *args.tests]
    started = time.monotonic()
    # Fixture media needs the real test disk's free-space accounting. The
    # container's small /tmp tmpfs must not make the 5 GiB reserve guard fail.
    with tempfile.TemporaryDirectory(prefix='stability-fixtures-', dir=output.parent) as fixture_tmp, (output / 'tests.log').open('w') as log:
        env['TMPDIR'] = fixture_tmp
        try:
            result = subprocess.run(command, cwd=args.root.resolve(), env=env,
                                    stdout=log, stderr=subprocess.STDOUT, timeout=args.timeout)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
    metadata = {'command': command, 'root': str(args.root.resolve()), 'exit_code': code,
                'seconds': time.monotonic() - started,
                'network': 'synthetic DNS; external Python sockets/native curl denied; run container with --network none'}
    (output / 'run.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(json.dumps(metadata))
    raise SystemExit(code)


if __name__ == '__main__':
    main()
