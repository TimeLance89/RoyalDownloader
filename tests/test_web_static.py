import gzip
import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.web_static import NoCacheStaticFiles


WEB = Path(__file__).resolve().parents[1] / "web"


def test_css_bundle_retains_exact_cascade_and_reduces_imports_to_one_response():
    assets = NoCacheStaticFiles(directory=str(WEB), html=True)
    plain, compressed = assets._stylesheet()
    manifest = (WEB / "style.css").read_text(encoding="utf-8")
    imports = re.findall(r"@import\s+url\(['\"]([^'\"]+)['\"]\);", manifest)
    assert imports
    assert any("/styles/media-center.css" in url for url in imports)
    assert any("/styles/seasonal-events.css" in url for url in imports)
    assert imports[-1].split("?", 1)[0] == "/styles/mobile.css"
    expected = manifest
    for url in imports:
        css = (WEB / url.split("?", 1)[0].lstrip("/")).read_text(encoding="utf-8")
        expected = re.sub(r"@import\s+url\(['\"]" + re.escape(url) + r"['\"]\);", lambda _: css, expected, count=1)
    assert plain.decode() == expected
    assert gzip.decompress(compressed) == plain
    assert len(compressed) < len(plain) * .3
    assert assets._stylesheet() is assets._css


def test_updated_css_and_head_compression_keep_no_store_contract(tmp_path):
    (tmp_path / "styles").mkdir()
    style = tmp_path / "styles" / "a.css"
    style.write_text(".a {color: red}", encoding="utf-8")
    (tmp_path / "style.css").write_text('@import url("/styles/a.css");', encoding="utf-8")
    app = FastAPI(); app.mount("/", NoCacheStaticFiles(directory=str(tmp_path)))
    with TestClient(app) as client:
        first = client.get("/style.css", headers={"Accept-Encoding": "gzip"})
        assert first.headers["content-encoding"] == "gzip"
        assert "no-store" in first.headers["cache-control"]
        assert first.text == ".a {color: red}"
        head = client.head("/style.css", headers={"Accept-Encoding": "gzip"})
        assert not head.content and head.headers["content-length"] == first.headers["content-length"]
        style.write_text(".a {color: green}", encoding="utf-8")
        second = client.get("/style.css", headers={"Accept-Encoding": "gzip;q=0"})
        assert "content-encoding" not in second.headers
        assert second.text == ".a {color: green}"


def test_missing_css_during_update_falls_back_to_manifest(tmp_path):
    manifest = '@import url("/styles/missing.css");'
    (tmp_path / "style.css").write_text(manifest)
    app = FastAPI(); app.mount("/", NoCacheStaticFiles(directory=str(tmp_path)))
    with TestClient(app) as client:
        assert client.get("/style.css").text == manifest
