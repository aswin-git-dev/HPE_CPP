from .routes.health import router as health_router
from .routes.ingest import router as ingest_router
from .routes.metrics import router as metrics_router
from .routes.stats import router as stats_router

__all__ = ["health_router", "ingest_router", "metrics_router", "stats_router"]

