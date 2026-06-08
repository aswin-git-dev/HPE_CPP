@echo off
REM Watches audit-service /stats and restarts k8s-audit-forwarder if ingest stalls.
REM Requires pf-audit port-forward on 18015 (started by run-project.bat).
setlocal EnableDelayedExpansion
title audit-pipeline-watch
set STALL_ROUNDS=0
set LAST_PROCESSED=
set CHECK_SECS=90
set STALL_LIMIT=4

echo ============================================================
echo  Audit pipeline watchdog
echo  Checks http://127.0.0.1:18015/stats every %CHECK_SECS%s
echo  Restarts k8s-audit-forwarder if processed count stalls and
echo  newest event is older than 3 minutes.
echo  Keep pf-audit port-forward running. Ctrl+C to quit.
echo ============================================================
echo.

:loop
set CUR=
set NEWEST=
for /f "usebackq delims=" %%P in (`powershell -NoProfile -Command ^
  "try { $s = (Invoke-WebRequest -Uri 'http://127.0.0.1:18015/stats' -UseBasicParsing -TimeoutSec 8).Content | ConvertFrom-Json; $e = (Invoke-WebRequest -Uri 'http://127.0.0.1:18015/control-plane/events?limit=1' -UseBasicParsing -TimeoutSec 8).Content | ConvertFrom-Json; $ts = ''; if ($e.events -and $e.events.Count -gt 0) { $ts = $e.events[0].timestamp }; Write-Output ($s.total_processed.ToString() + '|' + $ts) } catch { Write-Output 'ERR|' }"`) do (
  for /f "tokens=1,2 delims=|" %%A in ("%%P") do (
    set CUR=%%A
    set NEWEST=%%B
  )
)

if /I "!CUR!"=="ERR" (
  echo [%TIME%] WARN: cannot reach audit-service on :18015 - is pf-audit running?
  set STALL_ROUNDS=0
  goto wait
)

if not defined LAST_PROCESSED set LAST_PROCESSED=!CUR!
set AGE_STALE=0
for /f %%S in ('powershell -NoProfile -Command ^
  "if ('!NEWEST!' -eq '') { '1' } else { $age = (Get-Date).ToUniversalTime() - [datetime]::Parse('!NEWEST!'); if ($age.TotalMinutes -gt 3) { '1' } else { '0' } }"') do set AGE_STALE=%%S

if "!CUR!"=="!LAST_PROCESSED!" if "!AGE_STALE!"=="1" (
  set /a STALL_ROUNDS+=1
  echo [%TIME%] WARN: processed stuck at !CUR!, newest=!NEWEST! ^(!STALL_ROUNDS!/%STALL_LIMIT%^)
  if !STALL_ROUNDS! geq %STALL_LIMIT% (
    echo [%TIME%] Restarting k8s-audit-forwarder...
    kubectl rollout restart -n ecommerce daemonset/k8s-audit-forwarder
    set STALL_ROUNDS=0
    set LAST_PROCESSED=
    timeout /t 30 /nobreak >nul
  )
) else (
  set STALL_ROUNDS=0
  set LAST_PROCESSED=!CUR!
  echo [%TIME%] OK processed=!CUR! newest=!NEWEST!
)

:wait
timeout /t %CHECK_SECS% /nobreak >nul
goto loop
