# Run every trigger-falco.bat command, then verify audit-service + Falco capture.
$ErrorActionPreference = "Continue"
$AUDIT = "http://127.0.0.1:18015"
$falcoRows = @()

function Run-Exec($label, $ns, $deploy, $args) {
    & kubectl exec -n $ns "deploy/$deploy" -- @args 2>&1 | Out-Null
    $code = $LASTEXITCODE
    $status = if ($code -eq 0) { "OK" } else { "RAN($code)" }
    Write-Host "  [$status] $label"
    return [PSCustomObject]@{ Label = $label; Exit = $code }
}

Write-Host "=== trigger-falco command execution ==="
$runs = @()
$runs += Run-Exec "Read sensitive file (shadow)" "order-ns" "order-service" @("cat", "/etc/shadow")
$runs += Run-Exec "Read sensitive file (sudoers)" "user-ns" "user-service" @("cat", "/etc/sudoers")
$runs += Run-Exec "Write below etc (touch)" "product-ns" "product-service" @("touch", "/etc/hacked_config")
$runs += Run-Exec "Write below etc (mkdir)" "order-ns" "order-service" @("mkdir", "/etc/malicious_startup")
1..5 | ForEach-Object {
    $runs += Run-Exec "Shell spawn $_" "user-ns" "user-service" @("sh", "-c", "echo Malicious shell $_")
}
$runs += Run-Exec "Package manager (apk)" "order-ns" "order-service" @("apk", "add", "nmap")
$runs += Run-Exec "Package manager (apt)" "product-ns" "product-service" @("apt-get", "install", "-y", "curl")
$runs += Run-Exec "Package manager (yum)" "user-ns" "user-service" @("yum", "install", "-y", "wget")
$runs += Run-Exec "Write binary dir (/bin/nc)" "user-ns" "user-service" @("touch", "/bin/nc")
$runs += Run-Exec "Write binary dir (cpuminer)" "order-ns" "order-service" @("touch", "/usr/local/bin/cpuminer")
$runs += Run-Exec "Read SSH (id_rsa)" "product-ns" "product-service" @("cat", "/root/.ssh/id_rsa")
$runs += Run-Exec "Read SSH (ssh_config)" "order-ns" "order-service" @("cat", "/etc/ssh/ssh_config")
$runs += Run-Exec "AWS credentials" "user-ns" "user-service" @("cat", "/root/.aws/credentials")
$runs += Run-Exec "GCP credentials" "product-ns" "product-service" @("cat", "/root/.ssh/google_compute_engine")
$runs += Run-Exec "System info (uname)" "order-ns" "order-service" @("uname", "-a")

Write-Host ""
Write-Host "Waiting 25s for audit + Falco pipeline..."
Start-Sleep -Seconds 25

Write-Host ""
Write-Host "=== Audit monitor API (falco-style rows) ==="
try {
    $resp = Invoke-WebRequest -Uri "$AUDIT/control-plane/events/monitor?limit=200" -UseBasicParsing -TimeoutSec 15
    $mon = $resp.Content | ConvertFrom-Json
    $falcoRows = @($mon.events | Where-Object {
        $_.data.source.requestingService -eq 'falco' -or ($_.data.network.classification -like 'falco*')
    })
    Write-Host "Falco-style monitor rows: $($falcoRows.Count)"
    $falcoRows | Select-Object -First 30 | ForEach-Object {
        Write-Host ("  {0} | {1} | {2}" -f $_.data.source.requestMethod, $_.data.source.subject, $_.data.network.classification)
    }
} catch {
    Write-Host "FAIL: cannot reach audit-service on port 18015. Open pf-audit window or run port-forward."
    Write-Host $_.Exception.Message
}

Write-Host ""
Write-Host "=== Raw event store ==="
try {
    $resp2 = Invoke-WebRequest -Uri "$AUDIT/control-plane/events?limit=300" -UseBasicParsing -TimeoutSec 15
    $raw = $resp2.Content | ConvertFrom-Json
    $falcoNative = @($raw.events | Where-Object { $_.source_type -eq 'falco' })
    $execAudit = @($raw.events | Where-Object { $_.classification -eq 'exec_access' })
    Write-Host "Native Falco events (source_type=falco): $($falcoNative.Count)"
    $falcoNative | Group-Object event_type | Sort-Object Count -Descending | ForEach-Object {
        Write-Host ("  Falco rule: {0} x{1}" -f $_.Name, $_.Count)
    }
    Write-Host "K8s exec audit events (exec_access): $($execAudit.Count)"
} catch {
    Write-Host "FAIL: raw events API"
    Write-Host $_.Exception.Message
}

Write-Host ""
Write-Host "=== Action label coverage (monitor API) ==="
$expected = @(
    "Read sensitive file",
    "Wrote under etc",
    "Spawned interactive shell",
    "Ran package manager",
    "Wrote binary directory",
    "Read SSH information",
    "Searched AWS credentials",
    "Collected system information"
)
if ($falcoRows.Count -gt 0) {
    $actions = $falcoRows | ForEach-Object { $_.data.source.requestMethod } | Select-Object -Unique
    foreach ($exp in $expected) {
        if ($actions -contains $exp) { Write-Host "  [LOGGED]  $exp" }
        else { Write-Host "  [MISSING] $exp" }
    }
} else {
    foreach ($exp in $expected) { Write-Host "  [MISSING] $exp" }
}

Write-Host ""
Write-Host "=== Falco daemon rule hits (recent logs) ==="
$patterns = @(
    "Read Sensitive File", "Write below etc", "Terminal Shell", "Package Management",
    "Write below binary", "ssh information", "AWS Credentials", "System info", "Contact K8S API"
)
$log = kubectl logs -n falco -l app.kubernetes.io/name=falco --tail=500 2>&1 | Out-String
foreach ($p in $patterns) {
    $n = ([regex]::Matches($log, [regex]::Escape($p), "IgnoreCase")).Count
    Write-Host ("  {0,-35} {1} hits" -f $p, $n)
}

Write-Host ""
Write-Host "=== Command execution summary ==="
Write-Host ("  Total commands run: {0}" -f $runs.Count)
Write-Host ("  Commands with exit 0-1: {0}" -f (@($runs | Where-Object { $_.Exit -le 1 }).Count))
