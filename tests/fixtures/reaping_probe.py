"""Offline Linux tree stress probe, also executed under the image's real Tini."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from core.owned_process import spawn, stop

PARENT = '''
import os,signal,subprocess,sys,time
signal.signal(signal.SIGTERM,signal.SIG_IGN)
code = "import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
code += "os.setsid(); time.sleep(.05)" if sys.argv[1]=='detached' else "time.sleep(60)"
child=subprocess.Popen([sys.executable,'-c',code])
print(child.pid,flush=True)
time.sleep(60)
'''


def main():
    foreign = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        for index in range(12):
            parent = spawn(subprocess.Popen, [sys.executable, '-c', PARENT, 'detached' if index % 2 else 'group'],
                           stdout=subprocess.PIPE, text=True)
            grandchild = int(parent.stdout.readline())
            try:
                assert stop(parent, timeout=.2)
                assert foreign.poll() is None
                deadline = time.monotonic() + 2
                while Path(f'/proc/{grandchild}').exists() and time.monotonic() < deadline:
                    if '--reap-adopted' in sys.argv:
                        try:
                            os.waitpid(grandchild, os.WNOHANG)
                        except ChildProcessError:
                            pass
                    time.sleep(.01)
                assert not Path(f'/proc/{grandchild}').exists(), 'Owned descendant was not reaped'
            finally:
                stop(parent, timeout=.1)
                parent.stdout.close()
        print('reaping-ok: 12 trees, no residual descendants, foreign child unaffected')
    finally:
        foreign.terminate()
        foreign.wait(timeout=3)


if __name__ == '__main__':
    main()
