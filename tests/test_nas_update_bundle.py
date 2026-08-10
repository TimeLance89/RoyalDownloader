import hashlib
import importlib.util
import os
import subprocess
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "scripts" / "build_nas_update.py"


def _builder_module():
    spec = importlib.util.spec_from_file_location("build_nas_update", BUILDER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_nas_bundle_contains_verified_source_without_persistent_data(tmp_path):
    builder = _builder_module()
    commit = builder.resolve_commit("HEAD")
    output = builder.build_bundle(
        "HEAD",
        tmp_path / "nas-update.tar.gz",
        source_root=ROOT,
    )

    with tarfile.open(output, "r:gz") as outer:
        assert set(outer.getnames()) == {
            "install.sh", "payload.tar.gz", "payload.sha256", "commit.txt",
        }
        payload = outer.extractfile("payload.tar.gz").read()
        expected_hash = outer.extractfile("payload.sha256").read().decode().strip()
        assert hashlib.sha256(payload).hexdigest() == expected_hash
        assert outer.extractfile("commit.txt").read().decode().strip() == commit
        payload_path = tmp_path / "payload.tar.gz"
        payload_path.write_bytes(payload)

    with tarfile.open(payload_path, "r:gz") as inner:
        names = set(inner.getnames())
        assert inner.extractfile(".app_commit_sha").read().decode().strip() == commit
        assert {"server.py", "Dockerfile", "docker-compose.yml"} <= names
        assert not any(name == ".env" or name.startswith(("data/", "runtime/")) for name in names)


@pytest.mark.skipif(os.name == "nt", reason="Bash-Syntaxprüfung läuft in Linux-CI")
def test_nas_installer_has_valid_bash_syntax():
    subprocess.run(
        ["bash", "-n", str(ROOT / "scripts" / "nas_update_install.sh")],
        check=True,
    )
