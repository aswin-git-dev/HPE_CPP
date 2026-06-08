# Resolve minikube driver for Falco-capable Linux kernel (hyperv > virtualbox > docker).
# Override: set MINIKUBE_DRIVER=hyperv|virtualbox|docker before run-project.bat
param(
    [string]$Preferred = $env:MINIKUBE_DRIVER
)

if ($Preferred -and $Preferred.Trim()) {
    Write-Output $Preferred.Trim().ToLower()
    exit 0
}

function Test-MinikubeDriver($name) {
    $out = minikube start --help 2>&1 | Out-String
    return $out -match "--driver="
}

# Hyper-V (Windows Pro) — real VM Linux kernel, full Falco eBPF
try {
    $hv = Get-WindowsOptionalFeature -Online -FeatureName Microsoft-Hyper-V -ErrorAction SilentlyContinue
    if ($hv -and $hv.State -eq 'Enabled') {
        Write-Output 'hyperv'
        exit 0
    }
} catch {}

# VirtualBox — real VM Linux kernel
if (Get-Command VBoxManage -ErrorAction SilentlyContinue) {
    Write-Output 'virtualbox'
    exit 0
}

# Fallback: docker on WSL2 — fast but Falco file/exec rules do not work
Write-Output 'docker'
