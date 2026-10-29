"""Keep the isolated browser's guard alive for its complete process lifetime."""

import signal
import subprocess
import sys

from core.owned_process import spawn, stop
from core.egress import get_manager
from core.network_guard import stop_safe_proxy


def command(arguments):
    manager = get_manager()
    # Direct mode retains the sidecar's existing command exactly.
    return list(arguments) + (
        manager.browser_proxy_args() if manager.mode == "privacy" else []
    )


def main():
    process = None
    try:
        process = spawn(subprocess.Popen, command(sys.argv[1:]))

        def forward(signum, _frame):
            # Unwind the main wait before bounded cleanup; do not re-enter
            # Popen.wait from its signal handler while its wait lock is held.
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, forward)
        signal.signal(signal.SIGINT, forward)
        return process.wait()
    finally:
        try:
            stop(process)
        finally:
            stop_safe_proxy()


if __name__ == "__main__":
    sys.exit(main())
