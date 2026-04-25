@echo off
setlocal
cd /d "%~dp0"
title Docker DNS check (PyPI / builds)

echo ============================================================
echo  Docker DNS diagnostic
echo ============================================================
echo.
echo Pip errors like:
echo   Temporary failure in name resolution
echo   Failed to establish a new connection ... Errno -3
echo mean containers cannot resolve internet hostnames (pypi.org).
echo This is fixed in Docker Desktop, not in the project code.
echo.

where docker >nul 2>&1
if %errorlevel% neq 0 (
  echo [ERROR] docker not found in PATH.
  pause & exit /b 1
)

docker info >nul 2>&1
if %errorlevel% neq 0 (
  echo [ERROR] Docker is not running. Start Docker Desktop first.
  pause & exit /b 1
)

echo [1/2] Testing default container DNS (nslookup pypi.org)...
docker run --rm busybox:1.36 nslookup pypi.org >nul 2>&1
if %errorlevel% equ 0 (
  echo       OK — default DNS works. If builds still fail, try restarting Docker Desktop.
  echo.
  goto :done
)

echo       FAILED — containers cannot resolve pypi.org with default DNS.
echo.
echo [2/2] Testing with public DNS 8.8.8.8 on the container...
docker run --rm --dns 8.8.8.8 --dns 1.1.1.1 busybox:1.36 nslookup pypi.org >nul 2>&1
if %errorlevel% equ 0 (
  echo       OK with --dns 8.8.8.8 — your Docker daemon needs explicit DNS.
  echo.
  echo  ----- FIX (Docker Desktop) -----
  echo  1. Open Docker Desktop
  echo  2. Settings -^> Docker Engine
  echo  3. Merge this into the JSON (keep other keys, add or merge "dns"):
  echo.
  echo     "dns": ["8.8.8.8", "1.1.1.1"]
  echo.
  echo  4. Click "Apply and restart"
  echo  5. Run this script again — step [1/2] should pass.
  echo  --------------------------------
  echo.
) else (
  echo       Still FAILED even with 8.8.8.8.
  echo  Check: VPN (try disconnect), corporate firewall, or offline PC.
  echo  If you use an HTTP proxy, configure it in Docker Desktop -^> Settings -^> Resources -^> Proxies.
  echo.
)

:done
echo ============================================================
pause
