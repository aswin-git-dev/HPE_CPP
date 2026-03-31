from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api import control_plane_router, health_router, ingest_router, metrics_router, stats_router
from app.core.config import get_settings
from app.core.logging_config import setup_logging
from app.middleware.exception_handler import ExceptionHandlingMiddleware
from app.middleware.request_context import RequestContextMiddleware
from app.services import EventStoreService, K8sMonitorService, Normalizer, RetentionService, StatsService, TaggingService


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = logging.getLogger("audit-service")

    app = FastAPI(
        title="Audit Microservice",
        version="1.0.0",
        description="Control-plane monitoring and audit event service.",
    )

    # Middleware
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(ExceptionHandlingMiddleware)

    # Services (simple DI via app.state, viva-friendly)
    app.state.normalizer = Normalizer()
    app.state.settings = settings
    app.state.tagging_service = TaggingService()
    app.state.stats_service = StatsService()
    app.state.retention_service = RetentionService(settings)
    app.state.event_store_service = EventStoreService(max_events=settings.event_store_max_events)
    app.state.k8s_monitor_service = K8sMonitorService()

    # Routes
    app.include_router(health_router)
    app.include_router(stats_router)
    app.include_router(metrics_router)
    app.include_router(ingest_router)
    app.include_router(control_plane_router)

    @app.on_event("startup")
    def _startup() -> None:
        logger.info("startup_ok")

    return app


app = create_app()

