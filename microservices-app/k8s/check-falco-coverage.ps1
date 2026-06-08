$r = (Invoke-WebRequest -Uri 'http://127.0.0.1:18015/control-plane/events?limit=500' -UseBasicParsing -TimeoutSec 8).Content | ConvertFrom-Json
$falco = $r.events | Where-Object { $_.source_type -eq 'falco' }

Write-Host "Total Falco events in store: $($falco.Count)" -ForegroundColor Cyan

$rules = $falco | ForEach-Object {
    [PSCustomObject]@{
        Rule           = $_.event_type
        Classification = $_.classification
        NS             = if ($_.namespace) { $_.namespace } else { '<none>' }
        Pod            = if ($_.pod_name)  { $_.pod_name  } else { '<none>' }
    }
} | Sort-Object Rule, NS, Pod -Unique

$rules | Format-Table -AutoSize

# Check expected rules from trigger-falco.bat
$expected = @(
    'Read Sensitive File Untrusted',
    'Write below etc',
    'Terminal Shell in Container',
    'Launch Package Management Process in Container',
    'Write below binary dir',
    'Read ssh information',
    'Find AWS Credentials',
    'System Information Discovery'
)

Write-Host "`nCoverage check:" -ForegroundColor Yellow
$allRulesLower = $falco | ForEach-Object { $_.event_type.ToLower() }
foreach ($exp in $expected) {
    $hit = $allRulesLower | Where-Object { $_ -like "*$($exp.ToLower().Split(' ')[0])*" }
    if ($hit) {
        Write-Host "  [LOGGED]   $exp" -ForegroundColor Green
    } else {
        Write-Host "  [MISSING]  $exp" -ForegroundColor Red
    }
}
