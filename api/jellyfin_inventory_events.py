"""Authenticated Jellyfin Webhook plugin receiver for inventory changes."""

import os
import secrets
import sqlite3
from collections.abc import Callable
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from integrations.jellyfin_index import DATASETS


class JellyfinInventoryEvent(BaseModel):
    NotificationType: Literal["ItemAdded", "ItemDeleted"]
    ItemType: Literal["Movie", "Series", "Episode"]
    ItemId: UUID


def create_jellyfin_inventory_events_router(accept: Callable[[str, str], bool]) -> APIRouter:
    router = APIRouter()

    @router.post("/api/jellyfin/inventory/events", status_code=202)
    def receive_event(
        event: JellyfinInventoryEvent,
        secret: Annotated[str, Header(alias="X-Royal-Jellyfin-Secret")] = "",
    ):
        expected = os.environ.get("JELLYFIN_INVENTORY_WEBHOOK_SECRET", "").strip()
        if len(expected) < 32:
            raise HTTPException(status_code=404, detail="Jellyfin-Webhook deaktiviert")
        if not secrets.compare_digest(expected.encode(), secret.encode()):
            raise HTTPException(status_code=401, detail="Ungültiges Webhook-Secret")
        try:
            accepted = accept(DATASETS[event.ItemType], event.ItemId.hex)
        except (OSError, sqlite3.Error):
            accepted = False
        if not accepted:
            raise HTTPException(status_code=503, detail="Jellyfin-Bestandsabgleich nicht verfügbar")
        return {"accepted": True}

    return router
