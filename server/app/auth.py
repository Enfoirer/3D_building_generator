from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException, status

from .schemas import UserProfile


@dataclass
class AuthContext:
    token: str
    profile: UserProfile


def _decode_segment(segment: str) -> Optional[dict]:
    try:
        padding = "=" * (-len(segment) % 4)
        decoded = base64.urlsafe_b64decode(segment + padding).decode("utf-8")
        return json.loads(decoded)
    except Exception:
        return None


async def get_current_user(authorization: str = Header(default=None)) -> AuthContext:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.split(" ", 1)[1].strip()
    parts = token.split(".")
    payload = _decode_segment(parts[1]) if len(parts) > 1 else None
    if payload is None:
        payload = {}

    profile = UserProfile(
        id=str(payload.get("sub") or payload.get("user_id") or "anonymous"),
        email=payload.get("email"),
        name=payload.get("name") or payload.get("nickname"),
    )

    return AuthContext(token=token, profile=profile)
