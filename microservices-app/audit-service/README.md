# Audit Microservice (FastAPI + OpenSearch)

A supporting **security/monitoring microservice** for the Kubernetes-based microservices platform.  
It **collects logs/events**, **normalizes them into one schema**, applies **namespace filtering + retention**, adds **simple security tags**, and stores everything in **OpenSearch** for centralized search/analytics.

This service is **not** a business microservice (like `user-service`/`order-service`).  
It is part of a smart monitoring framework that sits **beside** the e-commerce system.

---

## How it fits the overall architecture

- **Business services** (user/product/order/payment/notification) generate **application logs**.
- Kubernetes control plane emits **Kubernetes audit events**.
- Falco emits **runtime alerts** (eBPF-based detection).
- **audit-service** receives events from all three sources via HTTP ingestion endpoints:
  - normalizes into a **common event schema**
  - filters by **namespace policy**
  - applies **selective field retention**
  - stores the result into **OpenSearch** index `audit-events`
  - exposes `/stats`, `/health`, and optional `/metrics`

---

## Endpoints

- `POST /ingest/app` - ingest application/service logs
- `POST /ingest/audit` - ingest Kubernetes audit log events
- `POST /ingest/falco` - ingest Falco runtime alerts
- `POST /ingest/bulk` - ingest batch events
- `GET /health` - health check
- `GET /stats` - in-memory counters (by source + severity)
- `GET /metrics` - Prometheus metrics (if enabled)

---

## Normalized schema (stored in OpenSearch)

All sources become a single structure:

```json
{
  "event_id": "unique-hash-or-uuid",
  "timestamp": "ISO timestamp",
  "source_type": "app | k8s_audit | falco",
  "service_name": "string or null",
  "namespace": "string or null",
  "pod_name": "string or null",
  "user_name": "string or null",
  "severity": "info | warning | critical",
  "event_type": "string",
  "message": "string",
  "action": "string or null",
  "resource": "string or null",
  "resource_name": "string or null",
  "status_code": "integer or null",
  "tags": [],
  "raw_event": {}
}
```

Key rules:
- **`raw_event`** always preserves the original payload (can be trimmed/disabled by config)
- **timestamp fallback**: if missing, service assigns current UTC time
- **severity mapping**: source-specific severity is normalized to `info|warning|critical`
- **dedup**: `event_id` is generated as a stable SHA-256 fingerprint if source doesn’t provide one
- **tags**: simple heuristics add tags like `auth-failure`, `privilege-escalation`, `config-change`, etc.

---

## Local run (developer mode)

```bash
cd microservices-app/audit-service
python -m venv .venv
source .venv/bin/activate   # (Windows PowerShell: .venv\\Scripts\\Activate.ps1)
pip install -r requirements.txt

cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8005 --reload
```

---

## Sample payloads

### 1) Application log (`POST /ingest/app`)

```json
{
  "timestamp": "2026-03-17T10:00:00Z",
  "service_name": "user-service",
  "namespace": "ecommerce",
  "pod_name": "user-service-6c9f7",
  "request_path": "/users/123",
  "method": "GET",
  "status_code": 200,
  "response_time": 12.4,
  "log_level": "info",
  "message": "Request served successfully",
  "extra": {
    "client_ip": "10.0.0.12",
    "trace_id": "abc-123"
  }
}
```

### 2) Kubernetes audit event (`POST /ingest/audit`)

```json
{
  "auditID": "b9c8c1a4-8f6c-4b86-a1fb-123456789000",
  "requestReceivedTimestamp": "2026-03-17T10:01:00Z",
  "verb": "create",
  "user": { "username": "system:serviceaccount:ecommerce:deployer" },
  "objectRef": {
    "namespace": "ecommerce",
    "resource": "secrets",
    "name": "db-credentials"
  },
  "stage": "ResponseComplete",
  "responseStatus": { "code": 201 },
  "requestURI": "/api/v1/namespaces/ecommerce/secrets"
}
```

### 3) Falco alert (`POST /ingest/falco`)

```json
{
  "time": "2026-03-17T10:02:00Z",
  "rule": "Terminal shell in container",
  "priority": "Critical",
  "output": "A shell was spawned in a container (user=root)",
  "hostname": "worker-1",
  "k8s": {
    "k8s.ns.name": "ecommerce",
    "k8s.pod.name": "payment-service-7b4c9"
  },
  "container": {
    "container.name": "payment-service",
    "container.image": "payment-service:latest"
  },
  "proc": { "proc.name": "bash" },
  "fields": { "user.name": "root" }
}
```

### 4) Bulk ingest (`POST /ingest/bulk`)

```json
[
  {
    "source_type": "app",
    "event": { "service_name": "user-service", "message": "login ok", "status_code": 200 }
  },
  {
    "source_type": "k8s_audit",
    "event": { "verb": "delete", "objectRef": { "namespace": "ecommerce", "resource": "pods", "name": "x" } }
  },
  {
    "source_type": "falco",
    "event": { "rule": "Write below etc", "priority": "Warning", "output": "/etc/passwd modified" }
  }
]
```

---

## curl test commands

### Health
```bash
curl http://localhost:8005/health
```

### App log
```bash
curl -X POST http://localhost:8005/ingest/app \
  -H "Content-Type: application/json" \
  -d '{"service_name":"user-service","namespace":"ecommerce","message":"GET /users ok","method":"GET","request_path":"/users","status_code":200,"log_level":"info"}'
```

### K8s audit log
```bash
curl -X POST http://localhost:8005/ingest/audit \
  -H "Content-Type: application/json" \
  -d '{"verb":"create","user":{"username":"admin"},"objectRef":{"namespace":"ecommerce","resource":"secrets","name":"x"},"responseStatus":{"code":201}}'
```

### Falco
```bash
curl -X POST http://localhost:8005/ingest/falco \
  -H "Content-Type: application/json" \
  -d '{"rule":"Terminal shell in container","priority":"Critical","output":"bash spawned","k8s":{"k8s.ns.name":"ecommerce","k8s.pod.name":"payment-xyz"},"container":{"container.name":"payment-service"}}'
```

### Bulk
```bash
curl -X POST http://localhost:8005/ingest/bulk \
  -H "Content-Type: application/json" \
  -d '[{"source_type":"app","event":{"service_name":"user-service","message":"ok","status_code":200}},{"source_type":"falco","event":{"rule":"Write below etc","priority":"Warning","output":"file write"}}]'
```

### Stats
```bash
curl http://localhost:8005/stats
```

### Metrics
```bash
curl http://localhost:8005/metrics
```

---

## Kubernetes deployment

Apply manifests (namespace `ecommerce`):

```bash
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secret.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml
```

Notes:
- OpenSearch should be reachable at `OPENSEARCH_URL` (default `http://opensearch:9200`).
- The service auto-creates the index if missing (`audit-events` by default).

