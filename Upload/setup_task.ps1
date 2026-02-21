# ═══════════════════════════════════════════════════════════════
# Apollova Render Watcher — Task Scheduler Setup
# ═══════════════════════════════════════════════════════════════
# Run ONCE from the upload folder (as Admin):
#   cd C:\Users\aliba\Downloads\Apollova\Apollova\upload
#   .\setup_task.ps1
# ═══════════════════════════════════════════════════════════════

$TaskName = "Apollova Render Watcher"
$VbsPath = "$PSScriptRoot\start_watcher.vbs"
$WorkingDir = $PSScriptRoot
$Description = "Monitors After Effects render folders and auto-uploads videos (hidden)"

# Validate
if (-not (Test-Path $VbsPath)) {
    Write-Host "ERROR: start_watcher.vbs not found at $VbsPath" -ForegroundColor Red
    exit 1
}

# Remove existing task if present
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Create the task — runs the hidden .vbs launcher
$Action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "`"$VbsPath`"" `
    -WorkingDirectory $WorkingDir

$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -RestartCount 3 `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description $Description `
    -Force

# Verify
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host ""
    Write-Host "SUCCESS: '$TaskName' registered (hidden mode)!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Trigger:  Runs at login for $env:USERNAME" -ForegroundColor Cyan
    Write-Host "  Launcher: $VbsPath (no CMD window)" -ForegroundColor Cyan
    Write-Host "  WorkDir:  $WorkingDir" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Commands:" -ForegroundColor Yellow
    Write-Host "  Start now:    Start-ScheduledTask -TaskName '$TaskName'"
    Write-Host "  Stop:         Stop-ScheduledTask -TaskName '$TaskName'"
    Write-Host "  Check status: Get-ScheduledTask -TaskName '$TaskName' | Select State"
    Write-Host "  Remove:       Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
    Write-Host ""
} else {
    Write-Host "ERROR: Task registration failed" -ForegroundColor Red
    exit 1
}