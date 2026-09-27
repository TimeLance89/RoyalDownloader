"""Release payload compatibility with already-installed pre-module updaters."""

import tarfile
from pathlib import Path

import pytest

from updates.self_updater import SelfUpdater


ROOT = Path(__file__).resolve().parents[1]
# Frozen contract from overnight 7d93908. Updating the new validator cannot
# change the validator that users must pass before installing this release.
LEGACY_REQUIRED_FILES = (
    "server.py", "core/app_version.py", "application_services/__init__.py",
    "application_services/runtime.py", "requirements.txt", "requirements.lock",
    "integrations/ui_translator.py", "updates/ytdlp_updater.py",
    "web/app.js", "web/i18n.js", "updates/update_checker.py",
    "updates/update_channels.py", "providers/__init__.py", "providers/catalog.py",
    "providers/models.py", "providers/filmfrei24.py", "providers/filmpalast.py",
    "providers/moflix.py", "providers/einschalten.py", "providers/kinox.py",
    "providers/kinoger.py", "providers/megakino.py", "providers/xcine.py",
    "providers/serienstream.py",
)


@pytest.mark.parametrize("omit_compatibility_file", [False, True])
def test_frontend_payload_passes_installed_updater_validation(tmp_path, omit_compatibility_file):
    archive = tmp_path / "update.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        for name in LEGACY_REQUIRED_FILES:
            if omit_compatibility_file and name == "web/i18n.js":
                continue
            bundle.add(ROOT / name, arcname=f"release/{name}", recursive=False)
        for name in ("web/index.html", "web/js/core/localization.js"):
            bundle.add(ROOT / name, arcname=f"release/{name}", recursive=False)

    updater = SelfUpdater("owner/repo", tmp_path / "installed", persistent_override=True)
    destination = tmp_path / "extracted"
    if omit_compatibility_file:
        with pytest.raises(RuntimeError, match=r"web/i18n\.js fehlt"):
            updater._extract_archive(archive, destination)
        return

    root = updater._extract_archive(archive, destination)
    assert all((root / name).is_file() for name in LEGACY_REQUIRED_FILES)
    assert 'src="/i18n.js' not in (root / "web/index.html").read_text(encoding="utf-8")
    assert "export function createLocalization" in (
        root / "web/js/core/localization.js"
    ).read_text(encoding="utf-8")
