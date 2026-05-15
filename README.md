# A Smart Security Logging Framework for Microservices using Kubernetes Control Plane, eBPF and Machine Learning


A **Cloud-Native Distributed Backend System** simulating an online shopping platform (Swiggy-style), built with FastAPI, Docker, Kubernetes, and MongoDB. This project extends beyond a standard microservices deployment by incorporating a robust **Security, Auditing, and Observability Stack** featuring Falco, Vector, Grafana Cloud, and OpenSearch.

---

## Architecture

```text
                        ┌──────────────────────────────────────────────┐
                        │           Kubernetes Cluster (ecommerce ns)  │
                        │                                              │
  Client ──► Ingress ──►│   ┌────────────────────────────────────┐     │
  (NGINX)               │   │         NODE 1 (Control Plane)     │     │
                        │   │  ┌────────────┐ ┌───────────────┐  │     │
                        │   │  │audit-service│ │ falcosidekick│  │     │
                        │   │  └─────┬──────┘ └───────┬───────┘  │     │
                        │   │        │                │          │     │
                        │   └────────▼────────────────▼──────────┘     │
                        │   ┌────────────────────────────────────┐     │
                        │   │         NODE 2 & 3 (Workers)       │     │
                        │   │  ┌──────────┐  ┌──────────────┐    │     │
                        │   │  │user-pod  │  │ product-pod  │    │     │
                        │   │  ├──────────┤  ├──────────────┤    │     │
                        │   │  │order-pod │  │ payment-pod  │    │     │
                        │   │  └────┬─────┘  └──────┬───────┘    │     │
                        │   │       │               │            │     │
                        │   │       ▼               ▼            │     │
                        │   │  ┌──────────┐ ┌───────────────┐    │     │
                        │   │  │ mongo-pod│ │ vector (logs) │    │     │
                        │   │  └──────────┘ └───────────────┘    │     │
                        │   └────────────────────────────────────┘     │
                        │                                              │
                        │   ┌────────────────────────────────────┐     │
                        │   │         EXTERNAL SERVICES          │     │
                        │   │  ┌──────────┐  ┌──────────────┐    │     │
                        │   │  │OpenSearch│  │ Grafana Cloud│    │     │
                        │   │  │(Audit DB)│  │ (Loki Logs)  │    │     │
                        │   │  └──────────┘  └──────────────┘    │     │
                        │   └────────────────────────────────────┘     │
                        └──────────────────────────────────────────────┘
```

---

## Core Services

| Service               | Port | Description |
|-----------------------|------|-------------|
| **user-service**      | 8000 | Customer Management & HTML UI |
| **product-service**   | 8001 | Product Catalog |
| **order-service**     | 8002 | Order Processing |
| **payment-service**   | 8003 | Payment Handling |
| **notification-service** | 8004 | Email/SMS Alerts |
| **audit-service**     | 8005 | Central ingestion for K8s Audit Logs and Falco security alerts |

---

## Observability & Security Stack

This platform integrates an advanced observability pipeline to ensure zero-trust security and complete audit trails:

- **Falco**: DaemonSet running on kernel level using eBPF to detect suspicious container behavior, filesystem access, and shell executions. Alerts are forwarded via `falcosidekick`.
- **Vector**: DaemonSet collecting Kubernetes API server events, logs, and routing them based on RBAC to the audit service.
- **Audit-Service**: A FastAPI backend that processes incoming telemetry, classifies it, and exports it via CSV/Excel. It serves as the bridge to log aggregators.
- **Grafana Cloud (Loki)**: Secure remote log storage and dynamic dashboards.
- **OpenSearch**: Deployed within the cluster with automated Index State Management (ISM) for TTL-based log retention.

---

## Kubernetes Deployment (Automated Setup)

We have streamlined the entire Minikube multi-node deployment via a set of automation scripts. 

### Prerequisites
1. Docker Desktop installed and running.
2. `kubectl`, `minikube`, and `helm` installed.
3. **Environment Variables**: Create an `.env` file in `microservices-app/k8s/` and `microservices-app/audit-service/` containing your Grafana Cloud credentials:
   ```env
   LOKI_PUSH_URL=https://logs-prod-xxx.grafana.net/loki/api/v1/push
   LOKI_URL=https://logs-prod-xxx.grafana.net
   LOKI_INSTANCE_ID=your_id
   GRAFANA_CLOUD_TOKEN=glc_your_secure_token
   ```

### Quick Start (Windows)

To deploy the entire 3-node cluster, patch the API server for audit logging, apply all manifests, build images, and set up port forwarding:

1. Starts a 3-node Minikube cluster (`--nodes=3`).
2. Patches the `kube-apiserver` to mount hostPath volumes for audit logs.
3. Applies all Kubernetes YAML manifests, including zero-trust Network Policies, Deployments, and HPA.
4. Builds Docker images directly into Minikube and distributes them across nodes.
5. Installs **Falco** via Helm (parsing the `.env` file for Grafana credentials).
6. Automatically sets up `port-forward` for all services and opens the UI in your browser.

*Note: You can skip certain steps on subsequent runs by setting environment variables in your terminal before running the script (e.g., `set SKIP_IMAGE_BUILD=1`, `set SKIP_FALCO=1`).*

---

## Verification & Usage

Once your finishes, you need to open browser and check the following urls:

### UIs & Dashboards
- **Monitor UI**: [http://127.0.0.1:18015/control-plane/ui](http://127.0.0.1:18015/control-plane/ui)
- **Architecture View**: [http://127.0.0.1:18015/control-plane/architecture/ui](http://127.0.0.1:18015/control-plane/architecture/ui)
- **Grafana Cloud**: [https://securelogger.grafana.net](https://securelogger.grafana.net)
- **OpenSearch Dashboards**: [http://127.0.0.1:5601](http://127.0.0.1:5601)

### Triggering Security Alerts (Test)

To verify that the audit and security pipelines are working, trigger a test event in a new terminal:

```cmd
kubectl create namespace demo-audit-ns
kubectl -n ecommerce create secret generic demo-secret --from-literal=pw=test123
kubectl -n ecommerce exec deployment/audit-service -- python -c "print('exec-test')"
kubectl delete namespace demo-audit-ns
```
*You will immediately see these actions reflected in the Monitor UI, Grafana Loki, and OpenSearch.*

---

## Project Structure

```
microservices-app/
├── user-service/             # FastAPI Customer Management
├── product-service/          # Product Catalog 
├── order-service/            # Order Processing 
├── payment-service/          # Payment Handling 
├── notification-service/     # Alerts 
├── audit-service/            # Security & Event Monitor (FastAPI + Excel export)
├── k8s/
│   ├── dashboards/           # Grafana Dashboard JSON templates
│   ├── namespace.yaml        # ecommerce namespace
│   ├── *-deployment.yaml     # Microservices deployments (anti-affinity applied)
│   ├── vector.yaml           # Vector DaemonSet for logs forwarding
│   ├── falco-values.yaml     # Helm values for Falco & Falcosidekick
│   ├── opensearch-ism-job.yaml # TTL policies for audit databases
│   ├── network-policy.yaml   # Zero-trust network rules
│   ├── run-project.bat       # Master deployment automation script
│   └── install-falco.bat     # Helm install automation for Falco
└── README.md
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Microservices Framework** | FastAPI 0.110, Python 3.11 |
| **Database** | MongoDB 6.0 |
| **Containerisation** | Docker |
| **Orchestration** | Kubernetes (Minikube 3-Node) |
| **Security Runtime** | Falco (eBPF), Falcosidekick |
| **Logging Pipeline** | Vector |
| **Log Aggregation** | Grafana Cloud (Loki), OpenSearch |
| **Networking** | NGINX Ingress, NetworkPolicy |
