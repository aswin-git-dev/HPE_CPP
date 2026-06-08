@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Update audit-service only

echo ============================================================
echo  audit-service hot-update  (no full restart needed)
echo ============================================================
echo.

REM ── 1. Rebuild only audit-service image ─────────────────────
echo [1/3] Building audit-service image...
minikube image build -t audit-service:latest ..\audit-service
if errorlevel 1 (
  echo ERROR: image build failed.
  pause & exit /b 1
)
echo      Build OK.
echo.

REM ── 2. Distribute to worker nodes ────────────────────────────
echo [2/3] Distributing image to worker nodes...
if not exist "C:\Temp" mkdir "C:\Temp"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "docker exec minikube docker save 'audit-service:latest' -o '/root/audit-service.tar' | Out-Null; docker cp 'minikube:/root/audit-service.tar' 'C:\Temp\audit-service.tar' | Out-Null; docker cp 'C:\Temp\audit-service.tar' 'minikube-m02:/root/audit-service.tar' | Out-Null; docker exec minikube-m02 docker load -i '/root/audit-service.tar' | Out-Null; docker cp 'C:\Temp\audit-service.tar' 'minikube-m03:/root/audit-service.tar' | Out-Null; docker exec minikube-m03 docker load -i '/root/audit-service.tar' | Out-Null; Write-Output '  audit-service distributed to all nodes.'"
del "C:\Temp\audit-service.tar" >nul 2>&1
echo      Distribution OK.
echo.

REM ── 3. Rolling restart (zero-downtime) ───────────────────────
echo [3/3] Rolling restart of audit-service deployment...
kubectl rollout restart -n ecommerce deployment/audit-service
echo      Waiting for rollout to finish (up to 3 min)...
kubectl rollout status -n ecommerce deployment/audit-service --timeout=180s
if errorlevel 1 (
  echo.
  echo   WARN: rollout did not finish in 3 min.
  echo   Check: kubectl get pods -n ecommerce -w
) else (
  echo.
  echo   audit-service updated successfully.
)

echo.
echo   Monitor UI:  http://127.0.0.1:18015/control-plane/ui
echo   (hard-refresh the browser: Ctrl+Shift+R)
echo.
pause
