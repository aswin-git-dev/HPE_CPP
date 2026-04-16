from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class FalcoK8s(BaseModel):
    ns_name: Optional[str] = Field(default=None, alias="k8s.ns.name")
    pod_name: Optional[str] = Field(default=None, alias="k8s.pod.name")


class FalcoContainer(BaseModel):
    name: Optional[str] = Field(default=None, alias="container.name")
    image: Optional[str] = Field(default=None, alias="container.image")


class FalcoProc(BaseModel):
    name: Optional[str] = Field(default=None, alias="proc.name")


class FalcoAlertIn(BaseModel):
    # Falco / falcosidekick JSON shapes vary; unknown keys kept via extra='allow'.
    time: Optional[str] = None
    rule: Optional[str] = None
    priority: Optional[str] = None
    output: Optional[str] = None
    hostname: Optional[str] = None

    k8s: Optional[FalcoK8s] = None
    container: Optional[FalcoContainer] = None
    proc: Optional[FalcoProc] = None

    fields: Dict[str, Any] = Field(default_factory=dict, description="Falco 'fields' payload")
    output_fields: Optional[Dict[str, Any]] = Field(default=None, description="Falcosidekick / JSON output_fields")

    model_config = ConfigDict(populate_by_name=True, extra="allow")

