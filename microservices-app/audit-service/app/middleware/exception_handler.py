from __future__ import annotations

import logging
from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.middleware.request_context import get_request_id


logger = logging.getLogger("audit-service.exceptions")


class ExceptionHandlingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable):
        try:
            return await call_next(request)
        except Exception as exc:
            rid = get_request_id()
            logger.exception(
                "unhandled_exception",
                extra={"request_id": rid, "path": str(request.url.path), "method": request.method},
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_server_error",
                    "request_id": rid,
                    "detail": str(exc),
                },
            )

