"""Apply egress to startup package installers without exposing proxy secrets."""

import os
import subprocess
import sys

from core.egress import get_manager
from core.environment_file import read_env
from core.network_guard import stop_safe_proxy


def main():
    for key, value in read_env().items():
        if key.startswith("ROYAL_EGRESS_"):
            os.environ.setdefault(key, value)
    try:
        env = get_manager().subprocess_environment("https://pypi.org/", untrusted=True)
        return subprocess.run(sys.argv[1:], env=env, check=False).returncode
    finally:
        stop_safe_proxy()


if __name__ == "__main__":
    sys.exit(main())
