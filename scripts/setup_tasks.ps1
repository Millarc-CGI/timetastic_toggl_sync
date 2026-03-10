# setup_tasks.ps1 - Register Windows Task Scheduler jobs for Timetastic-Toggl Sync
# Run from project root: .\scripts\setup_tasks.ps1
# Requires: PowerShell, ScheduledTasks module (built-in on Windows 10+)
# Note: tts_monthly uses schtasks.exe because Register-ScheduledTask has no -Monthly support

$ErrorActionPreference = "Stop"
$ScriptsDir = $PSScriptRoot
$ProjectRoot = Split-Path -Parent $ScriptsDir

$PsTasks = @(
    @{
        Name    = "tts_weekly"
        Script  = "run_weekly.ps1"
        Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "10:00"
        Desc    = "Timetastic-Toggl Sync: weekly refresh-cache + report-weekly"
    },
    @{
        Name    = "tts_backup"
        Script  = "run_backup.ps1"
        Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday -At "02:00"
        Desc    = "Timetastic-Toggl Sync: SQLite backup (90-day retention)"
    }
)

Write-Host "Registering Task Scheduler jobs for Timetastic-Toggl Sync"
Write-Host "Project root: $ProjectRoot"
Write-Host ""

foreach ($t in $PsTasks) {
    $ScriptPath = Join-Path $ScriptsDir $t.Script
    if (-not (Test-Path $ScriptPath)) {
        Write-Host "ERROR: Script not found: $ScriptPath"
        exit 1
    }

    $Action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`"" `
        -WorkingDirectory $ProjectRoot

    $Settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable

    $existing = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
    if ($existing) {
        Set-ScheduledTask -TaskName $t.Name -Action $Action -Trigger $t.Trigger -Settings $Settings -Description $t.Desc
        Write-Host "[OK] Updated: $($t.Name)"
    } else {
        Register-ScheduledTask `
            -TaskName $t.Name `
            -Action $Action `
            -Trigger $t.Trigger `
            -Settings $Settings `
            -Description $t.Desc
        Write-Host "[OK] Created: $($t.Name)"
    }
}

# Monthly task: schtasks.exe (Register-ScheduledTask has no -Monthly support)
$MonthlyScript = Join-Path $ScriptsDir "run_monthly.ps1"
if (-not (Test-Path $MonthlyScript)) {
    Write-Host "ERROR: Script not found: $MonthlyScript"
    exit 1
}
$MonthlyArg = "-NoProfile -ExecutionPolicy Bypass -File `"$MonthlyScript`""
schtasks /Create /TN "tts_monthly" /TR "powershell.exe $MonthlyArg" /SC MONTHLY /D 1 /ST 10:05 /F | Out-Null
Write-Host "[OK] Created/Updated: tts_monthly"

Write-Host ""
Write-Host "Done. Verify in Task Scheduler (taskschd.msc):"
Write-Host "  - tts_weekly  : Monday 10:00"
Write-Host "  - tts_monthly : 1st day of month 10:05"
Write-Host "  - tts_backup  : Monday 02:00"
