# Labels first two non-control-plane nodes as WorkerNode1 / WorkerNode2.
# Safe if nodes are named minikube-m02 or anything else.
$ErrorActionPreference = "Stop"
$json = kubectl get nodes -o json | ConvertFrom-Json
$workers = @()
foreach ($item in $json.items) {
    $labels = $item.metadata.labels
    $isCP = $null -ne $labels.'node-role.kubernetes.io/control-plane' -or $null -ne $labels.'node-role.kubernetes.io/master'
    if (-not $isCP) {
        $workers += $item.metadata.name
    }
}
# Sort for stable ordering (minikube-m02 before minikube-m03)
$workers = $workers | Sort-Object
if ($workers.Count -ge 1) {
    kubectl label node $workers[0] microservices-monitor/node-group=worker1 microservices-monitor/node-name=WorkerNode1 --overwrite 2>$null | Out-Null
    Write-Host ("      Labeled {0} -> WorkerNode1 (worker1)" -f $workers[0])
}
if ($workers.Count -ge 2) {
    kubectl label node $workers[1] microservices-monitor/node-group=worker2 microservices-monitor/node-name=WorkerNode2 --overwrite 2>$null | Out-Null
    Write-Host ("      Labeled {0} -> WorkerNode2 (worker2)" -f $workers[1])
}
if ($workers.Count -eq 0) {
    Write-Host "      WARN: No worker nodes found (only control-plane). Multi-node workloads will stay Pending."
}
if ($workers.Count -eq 1) {
    Write-Host "      WARN: Only 1 worker - need 2 for full layout. Run: minikube node add --worker"
}
exit 0
