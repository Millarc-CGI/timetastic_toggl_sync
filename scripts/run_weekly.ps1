# run_weekly.ps1 - Weekly tasks: refresh-cache + send-reminders
# Run: .\scripts\run_weekly.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$DateStr = Get-Date -Format "yyyy-MM-dd"
$LogFile = Join-Path $LogDir "run_weekly_$DateStr.log"

# Find Python - venv in parent dir (project inside venv) or venv/.venv in project
$VenvParent = Split-Path -Parent $ProjectRoot
$VenvPython = Join-Path $VenvParent "Scripts\python.exe"
if (Test-Path $VenvPython) {
    $PythonExe = (Resolve-Path $VenvPython).Path
} elseif (Test-Path (Join-Path $ProjectRoot "venv\Scripts\python.exe")) {
    $PythonExe = (Resolve-Path (Join-Path $ProjectRoot "venv\Scripts\python.exe")).Path
} elseif (Test-Path (Join-Path $ProjectRoot ".venv\Scripts\python.exe")) {
    $PythonExe = (Resolve-Path (Join-Path $ProjectRoot ".venv\Scripts\python.exe")).Path
} else {
    $PythonExe = "python"
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-Log {
    param([string]$Message)
    $Line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $Message"
    Write-Host $Line
    Add-Content -Path $LogFile -Value $Line
}

Write-Log "=== Weekly run started ==="
Write-Log "Using Python: $PythonExe"
if ($PythonExe -eq "python") {
    Write-Log "WARNING: Falling back to PATH - venv not found at: $VenvPython"
}
Set-Location $ProjectRoot

$env:PYTHONIOENCODING = "utf-8"

$prevErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"

try {
    Write-Log "1/2 refresh-cache..."
    $out1 = & $PythonExe -m src.cli refresh-cache 2>&1
    $out1 | ForEach-Object { Write-Log ($_.ToString()) }
    if ($LASTEXITCODE -ne 0) { throw "refresh-cache failed (exit code $LASTEXITCODE)" }

    Write-Log "2/2 send-reminders..."
    $out2 = & $PythonExe -m src.cli send-reminders --days 7 2>&1
    $out2 | ForEach-Object { Write-Log ($_.ToString()) }
    if ($LASTEXITCODE -ne 0) { throw "send-reminders failed (exit code $LASTEXITCODE)" }

    Write-Log "=== Weekly run completed OK ==="
} catch {
    Write-Log "ERROR: $_"
    $ErrorActionPreference = $prevErrorAction
    exit 1
}
$ErrorActionPreference = $prevErrorAction
