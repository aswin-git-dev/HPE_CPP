from __future__ import annotations

import contextvars
import uuid
from typing import Callable, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


request_id_ctx_var: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("request_id", default=None)


def get_request_id() -> Optional[str]:
    return request_id_ctx_var.get()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    Adds/propagates X-Request-ID for correlation across microservices.
    """

    def __init__(self, app, header_name: str = "X-Request-ID") -> None:
        super().__init__(app)
        self.header_name = header_name

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        rid = request.headers.get(self.header_name) or str(uuid.uuid4())
        token = request_id_ctx_var.set(rid)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx_var.reset(token)

        response.headers[self.header_name] = rid
        return response

