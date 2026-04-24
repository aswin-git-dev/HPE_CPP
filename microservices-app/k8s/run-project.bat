@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title microservices-Monitor — Runner

echo ============================================================
echo  microservices-Monitor - K8s Runner
echo ============================================================
echo  Build: 2026-04-02  Step 5 waits on: kubectl rollout status deployment/audit-service
echo  If you see "kubectl wait" and TWO pod names + "5 min ERROR" - OLD .bat - save/git pull this file.
echo ============================================================
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

REM ── 2. Start minikube (3 nodes: 1 control-plane + 2 workers) ────────────────
echo [2/5] Starting minikube (3 nodes, 2 CPU / 2 GB each)...
echo      First run downloads kicbase image (~514 MB) - normal, be patient.
REM  --- Point 4: On-disk apiserver audit log retention (rotation + TTL on disk) ---
REM       maxsize = rotate when file reaches this many MB
REM       maxbackup = keep at most this many rotated files (plus current)
REM       maxage    = delete rotated files older than this many days
REM       (Control-plane UI reads in-memory events in audit-service, not OpenSearch.)
minikube start ^
  --driver=docker ^
  --nodes=3 ^
  --cpus=2 ^
  --memory=2048 ^
  --extra-config=apiserver.audit-policy-file=/var/lib/minikube/certs/audit-policy.yaml
if errorlevel 1 (
  echo.
  echo ERROR: minikube start failed. Check Docker Desktop is running.
  pause & exit /b 1
)
minikube update-context >nul

REM ── Worker count: existing 1-node clusters are NOT upgraded by --nodes=3 ───
for /f %%n in ('powershell -NoProfile -Command "(kubectl get nodes -o json ^| ConvertFrom-Json).items.Count"') do set TOTAL_NODES=%%n
if not defined TOTAL_NODES set TOTAL_NODES=0
if !TOTAL_NODES! LSS 3 (
  echo.
  echo   *** WARNING: Only !TOTAL_NODES! node^(s^). Names minikube-m02 / minikube-m03 do NOT exist yet.
  echo       Why: If Minikube already existed as a single-node cluster, "minikube start --nodes=3"
  echo            does NOT add extra workers — it keeps the old profile.
  echo       Fix:  minikube delete
  echo             Then run this bat again ^(creates a fresh 3-node cluster^)
  echo       Or:   minikube node add --worker   ^(run twice; each can take several minutes^)
  echo.
)

REM ── Label workers by role ^(no hardcoded node names — avoids NotFound errors^) ───
echo      Labeling worker nodes...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0label-minikube-workers.ps1"
echo.
echo      Node layout:
kubectl get nodes -L microservices-monitor/node-group,microservices-monitor/node-name
echo.

REM ── 3. Patch kube-apiserver with audit-log hostPath volume ───
echo [3/5] Patching kube-apiserver audit-log volume mount...
docker exec minikube mkdir -p /var/log/kubernetes/audit

REM IMPORTANT: Copy to /root NOT /tmp — /tmp is noexec tmpfs inside minikube
docker cp "%~dp0patch-apiserver-audit-volume.py" minikube:/root/patch.py
if errorlevel 1 (
  echo ERROR: docker cp to minikube failed. Is Docker running and minikube up?
  pause & exit /b 1
)

REM Retry patch up to 6 times — DO NOT use "goto" inside "for /L ... do ( )" (breaks cmd.exe)
set PATCH_TRY=0
:patch_retry
set /a PATCH_TRY+=1
docker exec minikube python3 /root/patch.py 2>nul
if not errorlevel 1 goto patched
if !PATCH_TRY! geq 6 (
  echo WARNING: Patch may not have applied. Continuing...
  goto patched
)
echo      Waiting for kube-apiserver manifest... (attempt !PATCH_TRY!/6^)
timeout /t 10 /nobreak >nul
goto patch_retry

:patched
echo      Waiting for kube-apiserver to reboot and become ready...
timeout /t 10 /nobreak >nul

set WAIT_TRY=0
:wait_api
set /a WAIT_TRY+=1
kubectl get --raw /healthz >nul 2>&1
if not errorlevel 1 goto api_ready
if !WAIT_TRY! geq 20 (
  echo      WARN: API server took too long. Proceeding to apply...
  goto api_ready
)
timeout /t 3 /nobreak >nul
goto wait_api

:api_ready
echo      API server is READY.

REM ── 4. Apply manifests ────────────────────────────────────────
echo [4/5] Applying manifests...
if not exist "%~dp0namespace.yaml" (
  echo.
  echo ERROR: YAML not found next to this script: "%~dp0namespace.yaml"
  echo        The bat must stay in microservices-app\k8s with all *.yaml files.
  echo        Current dir is correct if you see this path. Re-clone or restore k8s\*.yaml
  pause & exit /b 1
)
kubectl apply -f namespace.yaml
timeout /t 2 /nobreak >nul
kubectl apply -f network-policy.yaml
kubectl apply -f mongo-deployment.yaml
kubectl apply -f mongo-service.yaml
kubectl apply -f opensearch.yaml
kubectl apply -f opensearch-dashboards.yaml
kubectl apply -f loki.yaml
kubectl apply -f grafana.yaml
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
REM ISM Job: delete old job if exists (re-runs), then apply fresh
kubectl delete job opensearch-ism-setup -n ecommerce >nul 2>&1
kubectl apply -f opensearch-ism-job.yaml
echo      Manifests applied (including OpenSearch, Loki, Grafana, ISM TTL).
echo.

REM ── Build images (use GOTO not giant "else (" blocks — nested parens break cmd.exe) ──
if /I "%SKIP_IMAGE_BUILD%"=="1" (
  echo      SKIP_IMAGE_BUILD=1 - Skipping image builds.
  goto skip_image_build
)

REM DNS pre-check (must NOT sit inside nested IF ( ) blocks — can abort the script silently)
if /I "%SKIP_DOCKER_DNS_CHECK%"=="1" goto dns_ok
docker run --rm busybox:1.36 nslookup pypi.org >nul 2>&1
if errorlevel 1 (
  echo.
  echo   [WARN] Docker DNS test failed - pip may fail during image build.
  echo          Fix: Docker Desktop - Settings - Docker Engine - add dns 8.8.8.8 and 1.1.1.1
  echo          Or run check-docker-dns.bat    Skip: set SKIP_DOCKER_DNS_CHECK=1
  echo.
  pause
)
:dns_ok

echo      Building service images (loaded on all Minikube nodes^)...
echo      This takes 3-10 min. Set SKIP_IMAGE_BUILD=1 to skip on re-runs.
echo.

minikube image build -t user-service:latest         ..\user-service
minikube image build -t product-service:latest      ..\product-service
minikube image build -t order-service:latest        ..\order-service
minikube image build -t payment-service:latest      ..\payment-service
minikube image build -t notification-service:latest ..\notification-service
minikube image build -t audit-service:latest        ..\audit-service

  REM minikube image build only puts the image on the primary (control-plane) node.
  REM IMPORTANT: Must export from INSIDE minikube (docker exec minikube docker save), NOT from host Docker.
  REM Host "docker save" saves a different (older) image that lacks new code -> "Not Found" on UI routes.
  echo      Distributing images to worker nodes (exporting from minikube node, not host Docker^)...
  if not exist "C:\Temp" mkdir "C:\Temp"
  for %%S in (user-service product-service order-service payment-service notification-service audit-service) do (
    docker exec minikube docker save %%S:latest -o /root/%%S.tar >nul 2>&1
    docker cp minikube:/root/%%S.tar "C:\Temp\%%S.tar" >nul 2>&1
    docker cp "C:\Temp\%%S.tar" minikube-m02:/root/%%S.tar >nul 2>&1
    docker exec minikube-m02 docker load -i /root/%%S.tar >nul 2>&1
    docker cp "C:\Temp\%%S.tar" minikube-m03:/root/%%S.tar >nul 2>&1
    docker exec minikube-m03 docker load -i /root/%%S.tar >nul 2>&1
    echo        %%S distributed to m02 + m03.
  )
  del "C:\Temp\*.tar" >nul 2>&1

echo      Rolling out pods on their designated nodes...
kubectl rollout restart -n user-ns          deployment/user-service        >nul 2>&1
kubectl rollout restart -n product-ns       deployment/product-service     >nul 2>&1
kubectl rollout restart -n order-ns         deployment/order-service       >nul 2>&1
kubectl rollout restart -n order-ns         deployment/payment-service     >nul 2>&1
kubectl rollout restart -n notification-ns  deployment/notification-service >nul 2>&1
kubectl rollout restart -n ecommerce        deployment/audit-service       >nul 2>&1
echo      Image build + rollouts done.

:skip_image_build
echo.

REM ── Restart Vector after everything is up ────────────────────
echo      Restarting k8s-audit-forwarder to pick up fresh connections...
kubectl rollout restart -n ecommerce daemonset/k8s-audit-forwarder >nul 2>&1

REM ── 5. Port-forwards ─────────────────────────────────────────
REM After rollout restart, the new pod can take 1-3+ min to become Ready (pull image, start container^).
REM SKIP_AUDIT_WAIT=1  -> skip wait entirely (port-forward windows may retry until pod is up^).
REM AUDIT_WAIT_SECS=N  -> wait N seconds (default 300 = 5 min^). Example: SET AUDIT_WAIT_SECS=600
if /I "%SKIP_AUDIT_WAIT%"=="1" (
  echo [5/5] SKIP_AUDIT_WAIT=1 - not waiting for Ready ^(check: kubectl get pods -n ecommerce -w^).
  goto after_audit_wait
)

REM Use "rollout status" NOT "kubectl wait pod -l app=..." — during rolling update TWO pods exist
REM (old + new^) and wait on all pods never finishes. Deployment status tracks the rollout correctly.
if not defined AUDIT_WAIT_SECS set AUDIT_WAIT_SECS=300
echo [5/5] Waiting for audit-service deployment rollout (up to !AUDIT_WAIT_SECS!s^)...
echo      Safe to wait - image pull + rollout can take a few minutes. To skip: SET SKIP_AUDIT_WAIT=1
echo      Longer: SET AUDIT_WAIT_SECS=600
kubectl rollout status -n ecommerce deployment/audit-service --timeout=!AUDIT_WAIT_SECS!s
if errorlevel 1 (
  echo.
  echo   WARN: rollout not finished in !AUDIT_WAIT_SECS!s. Continuing to port-forwards in 5s anyway...
  echo   Check: kubectl get pods -n ecommerce -w
  echo   kubectl describe deployment -n ecommerce audit-service
  timeout /t 5 /nobreak >nul
)
:after_audit_wait
echo      Starting port-forwards in new windows (keep them open^)...
echo      Retry script: port-forward-retry.cmd (ASCII - no UTF-8 dashes in console^)
start "pf-audit"        cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n ecommerce        svc/audit-service        18015:8005
timeout /t 1 /nobreak >nul
start "pf-user"         cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n user-ns          svc/user-service         18100:80
timeout /t 1 /nobreak >nul
start "pf-product"      cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n product-ns       svc/product-service      18101:80
timeout /t 1 /nobreak >nul
start "pf-order"        cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n order-ns         svc/order-service        18102:80
timeout /t 1 /nobreak >nul
start "pf-payment"      cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n order-ns         svc/payment-service      18103:80
timeout /t 1 /nobreak >nul
start "pf-notification" cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n notification-ns  svc/notification-service 18104:80
timeout /t 1 /nobreak >nul
start "pf-grafana"      cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n ecommerce        svc/grafana              3000:3000
timeout /t 1 /nobreak >nul
start "pf-opensearch-ui" cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n ecommerce       svc/opensearch-dashboards 5601:5601

echo.
echo [Falco] Optional runtime security (set SKIP_FALCO=1 to skip^).
if /I "%SKIP_FALCO%"=="1" (
  echo      SKIP_FALCO=1 - not installing Falco.
) else (
  where helm >nul 2>&1 && (
    call "%~dp0install-falco.bat" NOPAUSE
    if errorlevel 1 echo      NOTE: Falco Helm step failed — see messages above ^(kernel/driver or chart values^).
  ) || echo      Skipped: helm not on PATH. Run install-falco.bat when Helm is installed.
)

echo.
echo ============================================================
echo  ALL DONE - keep the pf-* windows open!
echo ============================================================
echo.
echo   [Monitor UI]            http://127.0.0.1:18015/control-plane/ui
echo   [Architecture]          http://127.0.0.1:18015/control-plane/architecture/ui
echo   [Monitor Audit JSON]    http://127.0.0.1:18015/control-plane/events/monitor?limit=50
echo   [Raw Events JSON]       http://127.0.0.1:18015/control-plane/events
echo.
echo   [Grafana Dashboards]    http://127.0.0.1:3000  (admin/admin)
echo   [OpenSearch Dashboards] http://127.0.0.1:5601
echo.
echo   [User service]          http://127.0.0.1:18100
echo   [Product service]       http://127.0.0.1:18101
echo   [Order service]         http://127.0.0.1:18102
echo   [Payment service]       http://127.0.0.1:18103
echo   [Notification service]  http://127.0.0.1:18104
echo ============================================================
echo.

REM ── Auto-open browser tabs (skip if SKIP_BROWSER=1) ─────────────────────
if /I "%SKIP_BROWSER%"=="1" (
  echo      SKIP_BROWSER=1 - skipping auto-open.
  goto skip_browser
)
echo      Opening browser tabs...
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:18015/control-plane/ui"
timeout /t 1 /nobreak >nul
start "" "http://127.0.0.1:18015/control-plane/architecture/ui"
timeout /t 1 /nobreak >nul
start "" "http://127.0.0.1:3000"
timeout /t 1 /nobreak >nul
start "" "http://127.0.0.1:5601"
:skip_browser

echo.
echo Trigger quick test audit events (copy + paste in a new terminal):
echo   kubectl create namespace demo-audit-ns
echo   kubectl -n ecommerce create secret generic demo-secret --from-literal=pw=test123
echo   kubectl -n ecommerce exec deployment/audit-service -- python -c "print('exec-test')"
echo   kubectl delete namespace demo-audit-ns
echo   kubectl -n ecommerce delete secret demo-secret
echo.
echo TIPs:
echo   SET SKIP_IMAGE_BUILD=1    skip Docker image builds on re-run
echo   SET SKIP_AUDIT_WAIT=1     skip rollout wait at step 5
echo   SET SKIP_BROWSER=1        skip auto-opening browser tabs
echo   SET SKIP_FALCO=1          skip Helm install of Falco at the end
echo   See sample-audit-triggers.txt for full event + classification catalog
echo.
echo This window stays open. Type EXIT to close.
cmd /k
