from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api import health_router, ingest_router, metrics_router, stats_router
from app.core.config import get_settings
from app.core.logging_config import setup_logging
from app.middleware.exception_handler import ExceptionHandlingMiddleware
from app.middleware.request_context import RequestContextMiddleware, get_request_id
from app.services import Normalizer, OpenSearchService, RetentionService, StatsService, TaggingService


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = logging.getLogger("audit-service")

    app = FastAPI(
        title="Audit Microservice",
        version="1.0.0",
        description="Collects, normalizes, filters, tags, and stores security events in OpenSearch.",
    )

    # Middleware
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(ExceptionHandlingMiddleware)

    # Services (simple DI via app.state, viva-friendly)
    app.state.normalizer = Normalizer()
    app.state.tagging_service = TaggingService()
    app.state.stats_service = StatsService()
    app.state.retention_service = RetentionService(settings)
    app.state.opensearch_service = OpenSearchService(settings)

    # Routes
    app.include_router(health_router)
    app.include_router(stats_router)
    app.include_router(metrics_router)
    app.include_router(ingest_router)

    @app.on_event("startup")
    def _startup() -> None:
        try:
            app.state.opensearch_service.ensure_index()
            logger.info("startup_ok", extra={"request_id": get_request_id(), "index": settings.opensearch_index})
        except Exception:
            logger.exception("startup_opensearch_failed")

    return app


app = create_app()

