@echo off
setlocal
cd /d "%~dp0"
title HPE Control-Plane Monitor — Runner

echo ============================================================
echo  HPE Control-Plane Monitor - K8s Runner
echo ============================================================
echo.

REM ── Pre-flight: check required tools are installed ───────────
echo [CHECK] Verifying required tools...
set PREFLIGHT_OK=1

where docker >nul 2>&1
if %errorlevel% neq 0 (
  echo   [MISSING] docker  ^> Install Docker Desktop: https://www.docker.com/products/docker-desktop
  set PREFLIGHT_OK=0
)

where minikube >nul 2>&1
if %errorlevel% neq 0 (
  echo   [MISSING] minikube  ^> Install: https://minikube.sigs.k8s.io/docs/start/
  set PREFLIGHT_OK=0
)

where kubectl >nul 2>&1
if %errorlevel% neq 0 (
  echo   [MISSING] kubectl  ^> Comes with Docker Desktop (enable Kubernetes) or install separately
  set PREFLIGHT_OK=0
)

docker info >nul 2>&1
if %errorlevel% neq 0 (
  echo   [NOT RUNNING] Docker Desktop is installed but not running - please start it first.
  set PREFLIGHT_OK=0
)

if "%PREFLIGHT_OK%"=="0" (
  echo.
  echo  Pre-flight FAILED. Install the missing tools above, then re-run.
  pause & exit /b 1
)
echo   All tools found. OK.
echo.

REM ── Stop docker-compose to free CPU before minikube starts ───
echo [0] Stopping any docker-compose services (frees CPU)...
docker compose -f ..\..\docker-compose.yaml down >nul 2>&1
docker compose -f ..\docker-compose.yaml down >nul 2>&1
echo     Done (ignored if not running).
echo.

REM ── 1. Copy audit policy into minikube auto-sync dir ─────────
echo [1/5] Copying audit policy...
set CERT_DIR=%USERPROFILE%\.minikube\files\var\lib\minikube\certs
if not exist "%CERT_DIR%" mkdir "%CERT_DIR%"
copy /Y "%~dp0audit-policy.yaml" "%CERT_DIR%\audit-policy.yaml" >nul
echo      OK.
echo.

REM ── 2. Start minikube (1 node, resource-capped) ──────────────
echo [2/5] Starting minikube (1 node, 2 CPU, 3 GB RAM)...
echo      First run downloads kicbase image (~514 MB) - normal, be patient.
minikube start ^
  --driver=docker ^
  --nodes=1 ^
  --cpus=2 ^
  --memory=3000 ^
  --extra-config=apiserver.audit-policy-file=/var/lib/minikube/certs/audit-policy.yaml ^
  --extra-config=apiserver.audit-log-path=/var/log/kubernetes/audit/audit.log ^
  --extra-config=apiserver.audit-log-maxage=7 ^
  --extra-config=apiserver.audit-log-maxbackup=3 ^
  --extra-config=apiserver.audit-log-maxsize=100
if %errorlevel% neq 0 (
  echo.
  echo ERROR: minikube start failed. Check Docker Desktop is running.
  pause & exit /b 1
)
minikube update-context >nul
echo.
echo      Node status:
kubectl get nodes
echo.

REM ── 3. Patch kube-apiserver with audit-log hostPath volume ───
echo [3/5] Patching kube-apiserver audit-log volume mount...
docker exec minikube mkdir -p /var/log/kubernetes/audit

REM IMPORTANT: Copy to /root NOT /tmp — /tmp is noexec tmpfs inside minikube
docker cp "%~dp0patch-apiserver-audit-volume.py" minikube:/root/patch.py
if %errorlevel% neq 0 (
  echo ERROR: docker cp to minikube failed. Is Docker running and minikube up?
  pause & exit /b 1
)

REM Retry patch up to 6 times (manifest appears after kubelet init, ~30s)
for /L %%i in (1,1,6) do (
  docker exec minikube python3 /root/patch.py 2>nul
  if not errorlevel 1 goto patched
  echo      Waiting for kube-apiserver manifest... (attempt %%i/6)
  timeout /t 10 /nobreak >nul
)
echo WARNING: Patch may not have applied. Continuing...

:patched
echo      Waiting 15s for kube-apiserver to reload...
timeout /t 15 /nobreak >nul

REM ── 4. Apply manifests ────────────────────────────────────────
echo [4/5] Applying manifests...
kubectl apply -f namespace.yaml
timeout /t 2 /nobreak >nul
kubectl apply -f network-policy.yaml
kubectl apply -f mongo-deployment.yaml
kubectl apply -f mongo-service.yaml
kubectl apply -f audit-service.yaml
kubectl apply -f vector.yaml
kubectl apply -f kube-control-plane-audit-forwarder.yaml
kubectl apply -f user-deployment.yaml
kubectl apply -f user-service.yaml
kubectl apply -f product-deployment.yaml
kubectl apply -f product-service.yaml
kubectl apply -f order-deployment.yaml
kubectl apply -f order-service.yaml
kubectl apply -f payment-deployment.yaml
kubectl apply -f payment-service.yaml
kubectl apply -f notification-deployment.yaml
kubectl apply -f notification-service.yaml
kubectl apply -f hpa.yaml
kubectl apply -f pdb.yaml
kubectl apply -f control-plane.yaml
echo      Manifests applied.
echo.

REM ── Build all service images on minikube node ────────────────
if "%SKIP_IMAGE_BUILD%"=="1" (
  echo      SKIP_IMAGE_BUILD=1 - Skipping image builds.
) else (
  echo      Building service images on minikube node...
  echo      This takes 3-10 min total. Set SKIP_IMAGE_BUILD=1 to skip on re-runs.

  minikube image build -t user-service:latest         ..\user-service
  minikube image build -t product-service:latest      ..\product-service
  minikube image build -t order-service:latest        ..\order-service
  minikube image build -t payment-service:latest      ..\payment-service
  minikube image build -t notification-service:latest ..\notification-service
  minikube image build -t audit-service:latest        ..\audit-service

  echo      Rolling out updated pods...
  kubectl rollout restart -n user-ns          deployment/user-service        >nul 2>&1
  kubectl rollout restart -n product-ns       deployment/product-service     >nul 2>&1
  kubectl rollout restart -n order-ns         deployment/order-service       >nul 2>&1
  kubectl rollout restart -n order-ns         deployment/payment-service     >nul 2>&1
  kubectl rollout restart -n notification-ns  deployment/notification-service >nul 2>&1
  kubectl rollout restart -n ecommerce        deployment/audit-service       >nul 2>&1
  echo      All images built and deployments rolled out.
)
echo.

REM ── Restart Vector after everything is up ────────────────────
echo      Restarting k8s-audit-forwarder to pick up fresh connections...
kubectl rollout restart -n ecommerce daemonset/k8s-audit-forwarder >nul 2>&1

REM ── 5. Port-forwards ─────────────────────────────────────────
echo [5/5] Starting port-forwards in new windows (keep them open!)...
start "pf-audit"        cmd /k kubectl port-forward -n ecommerce        svc/audit-service        18015:8005
timeout /t 1 /nobreak >nul
start "pf-user"         cmd /k kubectl port-forward -n user-ns          svc/user-service         18100:80
timeout /t 1 /nobreak >nul
start "pf-product"      cmd /k kubectl port-forward -n product-ns       svc/product-service      18101:80
timeout /t 1 /nobreak >nul
start "pf-order"        cmd /k kubectl port-forward -n order-ns         svc/order-service        18102:80
timeout /t 1 /nobreak >nul
start "pf-payment"      cmd /k kubectl port-forward -n order-ns         svc/payment-service      18103:80
timeout /t 1 /nobreak >nul
start "pf-notification" cmd /k kubectl port-forward -n notification-ns  svc/notification-service 18104:80

echo.
echo ============================================================
echo  ALL DONE — keep the pf-* windows open!
echo ============================================================
echo   Control-Plane Monitor UI  :  http://127.0.0.1:18015/control-plane/ui
echo   HPE Audit Events JSON     :  http://127.0.0.1:18015/control-plane/events/hpe?limit=50
echo   User service              :  http://127.0.0.1:18100
echo   Product service           :  http://127.0.0.1:18101
echo   Order service             :  http://127.0.0.1:18102
echo   Payment service           :  http://127.0.0.1:18103
echo   Notification service      :  http://127.0.0.1:18104
echo ============================================================
echo.
echo Trigger test audit events:
echo   kubectl create namespace demo-ns ^&^& kubectl delete namespace demo-ns
echo.
echo TIP: To skip image build on future runs, run:
echo   SET SKIP_IMAGE_BUILD=1 ^&^& run-project.bat
echo.
echo This window stays open. Type EXIT to close.
cmd /k
