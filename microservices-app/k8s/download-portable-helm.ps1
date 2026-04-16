# Downloads official Helm for Windows into <k8s>/tools/helm/helm.exe (get.helm.sh).
param(
    [string]$DestRoot = $PSScriptRoot
)
$ErrorActionPreference = 'Stop'
$version = '3.15.4'
$url = "https://get.helm.sh/helm-v$version-windows-amd64.zip"
$tools = Join-Path $DestRoot 'tools'
$helmDir = Join-Path $tools 'helm'
$zipPath = Join-Path $tools 'helm-windows-amd64.zip'
$extract = Join-Path $tools '_helm_extract'

New-Item -ItemType Directory -Force -Path $helmDir | Out-Null
Write-Host "Downloading Helm $version from get.helm.sh ..."
Invoke-WebRequest -Uri $url -OutFile $zipPath -UseBasicParsing
if (Test-Path $extract) { Remove-Item -Recurse -Force $extract }
Expand-Archive -Path $zipPath -DestinationPath $extract -Force
$exe = Join-Path $extract 'windows-amd64\helm.exe'
if (-not (Test-Path $exe)) { throw "helm.exe not found in zip layout" }
Copy-Item -Path $exe -Destination (Join-Path $helmDir 'helm.exe') -Force
Remove-Item -Recurse -Force $extract
Remove-Item -Force $zipPath
$final = Join-Path $helmDir 'helm.exe'
Write-Host "OK: $final"
& $final version
