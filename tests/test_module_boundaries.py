from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_composition_root_does_not_take_back_http_routes():
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    route_decorators = (
        "@app.get(",
        "@app.post(",
        "@app.put(",
        "@app.delete(",
        "@app.websocket(",
    )
    assert not any(decorator in server for decorator in route_decorators)


def test_modularized_entrypoints_stay_small():
    assert _line_count(ROOT / "server.py") < 1_000
    assert _line_count(ROOT / "web" / "app.js") < 700
    assert _line_count(ROOT / "web" / "style.css") < 50


def test_application_services_stay_focused():
    services = list((ROOT / "application_services").glob("*.py"))
    assert len(services) >= 10
    assert max(map(_line_count, services)) < 1_250


def test_frontend_feature_files_do_not_become_new_monoliths():
    javascript = list((ROOT / "web" / "screens").glob("*.js"))
    stylesheets = list((ROOT / "web" / "styles").glob("*.css"))
    assert javascript and stylesheets
    assert max(map(_line_count, javascript)) < 1_800
    assert max(map(_line_count, stylesheets)) < 2_300
