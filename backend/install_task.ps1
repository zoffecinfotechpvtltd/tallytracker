# Registers a Windows Task Scheduler task that starts the Tally dashboard
# (server + auto-sync loop) at logon, hidden (no console window), and
# restarts it automatically if it ever crashes.
#
# Run once from an ordinary PowerShell prompt (no admin needed for AtLogOn
# tasks scoped to the current user):
#   powershell -ExecutionPolicy Bypass -File install_task.ps1

$TaskName = "TallyTracker"

$pythonwCmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if ($pythonwCmd) {
    $pythonw = $pythonwCmd.Source
} else {
    $pythonExe = (Get-Command python.exe -ErrorAction Stop).Source
    $pythonw = Join-Path (Split-Path $pythonExe) "pythonw.exe"
    if (-not (Test-Path $pythonw)) {
        throw "Could not find pythonw.exe next to python.exe at '$pythonExe'. Is this a standard Python install?"
    }
}

$scriptPath = Join-Path $PSScriptRoot "run_server.py"
if (-not (Test-Path $scriptPath)) {
    throw "run_server.py not found at $scriptPath"
}

# Frontend is a React app now - main.py serves frontend/dist, which needs a
# build step. Build it here so a fresh checkout works with just this one
# script, same "always up after reboot" guarantee the scheduled task gives
# the backend.
$frontendDir = Join-Path $PSScriptRoot "..\frontend"
$npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCmd) { $npmCmd = Get-Command npm -ErrorAction SilentlyContinue }
if (-not $npmCmd) {
    throw "npm not found on PATH - install Node.js (https://nodejs.org) before running this script, it's needed to build the dashboard frontend."
}
Write-Host "Building frontend..."
Push-Location $frontendDir
try {
    & $npmCmd.Source install --no-fund --no-audit
    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
    & $npmCmd.Source run build
    if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
} finally {
    Pop-Location
}

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$scriptPath`"" -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Tally Live Entity Dashboard - background sync + local dashboard on http://127.0.0.1:8731/" `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName

Write-Host "Installed and started task '$TaskName'."
Write-Host "Runs at every logon from now on, silently, restarts itself if it crashes."
Write-Host "Dashboard: http://127.0.0.1:8731/"
Write-Host "Logs: $PSScriptRoot\server.log"
Write-Host ""
Write-Host "Check status:  Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "Stop now:      Stop-ScheduledTask -TaskName $TaskName"
Write-Host "Uninstall:     powershell -ExecutionPolicy Bypass -File uninstall_task.ps1"
