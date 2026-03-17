from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class AppLogIn(BaseModel):
    # Optional app-provided id/timestamp
    event_id: Optional[str] = None
    timestamp: Optional[str] = None

    service_name: Optional[str] = None
    namespace: Optional[str] = None
    pod_name: Optional[str] = None

    request_path: Optional[str] = None
    method: Optional[str] = None
    status_code: Optional[int] = None
    response_time: Optional[float] = None

    log_level: Optional[str] = Field(default=None, description="debug|info|warning|error|critical")
    message: str

    extra: Dict[str, Any] = Field(default_factory=dict, description="Any extra fields from app log")

