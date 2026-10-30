import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api import api_administration_router as router
from core import config


@pytest.mark.parametrize("stored,expected", [(None, True), ("1", True), ("0", False), ("false", False), ("off", False)])
def test_event_preference_default_and_existing_installations(monkeypatch, stored, expected):
    monkeypatch.setattr(config, "_read_all", lambda: {} if stored is None else {"seasonal_events_enabled": stored})
    assert config.load_seasonal_events_enabled() is expected


def test_event_preference_save_does_not_replace_other_settings(monkeypatch):
    values = {"ui_language": "en", "save_path": "fixture"}
    monkeypatch.setattr(config, "_read_all", lambda: dict(values))
    def update(changes):
        values.update(changes)
        return True
    monkeypatch.setattr(config, "_update_all", update)
    assert config.save_seasonal_events_enabled(False)
    assert config.load_seasonal_events_enabled() is False
    assert values["ui_language"] == "en"
    assert values["save_path"] == "fixture"


def test_event_preference_persists_on_disk(monkeypatch, tmp_path):
    path = tmp_path / "settings.ini"
    path.write_text("ui_language=en\nsave_path=fixture\n", encoding="utf-8")
    monkeypatch.setattr(config, "_config_file", lambda: path)
    monkeypatch.setattr(config, "_config_dir", lambda: tmp_path)
    assert config.save_seasonal_events_enabled(False)
    assert config.load_seasonal_events_enabled() is False
    assert config._read_all()["ui_language"] == "en"
    assert config.save_seasonal_events_enabled(True)
    assert config.load_seasonal_events_enabled() is True


def test_event_api_reads_and_writes_preference(monkeypatch):
    save = Mock(return_value=True)
    monkeypatch.setattr(router, "appconfig", SimpleNamespace(load_seasonal_events_enabled=lambda: False,
                        save_seasonal_events_enabled=save))
    assert asyncio.run(router.api_ui_events_get()) == {"enabled": False}
    assert asyncio.run(router.api_ui_events_set(router.UIEventsBody(enabled=True))) == {"enabled": True,"saved": True}
    save.assert_called_once_with(True)


def test_event_api_reports_failed_persistence(monkeypatch):
    monkeypatch.setattr(router, "appconfig", SimpleNamespace(save_seasonal_events_enabled=lambda _: False))
    with pytest.raises(HTTPException) as error:
        asyncio.run(router.api_ui_events_set(router.UIEventsBody(enabled=False)))
    assert error.value.status_code == 500


@pytest.mark.parametrize("value", ["false", "true", 1, None])
def test_event_api_requires_a_boolean(value):
    with pytest.raises(ValidationError):
        router.UIEventsBody(enabled=value)
