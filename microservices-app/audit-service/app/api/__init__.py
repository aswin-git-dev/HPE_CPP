from .routes.control_plane import router as control_plane_router
from .routes.health import router as health_router
from .routes.ingest import router as ingest_router
from .routes.metrics import router as metrics_router
from .routes.stats import router as stats_router

__all__ = ["control_plane_router", "health_router", "ingest_router", "metrics_router", "stats_router"]

