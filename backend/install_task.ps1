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
