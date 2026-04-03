@echo off
REM Opens Control-Plane Monitor + Architecture map in your default browser.
REM Requires: kubectl port-forward to audit-service on 18015 (run-project.bat pf-audit window).

start "" "http://127.0.0.1:18015/control-plane/ui"
timeout /t 1 /nobreak >nul
start "" "http://127.0.0.1:18015/control-plane/architecture/ui"
echo Opened:
echo   http://127.0.0.1:18015/control-plane/ui
echo   http://127.0.0.1:18015/control-plane/architecture/ui
echo.
echo If pages fail: ensure the pf-audit window is running and audit-service pod is Ready.
