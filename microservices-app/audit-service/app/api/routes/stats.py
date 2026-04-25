from __future__ import annotations

from fastapi import APIRouter, Request


router = APIRouter(tags=["stats"])


@router.get("/stats")
def stats(request: Request):
    stats_svc = request.app.state.stats_service
    return stats_svc.snapshot()

