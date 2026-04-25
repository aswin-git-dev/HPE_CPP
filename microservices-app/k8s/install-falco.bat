@echo off
setlocal EnableExtensions
cd /d "%~dp0"

REM Double-click: window stays open so you can read output/errors.
REM From run-project.bat: install-falco.bat NOPAUSE  (no pause; preserves errorlevel)
set "FALCO_BAT_NOPAUSE=0"
if /I "%~1"=="NOPAUSE" set "FALCO_BAT_NOPAUSE=1"

echo [Falco] Checking kubectl can reach the cluster...
kubectl cluster-info >nul 2>&1
if errorlevel 1 (
  echo.
  echo ERROR: Kubernetes API is not reachable ^(e.g. connection refused on 127.0.0.1^).
  echo kubectl tried to validate YAML against the server and could not open the API port.
  echo.
  echo Fix ^(Minikube^):
  echo   minikube start
  echo   minikube update-context
  echo Then run this script again ^(or use run-project.bat which starts the cluster first^).
  echo.
  goto :fail
)

echo [Falco] Applying namespace (must match NetworkPolicy label project=ecommerce-platform)...
kubectl apply -f "%~dp0falco-namespace.yaml"
if errorlevel 1 goto :fail

REM Helm: reload PATH from registry so winget installs work in THIS window ^(no need to reopen cmd^)
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command "$m=[Environment]::GetEnvironmentVariable('Path','Machine');$u=[Environment]::GetEnvironmentVariable('Path','User');Write-Output ($m+';'+$u)"`) do set "PATH=%%P"

set "HELM_CMD="
for /f "delims=" %%H in ('where.exe helm 2^>nul') do if not defined HELM_CMD set "HELM_CMD=%%H"

if exist "%ProgramFiles%\Helm\helm.exe" set "HELM_CMD=%ProgramFiles%\Helm\helm.exe"
if not defined HELM_CMD if exist "%ProgramFiles(x86)%\Helm\helm.exe" set "HELM_CMD=%ProgramFiles(x86)%\Helm\helm.exe"
if not defined HELM_CMD if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\helm.exe" set "HELM_CMD=%LOCALAPPDATA%\Microsoft\WinGet\Links\helm.exe"
if not defined HELM_CMD if exist "%LOCALAPPDATA%\Programs\Helm\helm.exe" set "HELM_CMD=%LOCALAPPDATA%\Programs\Helm\helm.exe"
if not defined HELM_CMD if exist "%ProgramData%\chocolatey\bin\helm.exe" set "HELM_CMD=%ProgramData%\chocolatey\bin\helm.exe"
if not defined HELM_CMD if exist "%USERPROFILE%\scoop\shims\helm.exe" set "HELM_CMD=%USERPROFILE%\scoop\shims\helm.exe"
if not defined HELM_CMD if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\helm.exe" set "HELM_CMD=%LOCALAPPDATA%\Microsoft\WindowsApps\helm.exe"

if not defined HELM_CMD for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command "try { (Get-Command helm -ErrorAction Stop).Source } catch { }"`) do if not defined HELM_CMD set "HELM_CMD=%%H"

REM Repo-local portable copy ^(no winget/PATH required^)
if not defined HELM_CMD if exist "%~dp0tools\helm\helm.exe" set "HELM_CMD=%~dp0tools\helm\helm.exe"

if not defined HELM_CMD if /I not "%SKIP_PORTABLE_HELM%"=="1" (
  echo.
  echo [Falco] Helm not on PATH. Downloading official portable Helm to k8s\tools\helm\ ^(get.helm.sh, ~20 MB^)...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0download-portable-helm.ps1" -DestRoot "%~dp0."
  if errorlevel 1 (
    echo ERROR: portable Helm download failed ^(network / TLS / disk^).
    goto :fail
  )
  if exist "%~dp0tools\helm\helm.exe" set "HELM_CMD=%~dp0tools\helm\helm.exe"
)

if not defined HELM_CMD (
  echo.
  echo ERROR: helm.exe still not found.
  echo   winget:  winget install -e --id Helm.Helm   ^(then new cmd, or set SKIP_PORTABLE_HELM=0^)
  echo   Manual:  https://github.com/helm/helm/releases  ^(windows-amd64 zip^)
  echo   Or fix network and re-run ^(script downloads to microservices-app\k8s\tools\helm\^).
  echo   To skip auto-download: set SKIP_PORTABLE_HELM=1
  echo.
  goto :fail
)

echo [Falco] Using Helm: %HELM_CMD%
"%HELM_CMD%" version

echo [Falco] Helm repo...
"%HELM_CMD%" repo add falcosecurity https://falcosecurity.github.io/charts 2>nul
"%HELM_CMD%" repo update
if errorlevel 1 goto :fail

echo [Falco] Installing/upgrading chart (may take several minutes)...
"%HELM_CMD%" upgrade --install falco falcosecurity/falco -n falco -f "%~dp0falco-values.yaml" --create-namespace --wait --timeout 15m
if errorlevel 1 goto :fail

echo.
echo Done. Falco DaemonSet + falcosidekick should POST alerts to audit-service.
echo Verify: kubectl get pods -n falco
echo          kubectl logs -n falco -l app.kubernetes.io/name=falcosidekick --tail=30

if "%FALCO_BAT_NOPAUSE%"=="0" (
  echo.
  echo Press any key to close this window...
  pause >nul
)
endlocal
exit /b 0

:fail
echo.
echo [Falco] Step failed - read the error lines above.
if "%FALCO_BAT_NOPAUSE%"=="0" (
  echo.
  echo Press any key to close this window...
  pause >nul
)
endlocal
exit /b 1
