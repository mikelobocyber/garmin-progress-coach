from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException, status


def require_token(authorization: str | None = Header(default=None)) -> None:
    """Optional bearer-token protection.

    Local setup is intentionally easy: if APP_SECRET_TOKEN is empty, the API
    is open. Set APP_SECRET_TOKEN before exposing the app beyond your own
    machine or trusted LAN.
    """
    expected = os.getenv("APP_SECRET_TOKEN", "").strip()
    if not expected:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    provided = authorization.removeprefix("Bearer ").strip()
    # compare_digest avoids leaking the token length/prefix via timing.
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid bearer token")
