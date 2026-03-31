from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "audit-service"
    env: str = Field(default="dev", description="dev|staging|prod")
    log_level: str = Field(default="INFO", description="DEBUG|INFO|WARNING|ERROR")

    host: str = "0.0.0.0"
    port: int = 8005

    # Namespace filtering / retention toggles
    allowed_namespaces: Optional[str] = Field(
        default=None,
        description="Comma-separated allowlist; if set, only these namespaces are accepted.",
    )
    ignored_namespaces: str = Field(
        default="kube-system,kube-public,kube-node-lease",
        description="Comma-separated blocklist namespaces to ignore.",
    )
    store_raw_event: bool = Field(default=True, description="Store raw_event field.")
    raw_event_max_bytes: int = Field(default=64000, description="Max raw_event JSON bytes.")
    retained_fields: Optional[str] = Field(
        default=None,
        description="Comma-separated normalized fields to keep (e.g. event_id,timestamp,source_type,message).",
    )

    # In-memory monitor store
    event_store_max_events: int = Field(default=5000)
    cluster_source_urn: str = Field(default="urn:k8s:cluster:prod-cluster-01")

    # Observability
    enable_metrics: bool = Field(default=True)

    def allowed_namespaces_list(self) -> Optional[List[str]]:
        if not self.allowed_namespaces:
            return None
        items = [x.strip() for x in self.allowed_namespaces.split(",")]
        items = [x for x in items if x]
        return items or None

    def ignored_namespaces_list(self) -> List[str]:
        items = [x.strip() for x in (self.ignored_namespaces or "").split(",")]
        return [x for x in items if x]

    def retained_fields_list(self) -> Optional[List[str]]:
        if not self.retained_fields:
            return None
        items = [x.strip() for x in self.retained_fields.split(",")]
        items = [x for x in items if x]
        return items or None


@lru_cache
def get_settings() -> Settings:
    return Settings()

