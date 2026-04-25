from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    app = "app"
    k8s_audit = "k8s_audit"
    falco = "falco"


class Severity(str, Enum):
    info = "info"
    warning = "warning"
    critical = "critical"
    unauthorized_access = "unauthorized_access"


class NormalizedEvent(BaseModel):
    event_id: str = Field(..., description="Unique dedup hash / id for event")
    timestamp: str = Field(..., description="ISO-8601 UTC timestamp")
    source_type: SourceType

    service_name: Optional[str] = None
    namespace: Optional[str] = None
    pod_name: Optional[str] = None
    user_name: Optional[str] = None

    severity: Severity = Severity.info
    event_type: str = Field(..., description="High-level event category/type")
    message: str
    classification: Optional[str] = Field(
        default=None,
        description="Optional high-level classification (e.g. unauthorized_access)",
    )

    action: Optional[str] = None
    resource: Optional[str] = None
    resource_name: Optional[str] = None
    status_code: Optional[int] = None

    tags: List[str] = Field(default_factory=list)
    raw_event: Dict[str, Any] = Field(default_factory=dict)


class IngestResponse(BaseModel):
    accepted: int
    stored: int
    dropped: int
    failed: int
    sample_event_ids: List[str] = Field(default_factory=list)

