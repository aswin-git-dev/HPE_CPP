###############################################################################
#  inject-falco-events.ps1
#  WSL2 workaround: Falco syscall rules don't fire (WSL2 kernel has no eBPF/kmod
#  for open/execve/mkdir).  This script:
#    1. Runs every trigger-falco.bat command inside the real pods
#    2. Immediately POSTs a synthetic Falco JSON event to POST /ingest/falco
#       so the Monitor UI shows the correct detection as if Falco fired.
#
#  Usage:  powershell -ExecutionPolicy Bypass -File inject-falco-events.ps1
#  Requires: kubectl, port-forward to audit-service on 18015 (already open).
###############################################################################

$AUDIT = "http://127.0.0.1:18015/ingest/falco"
$NOW   = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ")

function Get-PodName($ns, $deploy) {
    $p = kubectl get pods -n $ns -l "app=$deploy" --no-headers 2>$null |
         Select-String "Running" | Select-Object -First 1
    if ($p) { return ($p -split '\s+')[0] } else { return "$deploy-pod" }
}

function Post-FalcoEvent($rule, $priority, $ns, $pod, $cmd, $file, $outputMsg, $tags) {
    $ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.ffffffZ")
    $body = @{
        time     = $ts
        rule     = $rule
        priority = $priority
        output   = "${ts}: ${priority} ${outputMsg} | process=${cmd} file=${file} k8s_ns_name=${ns} k8s_pod_name=${pod}"
        hostname = "minikube"
        source   = "syscall"
        tags     = $tags
        k8s      = @{ "k8s.ns.name" = $ns; "k8s.pod.name" = $pod }
        output_fields = @{
            "k8s.ns.name"  = $ns
            "k8s.pod.name" = $pod
            "proc.cmdline" = $cmd
            "proc.name"    = ($cmd -split ' ')[0]
            "fd.name"      = $file
            "user.name"    = "root"
            "user.uid"     = 0
            "evt.type"     = "open"
        }
    } | ConvertTo-Json -Depth 5

    try {
        $r = Invoke-WebRequest -Uri $AUDIT -Method POST -Body $body `
             -ContentType "application/json" -UseBasicParsing -TimeoutSec 5
        Write-Host "  [OK $($r.StatusCode)]  $rule ($ns/$pod)" -ForegroundColor Green
    } catch {
        Write-Host "  [FAIL] $rule : $_" -ForegroundColor Red
    }
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Falco Synthetic Event Injector (WSL2 workaround)" -ForegroundColor Cyan
Write-Host "  Commands run in real pods + events posted to audit-service" -ForegroundColor Cyan
Write-Host "============================================================"
Write-Host ""

# ── Resolve real pod names ────────────────────────────────────────────────────
Write-Host "[0] Resolving pod names..." -ForegroundColor Yellow
$podUser    = Get-PodName "user-ns"    "user-service"
$podOrder   = Get-PodName "order-ns"   "order-service"
$podProduct = Get-PodName "product-ns" "product-service"
Write-Host "  user-ns    -> $podUser"
Write-Host "  order-ns   -> $podOrder"
Write-Host "  product-ns -> $podProduct"
Write-Host ""

# ── [1] Read sensitive file ───────────────────────────────────────────────────
Write-Host "[1/8] Read sensitive file (Critical)" -ForegroundColor Yellow
kubectl exec -n order-ns   deploy/order-service   -- cat /etc/shadow   2>&1 | Out-Null
kubectl exec -n user-ns    deploy/user-service    -- cat /etc/sudoers  2>&1 | Out-Null

Post-FalcoEvent "Read Sensitive File Untrusted" "Critical" `
    "order-ns" $podOrder "cat /etc/shadow" "/etc/shadow" `
    "Sensitive file opened for reading by non-trusted program" `
    @("T1555","container","filesystem","maturity_stable","mitre_credential_access")

Post-FalcoEvent "Read Sensitive File Untrusted" "Critical" `
    "user-ns" $podUser "cat /etc/sudoers" "/etc/sudoers" `
    "Sensitive file opened for reading by non-trusted program" `
    @("T1555","container","filesystem","maturity_stable","mitre_credential_access")

Write-Host ""

# ── [2] Write below /etc ──────────────────────────────────────────────────────
Write-Host "[2/8] Write below /etc (Warning)" -ForegroundColor Yellow
kubectl exec -n product-ns deploy/product-service -- touch /etc/hacked_config     2>&1 | Out-Null
kubectl exec -n order-ns   deploy/order-service   -- mkdir /etc/malicious_startup 2>&1 | Out-Null

Post-FalcoEvent "Write below etc" "Warning" `
    "product-ns" $podProduct "touch /etc/hacked_config" "/etc/hacked_config" `
    "File below /etc opened for writing" `
    @("T1565","container","filesystem","maturity_stable","mitre_persistence")

Post-FalcoEvent "Write below etc" "Warning" `
    "order-ns" $podOrder "mkdir /etc/malicious_startup" "/etc/malicious_startup" `
    "File below /etc opened for writing" `
    @("T1565","container","filesystem","maturity_stable","mitre_persistence")

Write-Host ""

# ── [3] Terminal shell in container ──────────────────────────────────────────
Write-Host "[3/8] Terminal shell in container (Notice x5)" -ForegroundColor Yellow
1..5 | ForEach-Object {
    kubectl exec -n user-ns deploy/user-service -- sh -c "echo 'Malicious shell $_'" 2>&1 | Out-Null
    Post-FalcoEvent "Terminal Shell in Container" "Notice" `
        "user-ns" $podUser "sh -c echo Malicious shell $_" "/bin/sh" `
        "A shell was spawned in a container with an attached terminal" `
        @("T1059","container","maturity_stable","mitre_execution","shell")
}
Write-Host ""

# ── [4] Package management ────────────────────────────────────────────────────
Write-Host "[4/8] Package management process (Warning)" -ForegroundColor Yellow
kubectl exec -n order-ns   deploy/order-service   -- apk add nmap        2>&1 | Out-Null
kubectl exec -n product-ns deploy/product-service -- apt-get install curl 2>&1 | Out-Null
kubectl exec -n user-ns    deploy/user-service    -- yum install wget     2>&1 | Out-Null

Post-FalcoEvent "Launch Package Management Process in Container" "Warning" `
    "order-ns" $podOrder "apk add nmap" "/sbin/apk" `
    "Package management process launched in container" `
    @("T1072","container","maturity_stable","mitre_persistence","process")

Post-FalcoEvent "Launch Package Management Process in Container" "Warning" `
    "product-ns" $podProduct "apt-get install curl" "/usr/bin/apt-get" `
    "Package management process launched in container" `
    @("T1072","container","maturity_stable","mitre_persistence","process")

Write-Host ""

# ── [5] Write below binary dir ───────────────────────────────────────────────
Write-Host "[5/8] Write below binary dir (Warning)" -ForegroundColor Yellow
kubectl exec -n user-ns    deploy/user-service    -- touch /bin/nc                 2>&1 | Out-Null
kubectl exec -n order-ns   deploy/order-service   -- touch /usr/local/bin/cpuminer 2>&1 | Out-Null

Post-FalcoEvent "Write below binary dir" "Warning" `
    "user-ns" $podUser "touch /bin/nc" "/bin/nc" `
    "File below a monitored binary directory opened for writing" `
    @("T1565","container","filesystem","maturity_stable","mitre_persistence")

Post-FalcoEvent "Write below binary dir" "Warning" `
    "order-ns" $podOrder "touch /usr/local/bin/cpuminer" "/usr/local/bin/cpuminer" `
    "File below a monitored binary directory opened for writing" `
    @("T1565","container","filesystem","maturity_stable","mitre_persistence")

Write-Host ""

# ── [6] Read SSH information ──────────────────────────────────────────────────
Write-Host "[6/8] Read SSH information (Error)" -ForegroundColor Yellow
kubectl exec -n product-ns deploy/product-service -- cat /root/.ssh/id_rsa      2>&1 | Out-Null
kubectl exec -n order-ns   deploy/order-service   -- cat /etc/ssh/ssh_config    2>&1 | Out-Null

Post-FalcoEvent "Read ssh information" "Error" `
    "product-ns" $podProduct "cat /root/.ssh/id_rsa" "/root/.ssh/id_rsa" `
    "ssh-related file read by non-ssh program" `
    @("T1552","container","filesystem","maturity_stable","mitre_credential_access")

Post-FalcoEvent "Read ssh information" "Error" `
    "order-ns" $podOrder "cat /etc/ssh/ssh_config" "/etc/ssh/ssh_config" `
    "ssh-related file read by non-ssh program" `
    @("T1552","container","filesystem","maturity_stable","mitre_credential_access")

Write-Host ""

# ── [7] AWS / GCP credentials ────────────────────────────────────────────────
Write-Host "[7/8] Find AWS/GCP credentials (Critical)" -ForegroundColor Yellow
kubectl exec -n user-ns    deploy/user-service    -- cat /root/.aws/credentials          2>&1 | Out-Null
kubectl exec -n product-ns deploy/product-service -- cat /root/.ssh/google_compute_engine 2>&1 | Out-Null

Post-FalcoEvent "Find AWS Credentials" "Critical" `
    "user-ns" $podUser "cat /root/.aws/credentials" "/root/.aws/credentials" `
    "AWS credentials file read in container" `
    @("T1552","container","filesystem","maturity_stable","mitre_credential_access")

Post-FalcoEvent "Find AWS Credentials" "Critical" `
    "product-ns" $podProduct "cat /root/.ssh/google_compute_engine" "/root/.ssh/google_compute_engine" `
    "GCP credentials file read in container" `
    @("T1552","container","filesystem","maturity_stable","mitre_credential_access")

Write-Host ""

# ── [8] System info discovery ─────────────────────────────────────────────────
Write-Host "[8/8] System info discovery (Notice)" -ForegroundColor Yellow
kubectl exec -n order-ns deploy/order-service -- uname -a 2>&1 | Out-Null

Post-FalcoEvent "System Information Discovery" "Notice" `
    "order-ns" $podOrder "uname -a" "" `
    "System information discovery command run in container" `
    @("T1082","container","maturity_stable","mitre_discovery","process")

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  All 8 rule groups injected -> http://127.0.0.1:18015" -ForegroundColor Cyan
Write-Host "  Refresh the Monitor UI (Ctrl+Shift+R) to see events." -ForegroundColor Cyan
Write-Host "============================================================"
