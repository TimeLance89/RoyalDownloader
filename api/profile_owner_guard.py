"""Reject stale browser-profile requests after a shared login cookie changes."""
from fastapi import HTTPException


def require_profile_owner(headers, user_id: str) -> None:
    expected = str(headers.get("x-royal-profile") or headers.get("X-Royal-Profile") or "")
    if expected and expected != user_id:
        raise HTTPException(409, {"code": "profile_changed",
                                  "message": "Das angemeldete Profil hat sich geändert. Bitte lade die Seite neu."})
