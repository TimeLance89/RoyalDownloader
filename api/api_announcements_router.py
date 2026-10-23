"""HTTP boundaries for signed Royal announcements.

No local household administrator becomes a global publisher. Authorization
requires the official server's private signing key AND the configured owner.
"""
from __future__ import annotations

import uuid
import time
import threading

from core.proxy_security import client_ip

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from application_services import announcements

_receipt_rate_lock = threading.Lock()
_receipt_rate = {}


class PublisherMessage(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=3000)
    category: str = Field(default="news", pattern="^(news|event|important)$")
    expires_at: int = Field(default=0, ge=0)


class EnabledSetting(BaseModel):
    enabled: bool


class Receipt(BaseModel):
    id: str = Field(min_length=36, max_length=36)
    profile: str = Field(min_length=32, max_length=32)
    kind: str = Field(pattern="^(delivered|read)$")


class ReceiptBatch(BaseModel):
    installation: str = Field(min_length=36, max_length=36)
    items: list[Receipt] = Field(max_length=50)


def create_announcements_router(current_user):
    router = APIRouter(tags=["announcements"])

    def user(request: Request) -> dict:
        identity = current_user(request.headers, request.cookies)
        if not identity:
            raise HTTPException(401, "Anmeldung erforderlich.")
        return identity

    def owner(request: Request) -> dict:
        identity = user(request)
        host = request.headers.get("host", "").split(":", 1)[0].casefold()
        if host != "royal-downloader.de" or not announcements.is_publisher_owner(identity):
            raise HTTPException(403, "Nur der offizielle Royal-Betreiber darf veröffentlichen.")
        return identity

    @router.get("/api/announcements")
    async def inbox(request: Request):
        identity = user(request)
        return await run_in_threadpool(announcements.inbox, str(identity["id"]))

    @router.get("/api/announcements/settings")
    async def settings(request: Request):
        user(request)
        return {"enabled": await run_in_threadpool(announcements.enabled)}

    @router.post("/api/announcements/settings")
    async def change_settings(request: Request, body: EnabledSetting):
        identity = user(request)
        if identity.get("role") != "admin":
            raise HTTPException(403, "Administratorrechte erforderlich.")
        await run_in_threadpool(announcements.set_enabled, body.enabled)
        return {"enabled": body.enabled}

    @router.post("/api/announcements/{message_id}/read")
    async def mark_read(message_id: str, request: Request):
        identity = user(request)
        try:
            uuid.UUID(message_id)
            await run_in_threadpool(announcements.mark_read, str(identity["id"]), message_id)
        except (ValueError, AttributeError) as exc:
            raise HTTPException(404, "Ankündigung nicht gefunden.") from exc
        return {"read": True}

    @router.get("/api/announcements/admin/status")
    async def admin_status(request: Request):
        identity = user(request)
        host = request.headers.get("host", "").split(":", 1)[0].casefold()
        return {"can_publish": host == "royal-downloader.de" and announcements.is_publisher_owner(identity)}

    @router.get("/api/announcements/admin/messages")
    async def admin_messages(request: Request):
        owner(request)
        return {"items": await run_in_threadpool(announcements.statistics)}

    @router.post("/api/announcements/admin/messages")
    async def create_message(body: PublisherMessage, request: Request):
        owner(request)
        try:
            message = await run_in_threadpool(
                announcements.publish, body.title, body.body, body.category, body.expires_at
            )
        except (ValueError, PermissionError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return message

    @router.post("/api/announcements/admin/messages/{message_id}/revoke")
    async def revoke_message(message_id: str, request: Request):
        owner(request)
        try:
            uuid.UUID(message_id)
            await run_in_threadpool(announcements.revoke, message_id)
        except (ValueError, PermissionError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"revoked": True}

    # No session needed to pull public, signed announcements. Every recipient
    # checks the embedded Ed25519 signature against its pinned public key.
    @router.get("/api/public/announcements/feed")
    async def signed_feed():
        if not announcements.publisher_ready():
            raise HTTPException(404, "Kein offizieller Announcement-Feed.")
        return await run_in_threadpool(announcements.feed)

    @router.post("/api/public/announcements/receipts")
    async def receipt_batch(body: ReceiptBatch, request: Request):
        now = int(time.monotonic() // 60)
        source = client_ip(request)
        with _receipt_rate_lock:
            if len(_receipt_rate) > 2000:
                _receipt_rate.clear()
            minute, count = _receipt_rate.get(source, (now, 0))
            count = count + 1 if minute == now else 1
            _receipt_rate[source] = (now, count)
        if count > 120:
            raise HTTPException(429, "Zu viele Empfangsbestätigungen.")
        if not announcements.publisher_ready():
            raise HTTPException(404, "Kein offizieller Announcement-Feed.")
        try:
            await run_in_threadpool(
                announcements.accept_receipts, body.installation,
                [item.model_dump() for item in body.items],
            )
        except ValueError as exc:
            raise HTTPException(400, "Ungültiger Empfangsbeleg.") from exc
        return {"accepted": True}

    return router
