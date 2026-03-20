@echo off
echo =======================================================
echo Kubernetes Cluster Setup - multi-namespace ecommerce
echo =======================================================

echo.
echo [1/8] Starting Minikube cluster with Audit Logging enabled...
echo Copying Audit configuration to minikube auto-sync directory...
if not exist "%USERPROFILE%\.minikube\files\etc\kubernetes" mkdir "%USERPROFILE%\.minikube\files\etc\kubernetes"
copy /Y audit-policy.yaml "%USERPROFILE%\.minikube\files\etc\kubernetes\audit-policy.yaml"
copy /Y audit-webhook.yaml "%USERPROFILE%\.minikube\files\etc\kubernetes\audit-webhook.yaml"
minikube start --driver=docker ^
  --extra-config=apiserver.audit-policy-file=/etc/kubernetes/audit-policy.yaml ^
  --extra-config=apiserver.audit-log-path=-

echo.
echo [2/8] Enabling necessary Minikube addons...
minikube addons enable ingress
minikube addons enable metrics-server

echo.
echo [3/8] Applying Namespaces (infrastructure and microservices)...
kubectl apply -f namespace.yaml
timeout /t 2 /nobreak >nul

echo.
echo [4/8] Applying Network Policies...
kubectl apply -f network-policy.yaml

echo.
echo [5/8] Applying Base Infrastructure (MongoDB, OpenSearch, Audit)...
kubectl apply -f mongo-deployment.yaml
kubectl apply -f mongo-service.yaml
kubectl apply -f opensearch.yaml
kubectl apply -f opensearch-dashboards.yaml
kubectl apply -f audit-service.yaml
kubectl apply -f vector.yaml
timeout /t 5 /nobreak >nul

echo.
echo [6/8] Applying Microservices (Deployments and Services)...
echo Deploying User Service...
kubectl apply -f user-deployment.yaml
kubectl apply -f user-service.yaml

echo Deploying Product Service...
kubectl apply -f product-deployment.yaml
kubectl apply -f product-service.yaml

echo Deploying Order & Payment Services...
kubectl apply -f order-deployment.yaml
kubectl apply -f order-service.yaml
kubectl apply -f payment-deployment.yaml
kubectl apply -f payment-service.yaml

echo Deploying Notification Service...
kubectl apply -f notification-deployment.yaml
kubectl apply -f notification-service.yaml

echo.
echo [7/8] Applying Supporting Resources (PDBs, HPAs, Ingress)...
kubectl apply -f hpa.yaml
kubectl apply -f pdb.yaml
kubectl apply -f ingress.yaml

echo.
echo [8/8] Applying Control Plane (Dashboard)...
kubectl apply -f control-plane.yaml

echo.
echo =======================================================
echo All manifests applied successfully!
echo.
echo To verify all namespaces:
echo   kubectl get namespaces
echo.
echo To verify all pods:
echo   kubectl get pods --all-namespaces
echo.
echo To access the Kubernetes Dashboard control plane:
echo   1. Run this command to get the login token:
echo      kubectl get secret dashboard-admin-token -n control-plane -o jsonpath="{.data.token}"^| base64 -d
echo   2. Access the dashboard via minikube's built-in command:
echo      minikube dashboard
echo =======================================================
pause
