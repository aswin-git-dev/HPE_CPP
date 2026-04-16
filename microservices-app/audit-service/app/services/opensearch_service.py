from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from opensearchpy import OpenSearch, RequestsHttpConnection
from opensearchpy.exceptions import RequestError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import Settings


logger = logging.getLogger("audit-service.opensearch")


DEFAULT_INDEX_MAPPING: Dict[str, Any] = {
    "settings": {
        "index": {
            "number_of_shards": 1,
            # Single-node / Minikube: avoid yellow cluster (unassigned replicas).
            "number_of_replicas": 0,
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
            "detection_layer": {"type": "keyword"},
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
            try:
                self.client.indices.create(index=self.index, body=DEFAULT_INDEX_MAPPING)
            except RequestError as e:
                # OpenSearch returns 400 resource_already_exists_exception if another
                # replica races to create the index at the same time.
                if getattr(e, "error", "") == "resource_already_exists_exception":
                    logger.info("opensearch_index_already_exists", extra={"index": self.index})
                else:
                    raise
            return

        # Ensure new fields are present even if index already exists
        try:
            self.client.indices.put_mapping(
                index=self.index,
                body={
                    "properties": {
                        "classification": {"type": "keyword"},
                        "detection_layer": {"type": "keyword"},
                    }
                },
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
        doc = {k: v for k, v in event.items() if k and not str(k).startswith("_")}
        eid = doc.get("event_id")
        kwargs: Dict[str, Any] = {"index": self.index, "body": doc, "refresh": False}
        if eid:
            kwargs["id"] = eid
        self.client.index(**kwargs)

    def purge_older_than(self, days: float) -> int:
        """
        Point 4 (downstream): time-based TTL for indexed events of all source_types
        (k8s_audit, app, falco). Complements apiserver on-disk rotation, not a substitute.
        """
        if days <= 0:
            return 0
        try:
            if not self.client.indices.exists(index=self.index):
                return 0
        except Exception:
            return 0
        age_days = max(1, int(days))
        body = {"query": {"range": {"timestamp": {"lt": f"now-{age_days}d"}}}}
        try:
            resp = self.client.delete_by_query(
                index=self.index,
                body=body,
                refresh=True,
                conflicts="proceed",
                wait_for_completion=True,
            )
            return int(resp.get("deleted") or 0)
        except Exception:
            logger.exception("opensearch_delete_by_query_failed", extra={"index": self.index})
            raise

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:
            return False

