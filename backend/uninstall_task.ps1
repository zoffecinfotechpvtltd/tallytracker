# Removes the scheduled task installed by install_task.ps1.
#   powershell -ExecutionPolicy Bypass -File uninstall_task.ps1

$TaskName = "TallyTracker"

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "No task named '$TaskName' found - nothing to do."
    exit 0
}

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false

Write-Host "Removed task '$TaskName'."
Write-Host "Note: this does not stop an already-running process from a previous session -"
Write-Host "if the dashboard still responds at http://127.0.0.1:8731/, find and stop it with:"
Write-Host "  Get-NetTCPConnection -LocalPort 8731 -State Listen | Select OwningProcess"
Write-Host "  Stop-Process -Id <that pid> -Force"
