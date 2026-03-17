from __future__ import annotations

from fastapi import APIRouter, Request, Response

from app.core.config import get_settings

try:
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
except Exception:  # pragma: no cover
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    generate_latest = None


router = APIRouter(tags=["metrics"])


@router.get("/metrics")
def metrics(request: Request):
    settings = get_settings()
    if not settings.enable_metrics:
        return Response(status_code=404, content="metrics disabled")
    if generate_latest is None:
        return Response(status_code=501, content="prometheus_client not installed")
    data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)

