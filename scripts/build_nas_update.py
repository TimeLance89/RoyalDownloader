#!/usr/bin/env python3
"""Build a self-contained, copyable NAS update bundle from a Git revision."""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
REQUIRED_FILES = (
    "Dockerfile",
    "docker-compose.yml",
    "docker_bootstrap.py",
    "server.py",
    "self_updater.py",
    "update_checker.py",
    "scripts/nas_update_install.sh",
)


def _git(*arguments: str, text: bool = True) -> str | bytes:
    return subprocess.check_output(
        ["git", *arguments],
        cwd=ROOT,
        text=text,
    )


def resolve_commit(reference: str) -> str:
    commit = str(_git("rev-parse", f"{reference}^{{commit}}")).strip().lower()
    if not COMMIT_RE.fullmatch(commit):
        raise RuntimeError(f"Ungültige Git-Revision: {reference}")
    return commit


def _write_payload(
    reference: str,
    commit: str,
    destination: Path,
    source_root: Path | None = None,
) -> tuple[Path, list[str]]:
    source = destination / "source"
    source.mkdir()
    if source_root is None:
        archive = destination / "source.tar"
        subprocess.run(
            ["git", "archive", "--format=tar", f"--output={archive}", reference],
            cwd=ROOT,
            check=True,
        )
        with tarfile.open(archive, "r:") as bundle:
            bundle.extractall(source, filter="data")
    else:
        source_root = source_root.resolve()
        listed = subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=source_root,
        ).decode("utf-8").split("\0")
        for relative in filter(None, listed):
            origin = source_root.joinpath(*Path(relative).parts)
            if not origin.is_file() or not origin.resolve().is_relative_to(source_root):
                continue
            target = source.joinpath(*Path(relative).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, target)
    for required in REQUIRED_FILES:
        if not (source / required).is_file():
            raise RuntimeError(f"NAS-Paket unvollständig: {required} fehlt")

    (source / ".app_commit_sha").write_text(commit + "\n", encoding="utf-8")
    managed_files = sorted(
        path.relative_to(source).as_posix()
        for path in source.rglob("*")
        if path.is_file()
    )
    managed_files.extend([".app_commit_sha", ".nas_managed_files"])
    managed_files = sorted(set(managed_files))
    (source / ".nas_managed_files").write_text(
        "\n".join(managed_files) + "\n",
        encoding="utf-8",
    )

    payload = destination / "payload.tar.gz"
    with tarfile.open(payload, "w:gz") as bundle:
        for path in sorted(source.rglob("*")):
            bundle.add(path, arcname=path.relative_to(source).as_posix(), recursive=False)
    return payload, managed_files


def build_bundle(
    reference: str,
    output: Path | None = None,
    source_root: Path | None = None,
) -> Path:
    commit = resolve_commit(reference)
    output = output or ROOT / "dist" / f"RoyalDownloader-NAS-Update-{commit[:12]}.tar.gz"
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="royal-nas-bundle-") as temporary:
        staging = Path(temporary)
        payload, _managed_files = _write_payload(
            reference,
            commit,
            staging,
            source_root=source_root,
        )
        digest = hashlib.sha256(payload.read_bytes()).hexdigest()
        installer = ROOT / "scripts" / "nas_update_install.sh"
        with tarfile.open(output, "w:gz") as bundle:
            bundle.add(installer, arcname="install.sh")
            bundle.add(payload, arcname="payload.tar.gz")
            for name, content in (
                ("commit.txt", commit + "\n"),
                ("payload.sha256", digest + "\n"),
            ):
                generated = staging / name
                generated.write_text(content, encoding="utf-8")
                bundle.add(generated, arcname=name)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="HEAD", help="Git-Revision für das Paket")
    parser.add_argument("--output", type=Path, help="Zielpfad der tar.gz-Datei")
    args = parser.parse_args()
    bundle = build_bundle(args.ref, args.output)
    print(bundle)


if __name__ == "__main__":
    main()
