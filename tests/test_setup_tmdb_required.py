import asyncio

import pytest
from fastapi import HTTPException

import api_administration_router as administration


def test_setup_rejects_missing_tmdb_key():
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(administration._validate_setup_tmdb_key("", "en"))

    assert exc_info.value.status_code == 400
    assert "erforderlich" in str(exc_info.value.detail)


def test_setup_validates_tmdb_key_before_saving(monkeypatch):
    created = {}

    class FakeTMDBClient:
        def __init__(self, api_key, language):
            created.update(api_key=api_key, language=language)

        def validate(self):
            return True

    monkeypatch.setattr(administration, "TMDBClient", FakeTMDBClient)

    asyncio.run(administration._validate_setup_tmdb_key("valid-token", "en"))

    assert created == {"api_key": "valid-token", "language": "en-US"}


def test_setup_rejects_invalid_tmdb_key(monkeypatch):
    class FakeTMDBClient:
        def __init__(self, api_key, language):
            pass

        def validate(self):
            return False

    monkeypatch.setattr(administration, "TMDBClient", FakeTMDBClient)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(administration._validate_setup_tmdb_key("invalid-token", "de"))

    assert exc_info.value.status_code == 400
    assert "ungültig" in str(exc_info.value.detail)
