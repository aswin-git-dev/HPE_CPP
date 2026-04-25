from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings


router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    settings = get_settings()
    return {"status": "ok", "service": settings.app_name, "env": settings.env}

