from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.middleware.request_context import get_request_id
from app.schemas import AppLogIn, FalcoAlertIn, IngestResponse, K8sAuditLogIn, Severity, SourceType


logger = logging.getLogger("audit-service.ingest")
router = APIRouter(prefix="/ingest", tags=["ingest"])


def _index_opensearch(request: Request, retained: Dict[str, Any]) -> None:
    ost = getattr(request.app.state, "opensearch_service", None)
    if ost is None:
        return
    try:
        ost.index_event(retained)
    except Exception:
        logger.exception(
            "opensearch_index_failed",
            extra={"event_id": retained.get("event_id"), "source_type": retained.get("source_type")},
        )


class BulkEvent(BaseModel):
    source_type: Literal["app", "k8s_audit", "falco"]
    event: Dict[str, Any]


def _process_and_store(request: Request, normalized: Dict[str, Any]) -> bool:
    retention = request.app.state.retention_service
    tagging = request.app.state.tagging_service
    store = request.app.state.event_store_service
    stats = request.app.state.stats_service

    normalized["tags"] = tagging.build_tags(normalized)
    retained, dropped = retention.apply(normalized)
    if dropped:
        return False

    try:
        store.index_event(retained)
        _index_opensearch(request, retained)
        # update stats using the original normalized values (before retention removal)
        stats.record_processed(SourceType(normalized["source_type"]), severity=_coerce_sev(normalized.get("severity")))
        return True
    except Exception:
        stats.record_failed()
        logger.exception(
            "event_store_failed",
            extra={"request_id": get_request_id(), "event_id": normalized.get("event_id"), "source_type": normalized.get("source_type")},
        )
        return False


def _coerce_sev(value: Any):
    s = (value or "info").lower()
    if s in ("info", "warning", "critical", "unauthorized_access"):
        return Severity(s)
    if s in ("error", "fatal"):
        return Severity.critical
    return Severity.info


@router.post("/app", response_model=IngestResponse)
def ingest_app(payload: AppLogIn, request: Request):
    normalizer = request.app.state.normalizer
    normalized = normalizer.normalize_app(payload)
    stored = _process_and_store(request, normalized)
    return IngestResponse(
        accepted=1,
        stored=1 if stored else 0,
        dropped=0 if stored else 1,  # includes namespace drops or index failures
        failed=0 if stored else 1,
        sample_event_ids=[normalized["event_id"]],
    )


@router.post("/audit", response_model=IngestResponse)
def ingest_audit(payload: K8sAuditLogIn, request: Request):
    normalizer = request.app.state.normalizer
    normalized = normalizer.normalize_k8s_audit(payload)
    stored = _process_and_store(request, normalized)
    return IngestResponse(
        accepted=1,
        stored=1 if stored else 0,
        dropped=0 if stored else 1,
        failed=0 if stored else 1,
        sample_event_ids=[normalized["event_id"]],
    )


@router.post("/falco", response_model=IngestResponse)
def ingest_falco(payload: FalcoAlertIn, request: Request):
    normalizer = request.app.state.normalizer
    normalized = normalizer.normalize_falco(payload)
    stored = _process_and_store(request, normalized)
    return IngestResponse(
        accepted=1,
        stored=1 if stored else 0,
        dropped=0 if stored else 1,
        failed=0 if stored else 1,
        sample_event_ids=[normalized["event_id"]],
    )


@router.post("/bulk", response_model=IngestResponse)
def ingest_bulk(payload: List[BulkEvent], request: Request):
    normalizer = request.app.state.normalizer

    accepted = len(payload)
    stored = 0
    dropped = 0
    failed = 0
    sample_ids: List[str] = []

    for item in payload:
        try:
            if item.source_type == "app":
                normalized = normalizer.normalize_app(AppLogIn(**item.event))
            elif item.source_type == "k8s_audit":
                normalized = normalizer.normalize_k8s_audit(K8sAuditLogIn(**item.event))
            else:
                normalized = normalizer.normalize_falco(FalcoAlertIn.model_validate(item.event))

            ok = _process_and_store(request, normalized)
            if ok:
                stored += 1
            else:
                # Could be dropped by namespace policy or indexing failure
                dropped += 1
                failed += 1
            if len(sample_ids) < 10:
                sample_ids.append(normalized["event_id"])
        except Exception:
            failed += 1
            logger.exception("bulk_item_failed", extra={"request_id": get_request_id()})

    return IngestResponse(
        accepted=accepted,
        stored=stored,
        dropped=dropped,
        failed=failed,
        sample_event_ids=sample_ids,
    )

