@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo =======================================================
echo     ADVANCED FALCO ALERT TRIGGER SCRIPT 
echo =======================================================
echo Running a massive wave of simulated attacks across 
echo various namespaces to fully populate Grafana with
echo Critical, Warning, Notice, and Informational alerts!
echo.

set "TARGET_USER=kubectl exec -n user-ns deploy/user-service --"
set "TARGET_ORDER=kubectl exec -n order-ns deploy/order-service --"
set "TARGET_PRODUCT=kubectl exec -n product-ns deploy/product-service --"

echo [1/8] Generating "Critical: Read sensitive file" ...
rem Reading /etc/shadow directly triggers the highest severity alert.
%TARGET_ORDER% cat /etc/shadow >nul 2>&1
%TARGET_USER% cat /etc/sudoers >nul 2>&1

echo [2/8] Generating "Warning: Write below /etc" ...
rem Modifying configuration folders is heavily monitored.
%TARGET_PRODUCT% touch /etc/hacked_config >nul 2>&1
%TARGET_ORDER% mkdir /etc/malicious_startup >nul 2>&1

echo [3/8] Generating "Notice: Spawning Interactive Shell" ...
rem Just launching a shell wrapper triggers a notice. Let's do it 5 times for volume.
for /l %%x in (1, 1, 5) do (
    %TARGET_USER% sh -c "echo 'Malicious shell %%x'" >nul 2>&1
)

echo [4/8] Generating "Warning: Accessing Package Manager" ...
rem Attempting to install new tools in an immutable container triggers a warning.
%TARGET_ORDER% apk add nmap >nul 2>&1
%TARGET_PRODUCT% apt-get install curl >nul 2>&1
%TARGET_USER% yum install wget >nul 2>&1

echo [5/8] Generating "Warning: Write below binary dir" ...
rem Dropping payloads into executable paths.
%TARGET_USER% touch /bin/nc >nul 2>&1
%TARGET_ORDER% touch /usr/local/bin/cpuminer >nul 2>&1

echo [6/8] Generating "Error: Read ssh information" ...
%TARGET_PRODUCT% cat /root/.ssh/id_rsa >nul 2>&1
%TARGET_ORDER% cat /etc/ssh/ssh_config >nul 2>&1

echo [7/8] Generating "Critical: Find AWS/GCP Credentials" ...
%TARGET_USER% cat /root/.aws/credentials >nul 2>&1
%TARGET_PRODUCT% cat /root/.ssh/google_compute_engine >nul 2>&1

echo [8/8] Generating "Notice: System info discovery" ...
%TARGET_ORDER% uname -a >nul 2>&1

echo.
echo =======================================================
echo MASSIVE ATTACK SIMULATION COMPLETE!
echo Falco has captured dozens of events across all rules.
echo.
echo Please wait 15 seconds for LogQL to process everything,
echo then refresh the Grafana "Falco Runtime Security" Dashboard!
echo The charts will now be densely populated with data.
echo =======================================================
pause
