@echo off
REM Re-runs kubectl port-forward when it exits. Use ASCII only (no UTF-8 dashes) for cmd.exe.
setlocal EnableDelayedExpansion
if "%~1"=="" (
  echo Usage: port-forward-retry.cmd kubectl-args...
  echo Example: port-forward-retry.cmd port-forward -n ecommerce svc/audit-service 18015:8005
  exit /b 1
)
set /a FAILS=0
:loop
kubectl %*
set /a FAILS+=1
echo.
echo [%TIME%] Port-forward stopped - reconnecting in 3s... (Ctrl+C to quit^)
if "!FAILS!"=="1" (
  echo.
  echo   If error says Pending: pods are not Running yet. Fix the cluster first:
  echo     kubectl get pods -A
  echo     kubectl describe pod -n ecommerce -l app=audit-service
  echo   Port-forward cannot work until at least one pod is Running.
  echo.
)
if "!FAILS!"=="20" (
  echo.
  echo   Still failing after many tries. Stop this window (Ctrl+C^) and fix scheduling/images.
  echo   Common: minikube memory too low, ImagePullBackOff, or kubectl context wrong.
  echo.
)
timeout /t 3 /nobreak >nul
goto loop
