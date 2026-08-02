import asyncio
import re
from pathlib import Path

from fastapi.testclient import TestClient

import server
from app_version import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_application_version_has_expected_release_candidate_value():
    assert APP_VERSION == "1.0.0-rc.1"


def test_capabilities_add_version_without_changing_health_contracts():
    client = TestClient(server.app)

    capabilities = client.get("/api/v1/capabilities").json()

    assert capabilities["application_version"] == APP_VERSION
    assert capabilities["build"] == (server.SERVER_BUILD or None)
    assert capabilities["application_version"] != capabilities["build"]
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/v1/health").json() == {
        "status": "ok", "api_version": 1,
    }


def test_frontend_renders_api_version_separately_from_build_revision():
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    account = (ROOT / "web" / "screens" / "account.js").read_text(encoding="utf-8")

    assert 'id="updater-version"' in html
    assert 'data.application_version || "unbekannt"' in account
    assert 'data.current_sha' in account
    assert APP_VERSION not in html
    assert APP_VERSION not in account


def test_updater_status_adds_version_without_replacing_revision_fields(monkeypatch):
    class Checker:
        @staticmethod
        def check(_force):
            return {"current_sha": "a" * 40, "latest_sha": "b" * 40}

    class Installer:
        @staticmethod
        def status():
            return {"state": "idle"}

    monkeypatch.setattr(server, "UPDATE_CHECKER", Checker())
    monkeypatch.setattr(server, "UPDATE_INSTALLER", Installer())

    payload = asyncio.run(server.api_updater_status(False))

    assert payload["application_version"] == APP_VERSION
    assert payload["current_sha"] == "a" * 40
    assert payload["latest_sha"] == "b" * 40


def test_release_documents_do_not_reference_another_semantic_version():
    documents = [
        ROOT / "README.md",
        ROOT / "CHANGELOG.md",
        ROOT / "docs" / "RELEASE.md",
        ROOT / "docs" / "releases" / "v1.0.0-rc.1.md",
    ]
    referenced_versions = set()
    for document in documents:
        text = document.read_text(encoding="utf-8")
        assert "v1.0.0-rc.1" in text, document
        referenced_versions.update(re.findall(r"v\d+\.\d+\.\d+-rc\.\d+", text))
    assert referenced_versions == {"v1.0.0-rc.1"}


def test_tag_release_waits_for_quality_and_publishes_only_a_prerelease():
    quality = (ROOT / ".github" / "workflows" / "quality.yml").read_text(
        encoding="utf-8",
    )
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8",
    )

    assert "workflow_call:" in quality
    assert 'branches:\n      - main' in release
    assert 'tags:\n      - "v*"' in release
    assert 'paths:\n      - app_version.py' in release
    assert "workflow_dispatch:" in release
    assert "uses: ./.github/workflows/quality.yml" in release
    assert "needs: quality" in release
    assert "Build container image" in quality
    assert "Smoke-test fresh and persistent container startup" in quality
    assert "--prerelease" in release
    assert "--verify-tag" in release
    assert 'git cat-file -t "${GITHUB_REF_NAME}"' in release
    assert 'git tag --annotate "${tag_name}" "${GITHUB_SHA}"' in release
    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in release
    assert ":latest" not in release.casefold()
    assert "--latest" not in release.casefold()
