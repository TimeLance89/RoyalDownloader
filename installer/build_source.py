"""Create reproducible source payloads from the exact checked-out Git commit.

Run on the GitHub Actions checkout before PyInstaller, not from local user files.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

try:
    from installer.core import sha256_file, verify_source_tar
except ModuleNotFoundError:
    from core import sha256_file, verify_source_tar


def build(repo: Path):
    repo = repo.resolve()
    assets = repo / "installer" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    if len(commit) != 40:
        raise RuntimeError("invalid Git SHA")
    for filename, fmt in (("royal-source.zip", "zip"), ("royal-source.tar.gz", "tar.gz")):
        # Do not include the untracked manifest/archives; git archive includes only committed source.
        subprocess.run(["git", "archive", f"--format={fmt}", f"--output={assets / filename}", "HEAD"],
                       cwd=repo, check=True)
    verify_source_tar(assets / "royal-source.tar.gz")
    manifest = {
        "ref": "stable" if __import__("os").environ.get("GITHUB_EVENT_NAME") == "release" else "overnight",
        "commit": commit,
        "archives": {
            name: sha256_file(assets / name)
            for name in ("royal-source.zip", "royal-source.tar.gz")
        },
    }
    (assets / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    build(Path(__file__).resolve().parents[1])
