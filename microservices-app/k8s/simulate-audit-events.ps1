#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Generates audit events covering ALL 9 classification types.
  Missing types (exec_access, unauthorized_access, admission_webhook_change)
  are run LAST so they appear at the top of the UI (newest-first ordering).
#>

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "  K8s Audit Event Simulator v2 — All 9 Classifications" -ForegroundColor Cyan
Write-Host "============================================================`n" -ForegroundColor Cyan

# ── 0. SETUP ─────────────────────────────────────────────────────────────────
Write-Host "[SETUP] Creating base resources in sim-ns..." -ForegroundColor Yellow

kubectl create namespace sim-ns --dry-run=client -o yaml | kubectl apply -f -
kubectl create deployment sim-app --image=nginx -n sim-ns --dry-run=client -o yaml | kubectl apply -f -
kubectl expose deployment sim-app --port=80 -n sim-ns --dry-run=client -o yaml | kubectl apply -f - 2>$null
kubectl create secret generic sim-secret-base --from-literal=token=base123 -n sim-ns --dry-run=client -o yaml | kubectl apply -f -
kubectl create configmap sim-config-base --from-literal=env=base -n sim-ns --dry-run=client -o yaml | kubectl apply -f -

Write-Host "[SETUP] Waiting for sim-app pod to be RUNNING..." -ForegroundColor Yellow
kubectl rollout status deployment/sim-app -n sim-ns --timeout=90s

$POD = kubectl get pods -n sim-ns -l app=sim-app -o jsonpath="{.items[0].metadata.name}"
Write-Host "[SETUP] Ready. Target pod: $POD`n" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────────────
# Phases 1-5: bulk events (run first — they go deeper in the store)
# ─────────────────────────────────────────────────────────────────────────────

# 1. secret_access
Write-Host "[1/9] secret_access (x12)..." -ForegroundColor Magenta
for ($i = 1; $i -le 6; $i++) {
    kubectl create secret generic "sim-secret-$i" --from-literal=pass=p$i -n sim-ns 2>$null
    kubectl get secret "sim-secret-$i" -o yaml -n sim-ns | Out-Null
}
kubectl get secrets -n sim-ns | Out-Null
kubectl describe secret sim-secret-base -n sim-ns | Out-Null

# 2. rbac_change
Write-Host "[2/9] rbac_change (x12)..." -ForegroundColor Magenta
for ($i = 1; $i -le 4; $i++) {
    kubectl create role "sim-role-$i" --verb=get,list --resource=pods,secrets -n sim-ns 2>$null
    kubectl create rolebinding "sim-rb-$i" --role="sim-role-$i" --serviceaccount="sim-ns:default" -n sim-ns 2>$null
    kubectl patch role "sim-role-$i" -n sim-ns --type=json `
        -p '[{"op":"add","path":"/rules/-","value":{"apiGroups":[""],"resources":["configmaps"],"verbs":["get"]}}]' 2>$null
}

# 3. privilege_escalation_candidate
Write-Host "[3/9] privilege_escalation_candidate (x12)..." -ForegroundColor Magenta
for ($i = 1; $i -le 6; $i++) {
    kubectl create serviceaccount "esc-sa-$i" -n sim-ns 2>$null
    kubectl create token "esc-sa-$i" -n sim-ns 2>$null
}

# 4. config_change
Write-Host "[4/9] config_change (x12)..." -ForegroundColor Magenta
for ($i = 1; $i -le 6; $i++) {
    kubectl create configmap "sim-cm-$i" --from-literal=k=v$i -n sim-ns 2>$null
    $patch = "{`"data`":{`"k`":`"updated$i`"}}"
    kubectl patch configmap "sim-cm-$i" --type=merge -p $patch -n sim-ns 2>$null
}

# 5. destructive_change
Write-Host "[5/9] destructive_change (x12)..." -ForegroundColor Magenta
for ($i = 1; $i -le 4; $i++) {
    kubectl create deployment "victim-$i" --image=nginx -n sim-ns 2>$null
    kubectl delete deployment "victim-$i" -n sim-ns 2>$null
}
for ($i = 1; $i -le 3; $i++) {
    kubectl delete secret "sim-secret-$i" -n sim-ns 2>$null
}

# ─────────────────────────────────────────────────────────────────────────────
# Phases 6-8: THE MISSING TYPES — run LAST so they are newest in the store
# ─────────────────────────────────────────────────────────────────────────────

# 6. admission_webhook_change  ← run near end so it stays at top of results
Write-Host "[6/9] admission_webhook_change (x10)..." -ForegroundColor Magenta
for ($i = 1; $i -le 3; $i++) {
@"
apiVersion: admissionregistration.k8s.io/v1
kind: MutatingWebhookConfiguration
metadata:
  name: sim-mutating-wh-$i
webhooks:
  - name: sim$i.mutate.example.com
    admissionReviewVersions: ["v1"]
    clientConfig:
      url: "https://127.0.0.1:944$i/mutate"
    rules:
      - operations: ["CREATE","UPDATE"]
        apiGroups: [""]
        apiVersions: ["v1"]
        resources: ["pods"]
    sideEffects: None
    failurePolicy: Ignore
"@ | kubectl apply -f - 2>$null
    kubectl patch mutatingwebhookconfiguration "sim-mutating-wh-$i" --type=json `
        -p '[{"op":"replace","path":"/webhooks/0/failurePolicy","value":"Fail"}]' 2>$null
    kubectl patch mutatingwebhookconfiguration "sim-mutating-wh-$i" --type=json `
        -p '[{"op":"replace","path":"/webhooks/0/failurePolicy","value":"Ignore"}]' 2>$null
}
@"
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: sim-validating-wh
webhooks:
  - name: sim.validate.example.com
    admissionReviewVersions: ["v1"]
    clientConfig:
      url: "https://127.0.0.1:9449/validate"
    rules:
      - operations: ["DELETE"]
        apiGroups: [""]
        apiVersions: ["v1"]
        resources: ["pods"]
    sideEffects: None
    failurePolicy: Ignore
"@ | kubectl apply -f - 2>$null
kubectl patch validatingwebhookconfiguration sim-validating-wh --type=json `
    -p '[{"op":"replace","path":"/webhooks/0/failurePolicy","value":"Fail"}]' 2>$null

# 7. exec_access  <- run near end; wait explicitly for pod to be Running
Write-Host "[7/9] exec_access generating 15 events..." -ForegroundColor Magenta
kubectl wait pod -n sim-ns -l app=sim-app --for=condition=Ready --timeout=60s 2>$null
$POD = kubectl get pods -n sim-ns -l app=sim-app -o jsonpath="{.items[0].metadata.name}"
Write-Host "  Exec target: $POD" -ForegroundColor DarkGray
if ($POD) {
    for ($i = 1; $i -le 5; $i++) {
        kubectl exec $POD -n sim-ns -- ls /            2>$null
        kubectl exec $POD -n sim-ns -- cat /etc/hostname 2>$null
        kubectl exec $POD -n sim-ns -- env             2>$null
    }
} else {
    Write-Host "  WARN: no running pod found, skipping exec" -ForegroundColor Red
}

# 8. unauthorized_access ← run LAST so it's at the very top of the store
Write-Host "[8/9] unauthorized_access (x15)..." -ForegroundColor Magenta
# These resources always return 403 for anonymous in Minikube
$secureResources = @(
    "secrets", "serviceaccounts", "configmaps", "pods",
    "deployments.apps", "roles.rbac.authorization.k8s.io",
    "rolebindings.rbac.authorization.k8s.io", "clusterroles.rbac.authorization.k8s.io"
)
foreach ($res in $secureResources) {
    kubectl get $res --as=system:anonymous -n sim-ns 2>$null
    kubectl get $res --as=system:anonymous -n kube-system 2>$null
}
# Try write operations as anonymous (always 403)
kubectl create secret generic anon-secret --as=system:anonymous --from-literal=x=y -n sim-ns 2>$null
kubectl delete configmap sim-config-base --as=system:anonymous -n sim-ns 2>$null
kubectl create deployment anon-dep --image=nginx --as=system:anonymous -n sim-ns 2>$null

Write-Host "  Done.`n" -ForegroundColor Green

# ─────────────────────────────────────────────────────────────────────────────
# VERIFY
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "[VERIFY] Waiting 10s for Vector to forward all events..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

Write-Host "`n[VERIFY] Classification breakdown (newest 2000 events):`n" -ForegroundColor Cyan
$e = (Invoke-RestMethod "http://127.0.0.1:18015/control-plane/events/hpe?limit=2000").events
$e | Group-Object { $_.data.network.classification } | Sort-Object Count -Descending | `
    Format-Table @{L="Classification";E={$_.Name};Width=40}, @{L="Count";E={$_.Count}} -AutoSize

Write-Host "Total events fetched: $($e.Count)" -ForegroundColor Cyan

Write-Host "`n[VERIFY] Showing the 3 often-missing classifications from recent events:" -ForegroundColor Yellow
Write-Host "--- exec_access ---" -ForegroundColor DarkGray
$e | Where-Object { $_.data.network.classification -eq 'exec_access' } | Select-Object -First 3 | `
    ForEach-Object { "  $($_.time) | $($_.data.source.subject) | $($_.data.source.requestUrl)" }
Write-Host "--- unauthorized_access ---" -ForegroundColor DarkGray
$e | Where-Object { $_.data.network.classification -eq 'unauthorized_access' } | Select-Object -First 3 | `
    ForEach-Object { "  $($_.time) | $($_.data.source.subject) | $($_.data.network.statusCode)" }
Write-Host "--- admission_webhook_change ---" -ForegroundColor DarkGray
$e | Where-Object { $_.data.network.classification -eq 'admission_webhook_change' } | Select-Object -First 3 | `
    ForEach-Object { "  $($_.time) | $($_.data.source.subject) | $($_.data.source.requestUrl)" }

# ─────────────────────────────────────────────────────────────────────────────
# CLEANUP
# ─────────────────────────────────────────────────────────────────────────────
Write-Host "`n[CLEANUP] Removing all sim resources..." -ForegroundColor Yellow
kubectl delete mutatingwebhookconfiguration sim-mutating-wh-1 sim-mutating-wh-2 sim-mutating-wh-3 2>$null
kubectl delete validatingwebhookconfiguration sim-validating-wh 2>$null
kubectl delete clusterrolebinding $(kubectl get clusterrolebinding -o name | Select-String "esc-admin" | ForEach-Object { $_ -replace "clusterrolebinding.rbac.authorization.k8s.io/",""  }) 2>$null
kubectl delete namespace sim-ns 2>$null
Write-Host "[CLEANUP] Done.`n" -ForegroundColor Green
Write-Host "Refresh the UI: http://127.0.0.1:18015/control-plane/ui" -ForegroundColor Cyan
