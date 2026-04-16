from __future__ import annotations

import logging
import threading
import time

from fastapi import FastAPI

from app.api import control_plane_router, health_router, ingest_router, metrics_router, stats_router
from app.core.config import get_settings
from app.core.logging_config import setup_logging
from app.middleware.exception_handler import ExceptionHandlingMiddleware
from app.middleware.request_context import RequestContextMiddleware
from app.services import EventStoreService, K8sMonitorService, Normalizer, RetentionService, StatsService, TaggingService
from app.services.opensearch_service import OpenSearchService


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
    app.state.event_store_service = EventStoreService(
        max_events=settings.event_store_max_events,
        ttl_seconds=settings.event_store_ttl_seconds,
    )
    app.state.k8s_monitor_service = K8sMonitorService()
    app.state.opensearch_service = None

    # Routes
    app.include_router(health_router)
    app.include_router(stats_router)
    app.include_router(metrics_router)
    app.include_router(ingest_router)
    app.include_router(control_plane_router)

    @app.on_event("startup")
    def _startup() -> None:
        logger.info("startup_ok")
        ost: OpenSearchService | None = None
        if settings.opensearch_enabled and settings.opensearch_url:
            try:
                cand = OpenSearchService(settings)
                if cand.ping():
                    cand.ensure_index()
                    ost = cand
                    logger.info("opensearch_ready", extra={"index": settings.opensearch_index})
                else:
                    logger.warning("opensearch_unreachable", extra={"url": settings.opensearch_url})
            except Exception as e:
                logger.warning("opensearch_init_failed: %s", e)
        app.state.opensearch_service = ost

        def _ttl_purge_loop(svc: OpenSearchService) -> None:
            if settings.opensearch_events_ttl_days <= 0:
                return
            interval_s = max(1800, int(settings.opensearch_purge_interval_hours * 3600))
            time.sleep(90)
            while True:
                try:
                    n = svc.purge_older_than(settings.opensearch_events_ttl_days)
                    if n:
                        logger.info("opensearch_ttl_purge", extra={"deleted": n, "days": settings.opensearch_events_ttl_days})
                except Exception:
                    logger.exception("opensearch_ttl_purge_failed")
                time.sleep(interval_s)

        if ost and settings.opensearch_events_ttl_days > 0:
            threading.Thread(target=_ttl_purge_loop, args=(ost,), daemon=True).start()

    return app


app = create_app()

