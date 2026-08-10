import api_administration_router as administration


def test_nas_container_does_not_rewrite_bundled_env(monkeypatch):
    monkeypatch.setenv("SERIENDL_DATA_DIR", "/app/data")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("NAS must not write the bundled .env")

    monkeypatch.setattr(administration, "write_project_env", fail_if_called)

    result = administration._write_deployment_environment("nas", "/movies", "/serien")

    assert result["managed_by_compose"] is True
    assert result["created"] is False


def test_desktop_still_writes_project_env(monkeypatch):
    monkeypatch.delenv("SERIENDL_DATA_DIR", raising=False)
    captured = {}

    def write(mode, movie_path, series_path):
        captured.update(mode=mode, movie_path=movie_path, series_path=series_path)
        return {"path": ".env", "created": False, "mode": mode}

    monkeypatch.setattr(administration, "write_project_env", write)

    result = administration._write_deployment_environment("desktop", "movies", "series")

    assert captured == {
        "mode": "desktop",
        "movie_path": "movies",
        "series_path": "series",
    }
    assert result["path"] == ".env"
