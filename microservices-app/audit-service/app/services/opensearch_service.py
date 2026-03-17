from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from opensearchpy import OpenSearch, RequestsHttpConnection
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings


logger = logging.getLogger("audit-service.opensearch")


DEFAULT_INDEX_MAPPING: Dict[str, Any] = {
    "settings": {
        "index": {
            "number_of_shards": 1,
            "number_of_replicas": 1,
        }
    },
    "mappings": {
        "dynamic": True,
        "properties": {
            "event_id": {"type": "keyword"},
            "timestamp": {"type": "date"},
            "source_type": {"type": "keyword"},
            "service_name": {"type": "keyword"},
            "namespace": {"type": "keyword"},
            "pod_name": {"type": "keyword"},
            "user_name": {"type": "keyword"},
            "severity": {"type": "keyword"},
            "event_type": {"type": "keyword"},
            "message": {"type": "text"},
            "classification": {"type": "keyword"},
            "action": {"type": "keyword"},
            "resource": {"type": "keyword"},
            "resource_name": {"type": "keyword"},
            "status_code": {"type": "integer"},
            "tags": {"type": "keyword"},
            "raw_event": {"type": "object", "enabled": True},
        },
    },
}


class OpenSearchService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.index = settings.opensearch_index
        self.client = self._build_client(settings)

    def _build_client(self, settings: Settings) -> OpenSearch:
        http_auth = None
        if settings.opensearch_user and settings.opensearch_password:
            http_auth = (settings.opensearch_user, settings.opensearch_password)

        return OpenSearch(
            hosts=[settings.opensearch_url],
            http_auth=http_auth,
            use_ssl=settings.opensearch_url.startswith("https://"),
            verify_certs=settings.opensearch_verify_certs,
            ssl_assert_hostname=False,
            ssl_show_warn=False,
            timeout=settings.opensearch_timeout_s,
            max_retries=settings.opensearch_max_retries,
            retry_on_timeout=True,
            connection_class=RequestsHttpConnection,
        )

    def ensure_index(self) -> None:
        if not self.client.indices.exists(self.index):
            logger.info("creating_opensearch_index", extra={"index": self.index})
            self.client.indices.create(index=self.index, body=DEFAULT_INDEX_MAPPING)
            return

        # Ensure new fields are present even if index already exists
        try:
            self.client.indices.put_mapping(
                index=self.index,
                body={"properties": {"classification": {"type": "keyword"}}},
            )
        except Exception:
            # Mapping updates are best-effort; dynamic mappings can still work.
            logger.warning("opensearch_put_mapping_failed", extra={"index": self.index})

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
        reraise=True,
    )
    def index_event(self, event: Dict[str, Any]) -> None:
        # Use event_id as document _id to deduplicate at index-level
        self.client.index(index=self.index, id=event.get("event_id"), body=event, refresh=False)

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:
            return False

