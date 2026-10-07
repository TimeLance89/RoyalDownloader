"""Read-only people discovery. Downloads continue through the regular queue."""

from fastapi import APIRouter, HTTPException, Query
from starlette.concurrency import run_in_threadpool
from application_services.people_series import resolve_person_series


def create_people_router(get_client):
    router = APIRouter(tags=["discovery"])

    def client():
        value = get_client()
        if not value.configured:
            raise HTTPException(503, "Personen benötigen einen eingerichteten TMDB-Zugang.")
        return value

    @router.get("/api/v1/people")
    @router.get("/api/people")
    async def people(query: str = Query("", max_length=200), page: int = Query(1, ge=1, le=500)):
        payload = await run_in_threadpool(client().people, query, page)
        if payload is None:
            raise HTTPException(503, "TMDB ist momentan nicht erreichbar. Bitte erneut versuchen.")
        return payload

    @router.get("/api/v1/people/{person_id}")
    @router.get("/api/people/{person_id}")
    async def person(person_id: int):
        if person_id <= 0:
            raise HTTPException(400, "Ungültige Person.")
        payload = await run_in_threadpool(client().person, person_id)
        if payload is None:
            raise HTTPException(503, "Das Personenprofil konnte nicht geladen werden. Bitte erneut versuchen.")
        return {"person": payload}

    @router.get("/api/v1/people/series/{tmdb_id}")
    @router.get("/api/people/series/{tmdb_id}")
    async def series_credit(tmdb_id: int, refresh_jellyfin: bool = False, defer_checks: bool = True):
        if tmdb_id <= 0:
            raise HTTPException(400, "Ungültige Serie.")
        tmdb = client()

        def work():
            from application_services import series_catalog as catalog

            series = resolve_person_series(
                tmdb, tmdb_id, catalog.provider_priority("series"),
                catalog._search_series_for_provider, catalog._load_series_for_provider,
            )
            if series is None:
                return None
            catalog.state.series_cache[series.base_slug] = series
            return catalog.series_to_dict(series, refresh_jellyfin=refresh_jellyfin, defer_checks=defer_checks)

        payload = await run_in_threadpool(work)
        if payload is None:
            raise HTTPException(404, "Für diese Serie wurde keine passende Quelle gefunden.")
        return payload

    return router
