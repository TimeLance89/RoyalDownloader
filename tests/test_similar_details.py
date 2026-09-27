import threading
import time
from types import SimpleNamespace
import asyncio

import pytest
import server  # noqa: F401 - initializes runtime publication
from application_services import movie_catalog
from api import api_discovery_router as router
from fastapi import HTTPException


def test_interactive_provider_deadline_keeps_fast_success_and_isolates_errors():
    release = threading.Event()
    def slow():
        release.wait(1)
        return 'slow'
    def broken():
        raise RuntimeError('Cloudflare 520')
    started = time.monotonic()
    try:
        results = dict(movie_catalog._bounded_movie_details([
            ('slow', slow), ('broken', broken), ('fast', lambda: 'available'),
        ], 0.05))
        assert time.monotonic() - started < 0.5
        assert results == {'fast': 'available'}
    finally:
        release.set()


@pytest.mark.parametrize('error,code,status', [
    (LookupError('No source'), 'movie_hoster_unavailable', 404),
    (RuntimeError('Cloudflare origin invalid'), 'movie_provider_unavailable', 502),
])
def test_provider_failure_contract_never_exposes_origin_response(monkeypatch, error, code, status):
    monkeypatch.setattr(router, 'state', SimpleNamespace(fp_movies={}))
    def fail(_slug):
        raise error
    monkeypatch.setattr(router, 'load_movie_for_slug', fail)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(router.api_movie('tmdb:42'))
    assert caught.value.status_code == status
    assert caught.value.detail['code'] == code
    assert 'Cloudflare' not in caught.value.detail['message']


def test_similar_series_metadata_uses_explicit_identity_without_provider(monkeypatch):
    calls = []
    def by_id(tmdb_id, title):
        calls.append((tmdb_id, title))
        return {'tmdb_id': tmdb_id, 'title': title, 'description': 'Full metadata'}
    monkeypatch.setattr(router, 'get_tmdb_client', lambda: SimpleNamespace(configured=True, series_by_id=by_id))
    response = asyncio.run(router.api_tmdb_series(router.SeriesMetadataBody(items=[
        router.SeriesMetadataItem(base_slug='identity-923841', title='Same name', tmdb_id=923841),
    ])))
    assert calls == [(923841, 'Same name')]
    assert response['series']['identity-923841']['description'] == 'Full metadata'


def test_direct_provider_error_does_not_prevent_identity_fallback(monkeypatch):
    calls = []
    movie = SimpleNamespace(hosters=['available'])
    def load(slug):
        calls.append(slug)
        if slug != 'tmdb:42':
            raise RuntimeError('Cloudflare 520')
        return movie
    monkeypatch.setattr(router, 'state', SimpleNamespace(fp_movies={}))
    monkeypatch.setattr(router, 'load_movie_for_slug', load)
    monkeypatch.setattr(router, 'movie_detail_to_dict', lambda slug, movie: {'slug': slug, 'hosters': movie.hosters})
    assert asyncio.run(router.api_movie('provider:title', tmdb_id=42))['hosters'] == ['available']
    assert calls == ['provider:title', 'tmdb:42']
