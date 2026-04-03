@echo off
setlocal
cd /d "%~dp0"
title Trigger sample Kubernetes audit events

echo ============================================================
echo  Sample triggers — run while Minikube is up and audit UI is open
echo  UI: http://127.0.0.1:18015/control-plane/ui
echo ============================================================
echo.

where kubectl >nul 2>&1
if %errorlevel% neq 0 (
  echo ERROR: kubectl not in PATH.
  pause & exit /b 1
)

REM --- 1) Namespace lifecycle (strong audit signal) -------------------------
echo [1] Namespace create + delete (demo-audit-ns)...
kubectl create namespace demo-audit-ns 2>nul
timeout /t 2 /nobreak >nul
kubectl delete namespace demo-audit-ns --wait=true
echo      Done.
echo.

REM --- 2) ConfigMap + Secret (resource create/update) -------------------------
echo [2] ConfigMap + Secret in ecommerce...
kubectl -n ecommerce create configmap audit-sample-cm --from-literal=sample=key --dry-run=client -o yaml | kubectl apply -f -
kubectl -n ecommerce create secret generic audit-sample-secret --from-literal=token=dummy --dry-run=client -o yaml | kubectl apply -f -
echo      Done.
echo.

REM --- 3) Read-only API traffic (list/get — shows in audit policy if logged) --
echo [3] List pods / get node (read traffic)...
kubectl get pods -n ecommerce -o wide >nul
kubectl get nodes -o wide >nul
echo      Done.
echo.

REM --- 4) Short-lived pod (create + delete) ---------------------------------
echo [4] Ephemeral pod in ecommerce (create then delete)...
kubectl -n ecommerce run audit-sample-busybox --image=busybox:1.36 --restart=Never --command -- sleep 15 2>nul
timeout /t 3 /nobreak >nul
kubectl -n ecommerce delete pod audit-sample-busybox --wait=true --ignore-not-found=true
echo      Done.
echo.

REM --- 5) RBAC check (SelfSubjectAccessReview-style traffic) ------------------
echo [5] auth can-i (generates API calls)...
kubectl auth can-i create pods -n ecommerce
kubectl auth can-i delete secrets -n kube-system
echo      Done.
echo.

REM --- 6) Patch / annotate (update events) ----------------------------------
echo [6] Annotate sample ConfigMap (triggers update/patch in audit)...
kubectl -n ecommerce annotate configmap audit-sample-cm audit-sample-run="%DATE% %TIME%" --overwrite 2>nul
if %errorlevel% neq 0 echo      (Create step [2] first if this was skipped. )
echo      Done.
echo.

echo ============================================================
echo  Refresh the Control-Plane UI or JSON:
echo  http://127.0.0.1:18015/control-plane/events/hpe?limit=50
echo ============================================================
pause
