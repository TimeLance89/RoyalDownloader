"""Browsable inventory for the currently linked Jellyfin profile."""

from typing import Literal
from uuid import UUID

from fastapi import HTTPException, Query, Request

from core import egress_requests as requests
from integrations.jellyfin_auth import jellyfin_auth_headers
from integrations.jellyfin_permissions import JellyfinPermissionError, require_jellyfin_item


KINDS = {"movie": "Movie", "series": "Series", "collection": "BoxSet", "episode": "Episode"}
FIELDS = "Overview,ProviderIds,Genres"


def library_card(item):
    kind = next((kind for kind, value in KINDS.items() if value == item.get("Type")), None)
    if (not kind or not item.get("Name") or item.get("LocationType") in ("Virtual", "Offline")
            or item.get("IsPlaceHolder")):
        return None
    try:
        identity = UUID(item["Id"]).hex
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    data = item.get("UserData") or {}
    return {
        "id": identity, "kind": kind, "title": item["Name"], "year": item.get("ProductionYear") or "",
        "description": item.get("Overview") or "", "in_jellyfin": True,
        "has_image": bool((item.get("ImageTags") or {}).get("Primary") or item.get("BackdropImageTags")),
        "played": bool(data.get("Played")), "position_ticks": data.get("PlaybackPositionTicks") or 0,
        "tmdb_id": (item.get("ProviderIds") or {}).get("Tmdb"),
        "series_title": item.get("SeriesName") or "", "episode_title": item["Name"] if kind == "episode" else "",
        "season": item.get("ParentIndexNumber"), "episode": item.get("IndexNumber"),
    }


def register_library_routes(router, connection, linked_profile, read_json, image, access):
    def scope(request):
        active = connection(request)
        if active is None:
            raise HTTPException(503, "Jellyfin ist nicht eingerichtet.")
        config, _, base_url = active
        return base_url, config["api_key"], linked_profile(request, config)

    def read(context, path, **params):
        base_url, api_key, profile = context
        return read_json(base_url, api_key, path, {"UserId": profile, **params})

    def exact(context, item_id, types, fields=FIELDS):
        result = read(context, "/Items", Ids=item_id, IncludeItemTypes=",".join(types),
                      Recursive="true", Limit=1, Fields=fields, EnableUserData="true")
        try:
            return require_jellyfin_item(result, item_id, types=types)
        except JellyfinPermissionError as error:
            raise HTTPException(error.status, str(error)) from None

    def page(result, offset, limit, types):
        raw = result.get("Items") or []
        cards = [card for item in raw if isinstance(item, dict) and item.get("Type") in types
                 if (card := library_card(item)) is not None]
        total = result.get("TotalRecordCount")
        end = offset + len(raw)
        more = bool(raw) and (end < total if isinstance(total, int) else len(raw) >= limit)
        return {"items": cards, "next_offset": end if more else None}

    @router.get("/api/media-center/library")
    def library(request: Request, kind: Literal["movie", "series", "collection"],
                sort: Literal["title", "recent"] = "title",
                search: str = Query("", max_length=150),
                offset: int = Query(0, ge=0), limit: int = Query(36, ge=1, le=60)):
        context = scope(request)
        types = (KINDS[kind],)
        params = {"SearchTerm": search.strip()} if search.strip() else {}
        result = read(context, "/Items", IncludeItemTypes=types[0], Recursive="true",
                      SortBy="DateCreated,SortName" if sort == "recent" else "SortName",
                      SortOrder="Descending" if sort == "recent" else "Ascending",
                      StartIndex=offset, Limit=limit, Fields=FIELDS, EnableUserData="true",
                      ExcludeLocationTypes="Virtual,Offline", IsMissing="false", IsPlaceHolder="false",
                      CollapseBoxSetItems="false", **params)
        return page(result, offset, limit, types)

    @router.get("/api/media-center/library/{item_id}/children")
    def library_children(request: Request, item_id: UUID, offset: int = Query(0, ge=0),
                         limit: int = Query(36, ge=1, le=60)):
        context = scope(request)
        parent = exact(context, item_id.hex, ("Series", "BoxSet"))
        common = dict(StartIndex=offset, Limit=limit, Fields=FIELDS, EnableUserData="true", IsMissing="false")
        if parent["Type"] == "Series":
            types = ("Episode",)
            result = read(context, f"/Shows/{item_id.hex}/Episodes", **common)
        else:
            types = ("Movie", "Series", "BoxSet")
            result = read(context, "/Items", ParentId=item_id.hex, IncludeItemTypes=",".join(types),
                          SortBy="PremiereDate,SortName", SortOrder="Ascending", **common)
        return page(result, offset, limit, types)

    @router.get("/api/media-center/library/{item_id}/image")
    def library_image(request: Request, item_id: UUID, style: Literal["poster", "wide"] = "poster"):
        context = scope(request)
        item = exact(context, item_id.hex, tuple(KINDS.values()))
        image_type = "Primary"
        if item.get("BackdropImageTags") and (style == "wide" or not (item.get("ImageTags") or {}).get("Primary")):
            image_type = "Backdrop"
        return image(context[0], context[1], item_id.hex, image_type)

    @router.delete("/api/media-center/library/{item_id}")
    def library_delete(request: Request, item_id: UUID, kind: Literal["movie", "series", "episode"]):
        if access.context(request).role != "admin":
            raise HTTPException(403, "Administratorrechte erforderlich.")
        context = scope(request)
        item = exact(context, item_id.hex, (KINDS[kind],), "CanDelete")
        if item.get("CanDelete") is not True:
            raise HTTPException(403, "Das verknüpfte Jellyfin-Profil darf diesen Inhalt nicht löschen.")
        access.assert_current(request)
        base_url, api_key, _ = context
        try:
            with requests.delete(f"{base_url}/Items/{item_id.hex}",
                                 headers=jellyfin_auth_headers(api_key), timeout=(5, 25),
                                 allow_redirects=False) as response:
                if response.status_code == 204:
                    return {"deleted": True}
                if response.status_code in (401, 403):
                    raise HTTPException(403, "Jellyfin hat das Löschen verweigert.")
                if response.status_code == 404:
                    raise HTTPException(404, "Der Inhalt ist in Jellyfin nicht mehr vorhanden.")
        except requests.RequestException:
            raise HTTPException(503, "Jellyfin hat das Löschen nicht bestätigt. Prüfe die Mediathek.") from None
        raise HTTPException(502, "Jellyfin hat das Löschen nicht bestätigt. Prüfe die Mediathek.")
