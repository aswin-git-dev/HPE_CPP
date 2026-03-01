#  E-Commerce Microservices Platform

A **Cloud-Native Distributed Backend System** simulating an online shopping platform (Swiggy-style), built with FastAPI, Docker, Kubernetes, and MongoDB.

---

##  Architecture

```
                        ┌─────────────────────────────────────────────┐
                        │           Kubernetes Cluster (ecommerce ns)  │
                        │                                              │
  Client ──► Ingress ──►│   ┌────────────────────────────────────┐    │
  (NGINX)               │   │         NODE 1  (worker-1)          │    │
                        │   │  ┌──────────┐  ┌──────────────┐   │    │
                        │   │  │user-pod-1│  │ product-pod-1│   │    │
                        │   │  └──────────┘  └──────────────┘   │    │
                        │   └────────────────────────────────────┘    │
                        │   ┌────────────────────────────────────┐    │
                        │   │         NODE 2  (worker-2)          │    │
                        │   │  ┌──────────┐  ┌──────────────┐   │    │
                        │   │  │user-pod-2│  │ product-pod-2│   │    │
                        │   │  └──────────┘  └──────────────┘   │    │
                        │   └────────────────────────────────────┘    │
                        │   ┌────────────────────────────────────┐    │
                        │   │         NODE 3  (worker-3)          │    │
                        │   │  ┌──────────┐  ┌──────────────┐   │    │
                        │   │  │user-pod-3│  │  order-pod-1 │   │    │
                        │   │  └────┬─────┘  └──────────────┘   │    │
                        │   │       │ MongoDB ClusterIP           │    │
                        │   │  ┌────▼─────┐                      │    │
                        │   │  │ mongo-pod│  (DB node)           │    │
                        │   │  └──────────┘                      │    │
                        │   └────────────────────────────────────┘    │
                        └─────────────────────────────────────────────┘
```

---

## Services

| Service               | Port | Description              |
|-----------------------|------|--------------------------|
| **user-service**      | 8000 | Customer Management      |
| **product-service**   | 8001 | Product Catalog          |
| **order-service**     | 8002 | Order Processing         |
| **payment-service**   | 8003 | Payment Handling         |
| **notification-service** | 8004 | Email/SMS Alerts         |

---

## Quick Start — Local (Docker Compose)

### Prerequisites
- Docker Desktop installed and running

```bash
cd d:\AK_Repo\HPE_CPP\microservices-app

# Build & run all services
docker-compose up --build

# Run in background
docker-compose up --build -d
```

### Access the Application

| URL | Description |
|-----|-------------|
| `http://localhost:8000` | User Service Dashboard (HTML UI) |
| `http://localhost:8000/docs` | Swagger API Docs |
| `http://localhost:8000/redoc` | ReDoc API Docs |
| `http://localhost:8000/health` | Health Check |
| `http://localhost:8001` | Product Service (stub) |
| `http://localhost:8002` | Order Service (stub) |
| `http://localhost:8003` | Payment Service (stub) |
| `http://localhost:8004` | Notification Service (stub) |

---

## Kubernetes Deployment (Multi-Node)

### Prerequisites
- Kubernetes cluster with ≥ 3 worker nodes (kubeadm / GKE / EKS / AKS)
- `kubectl` configured
- NGINX Ingress Controller
- metrics-server (for HPA)

### Step 1 — Install Prerequisites

```bash
# NGINX Ingress Controller
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.0/deploy/static/provider/cloud/deploy.yaml

# metrics-server (for HPA)
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

### Step 2 — Label Worker Nodes

```bash
# List your nodes
kubectl get nodes

# Label each worker node
kubectl label nodes <worker-node-1> node-role.kubernetes.io/worker=worker
kubectl label nodes <worker-node-2> node-role.kubernetes.io/worker=worker
kubectl label nodes <worker-node-3> node-role.kubernetes.io/worker=worker

# Create MongoDB data directory on the DB node
# SSH into the node that will host MongoDB:
# sudo mkdir -p /data/mongodb/userdb
```

### Step 3 — Build & Push Docker Images

```bash
# Build images
docker build -t user-service:latest       ./user-service
docker build -t product-service:latest    ./product-service
docker build -t order-service:latest      ./order-service
docker build -t payment-service:latest    ./payment-service
docker build -t notification-service:latest ./notification-service

# For production, push to registry:
# docker tag user-service:latest your-registry/user-service:latest
# docker push your-registry/user-service:latest
```

### Step 4 — Deploy to Kubernetes

```bash
# 1. Create namespace
kubectl apply -f k8s/namespace.yaml

# 2. Deploy MongoDB (DB + PV + PVC)
kubectl apply -f db/mongo-pv.yaml
kubectl apply -f db/mongo-deployment.yaml
kubectl apply -f k8s/mongo-service.yaml

# 3. Deploy all services
kubectl apply -f k8s/user-deployment.yaml
kubectl apply -f k8s/user-service.yaml
kubectl apply -f k8s/product-deployment.yaml
kubectl apply -f k8s/product-service.yaml
kubectl apply -f k8s/order-deployment.yaml
kubectl apply -f k8s/order-service.yaml
kubectl apply -f k8s/payment-deployment.yaml
kubectl apply -f k8s/payment-service.yaml
kubectl apply -f k8s/notification-deployment.yaml
kubectl apply -f k8s/notification-service.yaml

# 4. Apply HA & scaling policies
kubectl apply -f k8s/pdb.yaml
kubectl apply -f k8s/hpa.yaml

# 5. Apply network policy & ingress
kubectl apply -f k8s/network-policy.yaml
kubectl apply -f k8s/ingress.yaml
```

### Step 5 — Verify

```bash
# Check all pods across nodes
kubectl get pods -n ecommerce -o wide

# Check services
kubectl get svc -n ecommerce

# Check HPA
kubectl get hpa -n ecommerce

# Check PDB
kubectl get pdb -n ecommerce

# Watch pods spread across nodes
kubectl get pods -n ecommerce -o wide --watch
```

---

##  Multi-Node Features

| Feature | Config |
|---------|--------|
| **Pod Anti-Affinity** | `preferredDuringSchedulingIgnoredDuringExecution` — spreads pods across nodes |
| **Topology Spread** | `maxSkew: 1` on `kubernetes.io/hostname` — even distribution |
| **HPA** | user-service: 3→10 pods at CPU≥70% / Memory≥80% |
| **PDB** | `minAvailable: 1` for all services — safe during node drain |
| **Zero-downtime updates** | `maxSurge: 1, maxUnavailable: 0` rolling update |
| **Network Policy** | Default-deny + explicit allow rules (zero-trust) |
| **Resource Requests/Limits** | Proper CPU/memory for scheduler bin-packing |

---

## User Service API Reference

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | HTML Dashboard |
| `POST` | `/users/` | Create a new user |
| `GET` | `/users/` | List all users |
| `GET` | `/users/{id}` | Get user by ID |
| `PUT` | `/users/{id}` | Update user |
| `DELETE` | `/users/{id}` | Delete user |
| `GET` | `/health` | Health check |

### Example API Usage

```bash
# Create user
curl -X POST http://localhost:8000/users/ \
  -H "Content-Type: application/json" \
  -d '{"name":"Aswin Kumar","email":"aswin@example.com","phone":"9876543210","role":"customer"}'

# List all users
curl http://localhost:8000/users/

# Get specific user
curl http://localhost:8000/users/<user_id>

# Update user
curl -X PUT http://localhost:8000/users/<user_id> \
  -H "Content-Type: application/json" \
  -d '{"name": "Aswin K"}'

# Delete user
curl -X DELETE http://localhost:8000/users/<user_id>
```

---

## Project Structure

```
microservices-app/
├── user-service/             # Full FastAPI implementation
│   ├── main.py               #    CRUD API + HTML dashboard
│   ├── requirements.txt
│   └── Dockerfile            #    Multi-stage, non-root user
├── product-service/          # Stub (folder only)
├── order-service/            # Stub (folder only)
├── payment-service/          # Stub (folder only)
├── notification-service/     # Stub (folder only)
├── db/
│   ├── mongo-deployment.yaml #    MongoDB Deployment + resource limits
│   └── mongo-pv.yaml         #    PersistentVolume + PVC (5Gi)
├── k8s/
│   ├── namespace.yaml        #    ecommerce namespace
│   ├── user-deployment.yaml  #    3 replicas, anti-affinity, topology spread
│   ├── *-deployment.yaml     #    2 replicas each, anti-affinity
│   ├── *-service.yaml        #    ClusterIP services
│   ├── mongo-service.yaml    #    ClusterIP + Headless
│   ├── pdb.yaml              #    PodDisruptionBudgets for all services
│   ├── hpa.yaml              #    HPA: 3→10 pods at CPU/Mem threshold
│   ├── network-policy.yaml   #    Zero-trust network policy
│   └── ingress.yaml          #    NGINX Ingress with path routing
├── docker-compose.yaml       #    Local dev setup
└── README.md
```

---

##  Tech Stack

| Layer | Technology |
|-------|-----------|
| **Framework** | FastAPI 0.110 |
| **Runtime** | Python 3.11, Uvicorn |
| **Database** | MongoDB 6.0 (Motor async driver) |
| **Containerisation** | Docker (multi-stage builds) |
| **Orchestration** | Kubernetes (Deployments, Services, HPA, PDB) |
| **Networking** | NGINX Ingress, NetworkPolicy |
| **Local Dev** | Docker Compose |
