# 🔐 Smart Security Logging Framework (Service Mesh Exploration)

This branch focuses on implementing a **Service Mesh (Istio)** to enhance security observability and traffic control within a Kubernetes-managed environment.

---

## 🚀 Project Goal

To leverage **Istio's Sidecar Proxy (Envoy)** to:

- Automatically capture high-fidelity security logs  
- Enforce encryption using **Mutual TLS (mTLS)**  
- Monitor service-to-service communication  
- Achieve all of the above **without modifying application code**

---

## 🏗️ Architecture

The exploration environment consists of two microservices deployed in a **Sidecar configuration**:

### 🔹 Security-Frontend
- Acts as a **client service**
- Simulates traffic and potential "attacker" requests

### 🔹 Security-Backend
- A **target Nginx service**
- Represents a protected resource

### 🔹 Istio Proxy (Envoy)
- Automatically injected into each pod
- Pods run in **2/2 Ready state**
- Acts as a **security sensor and traffic controller**

---

## 🛠️ Implementation Steps

### 1️⃣ Environment Setup

Tested on:
- **Minikube**
- **Istio 1.29.1**

```bash
minikube start
istioctl install --set profile=demo -y
```

---

### 2️⃣ Sidecar Injection

Enable automatic sidecar injection in the `default` namespace:

```bash
kubectl label namespace default istio-injection=enabled --overwrite
```

---

### 3️⃣ Deployment

Deploy microservices using:

```bash
kubectl apply -f k8s-mesh/services.yaml
```

---

## 🔍 Smart Security Features

### 🔐 Mutual TLS (mTLS)

Istio automatically enforces **Peer Authentication**, ensuring encrypted communication.

Verify mTLS:

```bash
istioctl x describe pod <frontend-pod-name>
```

---

### 📊 Security Log Analysis

The framework leverages **Envoy Access Logs** to capture detailed request data:

- **Source Identity**
  - Verified using **SPIFFE IDs**

- **Protocol Detection**
  - Identifies: HTTP / HTTPS / TCP

- **Response Flags**
  - Detect anomalies like:
    - `UH` → No healthy upstream
    - `URX` → Upstream reset

---

### 📈 Visual Observability

Use **Kiali Dashboard** to visualize service communication and security flows:

```bash
istioctl dashboard kiali
```

