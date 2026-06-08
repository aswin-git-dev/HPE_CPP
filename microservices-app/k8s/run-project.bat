@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title microservices-Monitor — Runner

echo ============================================================
echo  microservices-Monitor - K8s Runner
echo ============================================================
echo  Build: 2026-06-08  Falco: use hyperv/virtualbox driver (not docker/WSL2)
echo  SKIP FLAGS: SET SKIP_IMAGE_BUILD=1 / SET SKIP_ML=1 / SET SKIP_KAFKA=1 / SET SKIP_FALCO=1
echo  DRIVER:     SET MINIKUBE_DRIVER=hyperv ^| virtualbox ^| docker  (auto if unset)
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
REM Falco needs a real Linux kernel. docker driver on WSL2 only gets network rules.
REM Auto-pick: hyperv ^> virtualbox ^> docker. Override: SET MINIKUBE_DRIVER=hyperv
for /f "delims=" %%D in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0pick-minikube-driver.ps1"') do set MINIKUBE_DRIVER=%%D
echo [2/5] Starting minikube driver=!MINIKUBE_DRIVER! (3 nodes, 2 CPU / 4 GB each^)...
if /I "!MINIKUBE_DRIVER!"=="docker" (
  echo      WARN: docker/WSL2 driver — Falco file/exec rules will NOT fire.
  echo            For real Falco: minikube delete, then SET MINIKUBE_DRIVER=hyperv and re-run.
)
echo      First run downloads kicbase image (~514 MB) - normal, be patient.
echo      4 GB per node: Kafka + OpenSearch + MongoDB need the headroom to avoid swap.
REM  --wait=apiserver,node_ready: block until cluster is truly healthy (avoids race conditions).
if not defined MINIKUBE_WAIT_TIMEOUT set MINIKUBE_WAIT_TIMEOUT=15m0s
minikube start ^
  --driver=!MINIKUBE_DRIVER! ^
  --nodes=3 ^
  --cpus=2 ^
  --memory=4096 ^
  --wait=apiserver,node_ready ^
  --wait-timeout=!MINIKUBE_WAIT_TIMEOUT! ^
  --extra-config=apiserver.audit-policy-file=/var/lib/minikube/certs/audit-policy.yaml
if errorlevel 1 (
  echo.
  echo   minikube start returned an error. Trying inline worker recovery...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "kubectl get nodes --no-headers 2>$null | Where-Object { $_ -match 'NotReady' } | ForEach-Object { $n=($_ -split '\s+')[0]; Write-Host \"  Restarting $n\"; minikube ssh -n $n 'sudo systemctl restart kubelet' 2>$null }; Start-Sleep 10"
  minikube start --wait=apiserver,node_ready --wait-timeout=10m0s 2>nul
)
if errorlevel 1 (
  echo.
  echo ERROR: minikube start failed.
  echo   Fix: minikube delete   then re-run. Ensure Docker has 14+ GB RAM for 3 nodes.
  pause & exit /b 1
)
minikube update-context >nul

REM ── Worker count: existing 1-node clusters are NOT upgraded by --nodes=3 ───
REM ── Inline worker recovery: fix any NotReady workers before continuing ───
echo      Checking for NotReady workers...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$nr = kubectl get nodes --no-headers 2>$null | Where-Object { $_ -match 'NotReady' }; if ($nr) { $nr | ForEach-Object { $n=($_ -split '\s+')[0]; Write-Host \"  Restarting kubelet on $n\"; minikube ssh -n $n 'sudo systemctl restart kubelet' 2>$null }; Write-Host '  Waiting 20s...'; Start-Sleep 20 } else { Write-Host '  All nodes Ready.' }"
kubectl wait --for=condition=Ready node --all --timeout=180s 2>nul

for /f %%n in ('kubectl get nodes --no-headers 2^>nul ^| find /c /v ""') do set TOTAL_NODES=%%n
if not defined TOTAL_NODES set TOTAL_NODES=0
if !TOTAL_NODES! LSS 3 (
  echo.
  echo   *** WARNING: Only !TOTAL_NODES! node^(s^). minikube-m02 / minikube-m03 do NOT exist yet.
  echo       Fix:  minikube delete   then re-run ^(creates fresh 3-node cluster^)
  echo       Or:   minikube node add --worker   ^(run twice; each several minutes^)
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
if /I "!MINIKUBE_DRIVER!"=="docker" (
  docker exec minikube mkdir -p /var/log/kubernetes/audit
  REM IMPORTANT: Copy to /root NOT /tmp — /tmp is noexec tmpfs inside minikube
  docker cp "%~dp0patch-apiserver-audit-volume.py" minikube:/root/patch.py
  if errorlevel 1 (
    echo ERROR: docker cp to minikube failed. Is Docker running and minikube up?
    pause & exit /b 1
  )
) else (
  minikube ssh -c "sudo mkdir -p /var/log/kubernetes/audit" >nul 2>&1
  minikube cp "%~dp0patch-apiserver-audit-volume.py" minikube:/root/patch.py
  if errorlevel 1 (
    echo ERROR: minikube cp to node failed. Is minikube up?
    pause & exit /b 1
  )
)

REM Retry patch up to 6 times — DO NOT use "goto" inside "for /L ... do ( )" (breaks cmd.exe)
set PATCH_TRY=0
:patch_retry
set /a PATCH_TRY+=1
if /I "!MINIKUBE_DRIVER!"=="docker" (
  docker exec minikube python3 /root/patch.py 2>nul
) else (
  minikube ssh -c "sudo python3 /root/patch.py" 2>nul
)
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
REM Namespace must exist first before anything else can land in it
kubectl apply -f namespace.yaml
timeout /t 2 /nobreak >nul

REM ── GROUP 1: Network + infrastructure (one kubectl call = much faster) ─────
kubectl apply ^
  -f network-policy.yaml ^
  -f mongo-deployment.yaml ^
  -f mongo-service.yaml ^
  -f opensearch.yaml ^
  -f opensearch-dashboards.yaml
REM Kafka applied separately so SKIP_KAFKA=1 can suppress it below

if /I "%SKIP_KAFKA%"=="1" (
  echo      SKIP_KAFKA=1 - skipping Kafka deployment.
) else (
  kubectl apply -f kafka.yaml -f allow-kafka.yaml
)

REM ── GROUP 2: Platform services (audit, vector, forwarder, secrets) ─────────
REM loki.yaml / grafana.yaml removed — using Grafana Cloud instead
kubectl apply ^
  -f grafana-cloud-secret.yaml ^
  -f vector-rbac.yaml ^
  -f audit-service.yaml ^
  -f vector.yaml ^
  -f kube-control-plane-audit-forwarder.yaml

REM ── GROUP 3: All microservices in one call ──────────────────────────────────
kubectl apply ^
  -f user-deployment.yaml   -f user-service.yaml ^
  -f product-deployment.yaml -f product-service.yaml ^
  -f order-deployment.yaml   -f order-service.yaml ^
  -f payment-deployment.yaml -f payment-service.yaml ^
  -f notification-deployment.yaml -f notification-service.yaml

REM ── GROUP 4: Policies + dashboard ──────────────────────────────────────────
kubectl apply -f hpa.yaml -f pdb.yaml -f control-plane.yaml

REM ISM Job: delete old job if exists (re-runs), then apply fresh
kubectl delete job opensearch-ism-setup -n ecommerce >nul 2>&1
kubectl apply -f opensearch-ism-job.yaml
echo      Manifests applied (OpenSearch, Grafana Cloud secret, vector-rbac, log + audit forwarders, ISM TTL).
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

  if /I "!MINIKUBE_DRIVER!"=="docker" (
    REM minikube image build only puts the image on the control-plane node.
    REM IMPORTANT: Must export from INSIDE minikube (docker exec minikube docker save), NOT from host Docker.
    echo      Distributing images to worker nodes IN PARALLEL (docker driver^)...
    if not exist "C:\Temp" mkdir "C:\Temp"
    powershell -NoProfile -ExecutionPolicy Bypass -Command ^
      "$services = 'user-service','product-service','order-service','payment-service','notification-service','audit-service'; $jobs = $services | ForEach-Object { $s = $_; Start-Job -ScriptBlock { param($svc) docker exec minikube docker save \"${svc}:latest\" -o \"/root/${svc}.tar\" 2>&1 | Out-Null; docker cp \"minikube:/root/${svc}.tar\" \"C:\Temp\${svc}.tar\" 2>&1 | Out-Null; docker cp \"C:\Temp\${svc}.tar\" \"minikube-m02:/root/${svc}.tar\" 2>&1 | Out-Null; docker exec minikube-m02 docker load -i \"/root/${svc}.tar\" 2>&1 | Out-Null; docker cp \"C:\Temp\${svc}.tar\" \"minikube-m03:/root/${svc}.tar\" 2>&1 | Out-Null; docker exec minikube-m03 docker load -i \"/root/${svc}.tar\" 2>&1 | Out-Null; Write-Output \"  $svc distributed.\" } -ArgumentList $s }; $jobs | Wait-Job | Receive-Job; $jobs | Remove-Job"
    del "C:\Temp\*.tar" >nul 2>&1
    echo      All images distributed.
  ) else (
    echo      VM driver: loading built images onto worker nodes via minikube image load...
    for %%S in (user-service product-service order-service payment-service notification-service audit-service) do (
      minikube image load %%S:latest -p minikube-m02 >nul 2>&1
      minikube image load %%S:latest -p minikube-m03 >nul 2>&1
    )
    echo      Worker image load done.
  )

echo      Rolling out pods in parallel...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$restarts = @('kubectl rollout restart -n user-ns deployment/user-service','kubectl rollout restart -n product-ns deployment/product-service','kubectl rollout restart -n order-ns deployment/order-service','kubectl rollout restart -n order-ns deployment/payment-service','kubectl rollout restart -n notification-ns deployment/notification-service','kubectl rollout restart -n ecommerce deployment/audit-service'); $jobs = $restarts | ForEach-Object { $cmd=$_; Start-Job -ScriptBlock { param($c) Invoke-Expression $c 2>&1 } -ArgumentList $cmd }; $jobs | Wait-Job | Out-Null; $jobs | Remove-Job; Write-Output '  All rollouts triggered.'"
echo      Image build + rollouts done.

:skip_image_build
echo.

REM ── Restart Vector daemonsets after everything is up ────────────────────────
echo      Restarting Vector daemonsets to pick up fresh connections...
kubectl rollout restart -n ecommerce daemonset/k8s-audit-forwarder >nul 2>&1
kubectl rollout restart -n ecommerce daemonset/log-forwarder >nul 2>&1

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
echo      Retry script: port-forward-retry.cmd
REM Fire all core port-forwards simultaneously — no 1s delays needed between them
start "pf-audit"         cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n ecommerce        svc/audit-service        18015:8005
start "audit-watch"      cmd /k call "%~dp0audit-pipeline-watch.cmd"
start "pf-user"          cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n user-ns          svc/user-service         18100:80
start "pf-product"       cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n product-ns       svc/product-service      18101:80
start "pf-order"         cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n order-ns         svc/order-service        18102:80
start "pf-payment"       cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n order-ns         svc/payment-service      18103:80
start "pf-notification"  cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n notification-ns  svc/notification-service 18104:80
REM Grafana port-forward removed — using Grafana Cloud at https://securelogger.grafana.net
start "pf-opensearch-ui" cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n ecommerce        svc/opensearch-dashboards 5601:5601

REM ── Smart Security Pipeline: Kafka + OpenSearch + ML + Alerts ─────────────
set "ML_DIR=%~dp0..\..\ml-anomaly-service"
set "MICROSERVICES_DIR=%~dp0.."

if /I "%SKIP_ML%"=="1" (
  echo.
  echo      SKIP_ML=1 - skipping Kafka port-forward, ML API and ML consumer.
  goto skip_ml_pipeline
)

echo.
echo [Security Pipeline] Starting Kafka, OpenSearch, ML API, ML consumer...
echo      Skip with: SET SKIP_ML=1 ^(saves ~300 MB RAM + several seconds^)

if /I "%SKIP_KAFKA%"=="1" (
  echo      SKIP_KAFKA=1 - skipping Kafka port-forward.
) else (
  REM Kafka port-forward for kafka_ml_consumer.py
  start "pf-kafka" cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n ecommerce svc/kafka 9092:9092
)

REM OpenSearch API port-forward for storing ML scored events
start "pf-opensearch-api" cmd /k call "%~dp0port-forward-retry.cmd" port-forward -n ecommerce svc/opensearch 9200:9200

REM Start ML API (paths relative to this script — works on any drive)
if not exist "%ML_DIR%\venv\Scripts\activate.bat" (
  echo      WARN: ML venv missing. Run once:
  echo        cd "%ML_DIR%"
  echo        python -m venv venv
  echo        venv\Scripts\pip install -r requirements.txt
) else (
  start "ml-api" cmd /k pushd "%ML_DIR%" ^&^& call venv\Scripts\activate ^&^& python -m uvicorn main:app --host 0.0.0.0 --port 8000
  REM Give uvicorn 5s to bind its port before the consumer tries to connect
  timeout /t 5 /nobreak >nul
  REM Start Kafka ML consumer: Kafka -> ML -> OpenSearch -> Email Alert
  start "ml-consumer-alerts" cmd /k pushd "%ML_DIR%" ^&^& call venv\Scripts\activate ^&^& python kafka_ml_consumer.py
  echo      ML API:     http://127.0.0.1:8000/docs
  echo      ML Consumer started ^(Kafka ^> ML ^> OpenSearch ^> alerts^)
)

:skip_ml_pipeline
echo.

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
echo   [Grafana Cloud]         https://securelogger.grafana.net  (login with Grafana Cloud account)
echo   [OpenSearch Dashboards] http://127.0.0.1:5601
echo   [OpenSearch API]        http://127.0.0.1:9200
echo   [ML API]                http://127.0.0.1:8000/docs
echo   [Anomaly Index]         http://127.0.0.1:9200/security-anomalies/_search?pretty
echo   [Alert Log]             %ML_DIR%\alerts.log

echo.
echo   [User service]          http://127.0.0.1:18100
echo   [Product service]       http://127.0.0.1:18101
echo   [Order service]         http://127.0.0.1:18102
echo   [Payment service]       http://127.0.0.1:18103
echo   [Notification service]  http://127.0.0.1:18104
echo ============================================================
echo.
REM ── Auto-open ecommerce UI only (skip if SKIP_BROWSER=1) ─────────────────
if /I "%SKIP_BROWSER%"=="1" (
  echo      SKIP_BROWSER=1 - skipping auto-open.
  goto skip_browser
)

echo   [SecureShop Ecommerce]  http://127.0.0.1:18000/ecommerce.html

start "ecommerce-ui" cmd /k pushd "%MICROSERVICES_DIR%" ^&^& python -m http.server 18000
start "" "http://127.0.0.1:18000/ecommerce.html"



REM return back to k8s folder
cd /d "%~dp0"

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
echo   SET SKIP_IMAGE_BUILD=1    skip Docker image builds on re-run (fastest re-run^)
echo   SET SKIP_ML=1             skip ML API + Kafka consumer windows ^(saves RAM^)
echo   SET SKIP_KAFKA=1          skip Kafka pod deploy + port-forward
echo   SET SKIP_AUDIT_WAIT=1     skip rollout wait at step 5
echo   SET SKIP_BROWSER=1        skip auto-opening browser tabs
echo   SET SKIP_FALCO=1          skip Helm install of Falco at the end
echo   SET MINIKUBE_WAIT_TIMEOUT=20m0s  extend minikube start timeout on slow machines
echo   SET MINIKUBE_DRIVER=hyperv       real Falco eBPF (needs Hyper-V on Windows Pro)
echo   SET MINIKUBE_DRIVER=virtualbox   real Falco eBPF (needs VirtualBox installed)
echo   docker driver on WSL2: only Falco network rules work; file/exec rules do not
echo   See sample-audit-triggers.txt for full event + classification catalog
echo.
echo This window stays open. Type EXIT to close.
cmd /k