"""Shared, fail-closed translation for second-factor authentication."""
from fastapi import HTTPException

from core.totp import TotpError


def totp_error(error):
    return HTTPException(error.status, {"code": error.code, "message": str(error)},
                         headers={"Retry-After": str(error.retry_after)} if error.retry_after else None)


def verify_second_factor(dependencies, user, code):
    if not user or not user.get("mfa", {}).get("enabled"):
        return {}
    if dependencies.mfa is None:
        raise HTTPException(503, "2FA-Prüfung nicht verfügbar.")
    try:
        epoch = dependencies.mfa.verify(str(user["id"]), code)
    except TotpError as exc:
        raise totp_error(exc) from exc
    return {"auth_epoch": epoch}
