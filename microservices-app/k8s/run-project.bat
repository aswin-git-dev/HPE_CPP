@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo  HPE Control-Plane Monitor — Full Project Runner
echo ============================================================
echo.

REM ── 1. Copy audit policy into minikube auto-sync dir ─────────
set CERT_DIR=%USERPROFILE%\.minikube\files\var\lib\minikube\certs
if not exist "%CERT_DIR%" mkdir "%CERT_DIR%"
copy /Y audit-policy.yaml "%CERT_DIR%\audit-policy.yaml" >nul
echo [1/6] Audit policy copied to minikube certs dir.

REM ── 2. Start minikube (audit log to file, not stdout) ────────
echo [2/6] Starting minikube with audit-log-path to file...
minikube start --driver=docker ^
  --nodes=2 ^
  --extra-config=apiserver.audit-policy-file=/var/lib/minikube/certs/audit-policy.yaml ^
  --extra-config=apiserver.audit-log-path=/var/log/kubernetes/audit/audit.log ^
  --extra-config=apiserver.audit-log-maxage=7 ^
  --extra-config=apiserver.audit-log-maxbackup=3 ^
  --extra-config=apiserver.audit-log-maxsize=100

if %errorlevel% neq 0 (
  echo ERROR: minikube start failed.
  pause & exit /b 1
)
echo Minikube started OK.

echo Enabling common addons (ingress, metrics-server)...
minikube addons enable ingress 2>nul
minikube addons enable metrics-server 2>nul

REM ── 3. Make sure kubectl context is set ──────────────────────
echo [3/6] Updating kubectl context...
minikube update-context
kubectl get nodes

REM ── 3b. Patch kube-apiserver manifest with audit-log volume ──
echo [3b] Patching kube-apiserver static pod manifest with audit-log volume...
docker exec minikube python3 -c "
manifest = open('/etc/kubernetes/manifests/kube-apiserver.yaml').read()
if 'audit-log' in manifest:
    print('already patched')
else:
    vm = '    - mountPath: /var/log/kubernetes/audit\n      name: audit-log\n'
    vol = '  - hostPath:\n      path: /var/log/kubernetes/audit\n      type: DirectoryOrCreate\n    name: audit-log\n'
    manifest = manifest.replace('  hostNetwork: true', vm + '  hostNetwork: true')
    manifest = manifest.replace('status: {}', vol + 'status: {}')
    open('/etc/kubernetes/manifests/kube-apiserver.yaml', 'w').write(manifest)
    print('PATCHED OK')
"
echo Waiting 20s for kube-apiserver to reload...
timeout /t 20 /nobreak >nul

REM ── 4. Apply all manifests ────────────────────────────────────
echo [4/6] Applying manifests...
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
kubectl apply -f ingress.yaml
kubectl apply -f control-plane.yaml

REM ── 5. Build service images on each minikube node ─────────────
echo [5/6] Building service images on minikube nodes...
for %%N in (minikube minikube-m02) do (
  echo   Building audit-service:ui1 on %%N...
  minikube image build -t audit-service:ui1 --node=%%N ..\audit-service
  echo   Building user-service:latest on %%N...
  minikube image build -t user-service:latest --node=%%N ..\user-service
  echo   Building product-service:latest on %%N...
  minikube image build -t product-service:latest --node=%%N ..\product-service
  echo   Building order-service:latest on %%N...
  minikube image build -t order-service:latest --node=%%N ..\order-service
  echo   Building payment-service:latest on %%N...
  minikube image build -t payment-service:latest --node=%%N ..\payment-service
  echo   Building notification-service:latest on %%N...
  minikube image build -t notification-service:latest --node=%%N ..\notification-service
)

REM ── Switch audit-service deployment to ui1 ───────────────────
kubectl -n ecommerce set image deployment/audit-service audit-service=audit-service:ui1

REM ── 6. Open port-forwards in separate windows ─────────────────
echo [6/6] Starting port-forwards (new windows — keep them open)...
start "pf-audit-monitor"        cmd /k kubectl port-forward -n ecommerce      svc/audit-service        18015:8005
timeout /t 1 >nul
start "pf-user-service"         cmd /k kubectl port-forward -n user-ns        svc/user-service         18100:80
timeout /t 1 >nul
start "pf-product-service"      cmd /k kubectl port-forward -n product-ns     svc/product-service      18101:80
timeout /t 1 >nul
start "pf-order-service"        cmd /k kubectl port-forward -n order-ns       svc/order-service        18102:80
timeout /t 1 >nul
start "pf-payment-service"      cmd /k kubectl port-forward -n order-ns       svc/payment-service      18103:80
timeout /t 1 >nul
start "pf-notification-service" cmd /k kubectl port-forward -n notification-ns svc/notification-service 18104:80

echo.
echo ============================================================
echo  DONE — open these in your browser after port-forward windows
echo  show "Forwarding from 127.0.0.1:..."
echo ============================================================
echo   Control-Plane Monitor UI  : http://127.0.0.1:18015/control-plane/ui
echo   HPE Audit Events JSON     : http://127.0.0.1:18015/control-plane/events/hpe?limit=50
echo   User service              : http://127.0.0.1:18100
echo   Product service           : http://127.0.0.1:18101
echo   Order service             : http://127.0.0.1:18102
echo   Payment service           : http://127.0.0.1:18103
echo   Notification service      : http://127.0.0.1:18104
echo ============================================================
echo.
pause
