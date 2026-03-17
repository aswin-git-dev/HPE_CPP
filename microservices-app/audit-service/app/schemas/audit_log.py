from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class K8sAuditObjectRef(BaseModel):
    namespace: Optional[str] = None
    resource: Optional[str] = None
    name: Optional[str] = None


class K8sAuditUser(BaseModel):
    username: Optional[str] = None
    groups: Optional[List[str]] = None


class K8sAuditResponseStatus(BaseModel):
    code: Optional[int] = None


class K8sAuditLogIn(BaseModel):
    auditID: Optional[str] = None
    requestReceivedTimestamp: Optional[str] = None
    stageTimestamp: Optional[str] = None

    verb: Optional[str] = None
    user: Optional[K8sAuditUser] = None
    objectRef: Optional[K8sAuditObjectRef] = None
    stage: Optional[str] = None
    responseStatus: Optional[K8sAuditResponseStatus] = None
    sourceIPs: Optional[List[str]] = None
    requestURI: Optional[str] = None

    annotations: Dict[str, Any] = Field(default_factory=dict)
    extra: Dict[str, Any] = Field(default_factory=dict, description="Catch-all for other audit fields")

