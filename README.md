# A Smart Security Logging Framework for Microservices using Kubernetes Control Plane, eBPF and Machine Learning

## Overview

This project implements a cloud-native microservices-based e-commerce platform integrated with a security monitoring framework for Kubernetes environments.

The system combines Kubernetes Audit Logs, Falco runtime security monitoring, Linkerd Service Mesh, OpenSearch, and Grafana to provide secure communication, observability, and security event monitoring for microservices deployed in a Kubernetes cluster.

In addition to the security framework, the project includes an Ecommerce User Interface and an Admin Dashboard for monitoring cluster activities and security events.

---

# System Architecture

```text
                    ┌─────────────────────────┐
                    │      Ecommerce UI       │
                    │ Login • Search • Order  │
                    │ Payment • Notification  │
                    └────────────┬────────────┘
                                 │
                                 ▼

                ┌─────────────────────────────┐
                │      Kubernetes Cluster     │
                │       (3 Node Minikube)     │
                └─────────────────────────────┘

                                 │

      ┌──────────────────────────────────────────┐
      │         Linkerd Service Mesh             │
      │ mTLS • Service Discovery • Routing       │
      │ Traffic Observability • Reliability      │
      └──────────────────────────────────────────┘

                                 │

     ┌────────────┬────────────┬────────────┬────────────┐
     │            │            │            │            │

┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌─────────────┐
│ User     │ │ Product  │ │ Order    │ │ Payment  │ │ Notification│
│ Service  │ │ Service  │ │ Service  │ │ Service  │ │ Service     │
└──────────┘ └──────────┘ └──────────┘ └──────────┘ └─────────────┘

                                 │
                                 ▼

                         ┌────────────┐
                         │ MongoDB    │
                         └────────────┘

────────────────────────────────────────────

Security Monitoring Layer

Kubernetes API Server
          │
          ▼

      Audit Logs
          │
          ▼

    Audit Service

────────────────────────────────────────────

Container Runtime
          │
          ▼

        Falco
          │
          ▼

    Falcosidekick
          │
          ▼

    Audit Service

────────────────────────────────────────────

Audit Service
          │
          ▼

     OpenSearch
          │
          ▼

      Grafana

────────────────────────────────────────────

Admin Dashboard

Admin Login
      │
      ▼

Security Dashboard

 ├── Control Plane Monitor
 ├── Cluster Architecture View
 ├── OpenSearch Dashboard
 └── Grafana Dashboard
```

---

# Key Features

## Ecommerce Platform

* User Login
* Product Search
* Order Placement
* Payment Simulation
* Notification Service
* Admin Login

## Linkerd Service Mesh

* Automatic sidecar injection
* Mutual TLS (mTLS)
* Service discovery
* Traffic routing
* Request-level observability
* Service-to-service communication security

## Security Monitoring

* Kubernetes Audit Logs collection
* Runtime threat detection using Falco
* Falcosidekick alert forwarding
* Audit event classification
* Security event monitoring

## Observability

* Control Plane Monitoring UI
* Cluster Architecture Dashboard
* OpenSearch Dashboards
* Grafana Dashboards

## Administration

* Admin Authentication
* Central Security Dashboard
* Audit Event Monitoring
* Security Event Visualization

---

# Core Services

| Service              | Port  | Description                         |
| -------------------- | ----- | ----------------------------------- |
| User Service         | 18100 | Customer Management and Login       |
| Product Service      | 18101 | Product Search and Catalog          |
| Order Service        | 18102 | Order Processing                    |
| Payment Service      | 18103 | Payment Handling                    |
| Notification Service | 18104 | Notifications                       |
| Audit Service        | 18015 | Audit Log Collection and Monitoring |

---

# Observability and Security Stack

## Linkerd Service Mesh

Linkerd provides:

* Mutual TLS (mTLS)
* Service discovery
* Traffic routing
* Reliability
* Request metrics
* Service observability

---

## Kubernetes Audit Logs

Audit logs capture:

* Namespace creation
* Resource modifications
* Secret creation
* Pod executions
* User activities
* Administrative operations

---

## Falco

Falco performs runtime security monitoring using eBPF.

Examples:

* Shell execution inside containers
* Unauthorized file access
* Privilege escalation attempts
* Suspicious container activities

---

## Falcosidekick

Falcosidekick receives Falco alerts and forwards them to the Audit Service for processing and visualization.

---

## Audit Service

The Audit Service:

* Receives Kubernetes Audit Logs
* Receives Falco Security Alerts
* Normalizes events
* Classifies events
* Stores events
* Provides monitoring dashboards

---

## OpenSearch

OpenSearch provides:

* Audit event storage
* Security event indexing
* Event search capabilities
* Dashboard visualization

---

## Grafana

Grafana provides:

* Security dashboards
* Event visualization
* Metrics monitoring
* Security alert monitoring

---

# Deployment Environment

## Software Requirements

* Docker Desktop
* Kubernetes (Minikube)
* Helm
* Kubectl
* Python 3.11
* FastAPI
* MongoDB

---

## Cluster Configuration

* Kubernetes: Minikube
* Nodes: 3
* Control Plane: 1
* Worker Nodes: 2

---

### Prerequisites 
1. Docker Desktop installed and running. 
2. kubectl, minikube, and helm installed. 
3. **Environment Variables**: Create an .env file in microservices-app/k8s/ and microservices-app/audit-service/ containing your Grafana Cloud credentials:
env
   LOKI_PUSH_URL=https://logs-prod-xxx.grafana.net/loki/api/v1/push
   LOKI_URL=https://logs-prod-xxx.grafana.net
   LOKI_INSTANCE_ID=your_id
   GRAFANA_CLOUD_TOKEN=glc_your_secure_token
### Quick Start (Windows) 
To deploy the entire 3-node cluster, patch the API server for audit logging, apply all manifests, build images, and set up port forwarding: 
1. Starts a 3-node Minikube cluster (--nodes=3). 
2. Patches the kube-apiserver to mount hostPath volumes for audit logs. 
3. Applies all Kubernetes YAML manifests, including zero-trust Network Policies, Deployments, and HPA. 
4. Builds Docker images directly into Minikube and distributes them across nodes. 
5. Installs **Falco** via Helm (parsing the .env file for Grafana credentials). 
6. Automatically sets up port-forward for all services and opens the UI in your browser. 
*Note: You can skip certain steps on subsequent runs by setting environment variables in your terminal before running the script (e.g., set SKIP_IMAGE_BUILD=1, set SKIP_FALCO=1).* ---

The script performs:

1. Starts Minikube Cluster
2. Applies Kubernetes manifests
3. Deploys microservices
4. Deploys Linkerd
5. Deploys Falco
6. Deploys OpenSearch
7. Configures Monitoring Components
8. Starts Port Forwarding
9. Opens Ecommerce UI

---

# User Interface

## Ecommerce UI

The Ecommerce UI provides:

* User Login
* Product Search
* Order Placement
* Payment Options
* Notifications
* Admin Access

---

## Admin Dashboard

Admin credentials:

```text
Username: admin
Password: admin
```

Available Dashboard Options:

* View Control Plane Logs
* View Cluster Architecture
* View OpenSearch Dashboard
* View Grafana Dashboard

---

# Verification URLs

## Ecommerce

```text
http://127.0.0.1:5500/ecommerce.html
```

## Control Plane Monitor

```text
http://127.0.0.1:18015/control-plane/ui
```

## Architecture Dashboard

```text
http://127.0.0.1:18015/control-plane/architecture/ui
```

## OpenSearch Dashboard

```text
http://127.0.0.1:5601
```

## Grafana Dashboard

```text
https://securelogger.grafana.net
```

## Microservices

```text
User Service         : http://127.0.0.1:18100
Product Service      : http://127.0.0.1:18101
Order Service        : http://127.0.0.1:18102
Payment Service      : http://127.0.0.1:18103
Notification Service : http://127.0.0.1:18104
```

---

# Triggering Test Audit Events

Execute:

```cmd
kubectl create namespace demo-audit-ns

kubectl -n ecommerce create secret generic demo-secret --from-literal=pw=test123

kubectl -n ecommerce exec deployment/audit-service -- python -c "print('exec-test')"

kubectl delete namespace demo-audit-ns

kubectl -n ecommerce delete secret demo-secret
```

The generated events can be viewed in:

* Control Plane Monitor
* OpenSearch
* Grafana

---

# Project Structure

```text
microservices-app/

├── audit-service/
│   ├── app/
│   ├── k8s/
│   ├── scripts/
│   └── vector/

├── user-service/
├── product-service/
├── order-service/
├── payment-service/
├── notification-service/

├── kafka-producer-service/
├── ml-anomaly-service/

├── k8s/

├── ecommerce.html
├── admin-login.html
├── security-dashboard.html

├── docker-compose.yaml
├── Usecase.md
└── README.md
```

---

# Technology Stack

| Layer              | Technology            |
| ------------------ | --------------------- |
| Frontend           | HTML, CSS, JavaScript |
| Backend            | FastAPI               |
| Database           | MongoDB               |
| Containerization   | Docker                |
| Orchestration      | Kubernetes (Minikube) |
| Service Mesh       | Linkerd               |
| Runtime Security   | Falco, eBPF           |
| Alert Forwarding   | Falcosidekick         |
| Logging            | Kubernetes Audit Logs |
| Search & Analytics | OpenSearch            |
| Visualization      | Grafana               |
| Monitoring         | Audit Service         |

---

