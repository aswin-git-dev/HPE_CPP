# Service Mesh Integration using Linkerd

## Prerequisites

* Docker Desktop
* Kubernetes (Minikube)
* kubectl
* Linkerd CLI
* Git
* Running microservices cluster

---

## Objective

This project integrates Linkerd Service Mesh with the Kubernetes-based microservices application to provide:

* Secure service-to-service communication
* Automatic mTLS
* Traffic visibility
* Observability and monitoring

---

## Components Installed

### Linkerd Control Plane

* Linkerd Control Plane
* Linkerd Identity
* Linkerd Destination
* Linkerd Proxy Injector

### Linkerd Viz Extension

* Linkerd Viz Dashboard
* Metrics API
* Prometheus
* Tap
* Tap Injector
* Web UI

---

## Namespaces Injected

Only business microservices are injected into the service mesh:

* `user-ns`
* `product-ns`
* `order-ns`
* `notification-ns`

> The `payment-service` is deployed inside `order-ns`.

---

## Why Only Business Services?

We injected only business services initially to reduce deployment risk.

Infrastructure services such as:

* MongoDB
* OpenSearch
* Grafana
* Falco
* Kubernetes system pods

were intentionally excluded during the first phase to avoid disrupting logging, monitoring, and cluster operations.

---

## Setup Steps

### 1. Start Minikube Cluster

```bash
minikube start --nodes 3
```

### 2. Verify Cluster

```bash
kubectl get nodes
```

### 3. Install Linkerd

```bash
service-mesh/install-linkerd.bat
```

### 4. Inject Business Services

```bash
service-mesh/inject-business-services.bat
```

### 5. Verify Installation

```bash
linkerd check
linkerd viz check
```

---

## Verification

### Before Linkerd Injection

```text
user-service          1/1 Running
product-service       1/1 Running
order-service         1/1 Running
payment-service       1/1 Running
notification-service  1/1 Running
```

### After Linkerd Injection

```text
user-service          2/2 Running
product-service       2/2 Running
order-service         2/2 Running
payment-service       2/2 Running
notification-service  2/2 Running
```

The additional container is the **Linkerd Sidecar Proxy**, which intercepts and secures all service-to-service communication.

![Linkerd Sidecar Injection](screenshots/linkerd-sidecar-injection.png)

---

## Commands Used

### Install Linkerd

```bat
service-mesh\install-linkerd.bat
```

### Inject Business Services

```bat
service-mesh\inject-business-services.bat
```

### Verify Linkerd Installation

```bat
linkerd check
```

![Linkerd Check](screenshots/linkerd-check.png)

```bat
linkerd viz check
```

![Linkerd Viz Check](screenshots/linkerd-viz-check.png)

```bat
kubectl get pods -n linkerd
kubectl get pods -n linkerd-viz
```

### View Service Mesh Dashboard

```bat
linkerd viz dashboard
```

### View Traffic Statistics

```bat
linkerd viz stat deploy -n user-ns
linkerd viz stat deploy -n product-ns
linkerd viz stat deploy -n order-ns
linkerd viz stat deploy -n notification-ns
```

---

## Successfully Integrated Services

* user-service
* product-service
* order-service
* payment-service
* notification-service

---

## Linkerd Control Plane Components

* linkerd-identity
* linkerd-destination
* linkerd-proxy-injector

---

## Linkerd Viz Components

* metrics-api
* prometheus
* tap
* tap-injector
* web

![Linkerd Observability](screenshots/linkerd-observability.png)

---

## Benefits Achieved

* Automatic mTLS between microservices
* Secure service-to-service communication
* Traffic monitoring and observability
* Request success and failure tracking
* Latency monitoring
* Foundation for anomaly detection and security analytics

---

## Service Mesh Validation

The Linkerd Viz Dashboard confirms that the business microservices have been successfully integrated into the service mesh and are actively managed by Linkerd.

![Linkerd Dashboard](screenshots/linkerd-dashboard.png)
