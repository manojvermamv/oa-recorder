# Registers oar as a Windows scheduled task that starts at boot and restarts on failure.
# Run once from the oa-recorder folder in an elevated PowerShell:
#   powershell -ExecutionPolicy Bypass -File deploy\oar-windows.ps1
# Put OAR_API_KEY in .env first (the task reads it through run-oar.cmd).
$dir = (Resolve-Path "$PSScriptRoot\..").Path
$cmd = Join-Path $dir "deploy\run-oar.cmd"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$cmd`"" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable
Register-ScheduledTask -TaskName "openalgo-recorder" -Action $action -Trigger $trigger `
    -Settings $settings -User "$env:USERDOMAIN\$env:USERNAME" -RunLevel Limited -Force
Start-ScheduledTask -TaskName "openalgo-recorder"
Write-Host "Registered and started. Log: $dir\data\oar.log"
