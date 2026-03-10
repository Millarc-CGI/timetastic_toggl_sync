# run_monthly.ps1 - Monthly tasks: sync-users + report-monthly (all, admin)
# Project statistics (production) are on-demand via Slack - not automated here.
# Run: .\scripts\run_monthly.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$DateStr = Get-Date -Format "yyyy-MM-dd"
$LogFile = Join-Path $LogDir "run_monthly_$DateStr.log"

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

Write-Log "=== Monthly run started ==="
Write-Log "Using Python: $PythonExe"
if ($PythonExe -eq "python") {
    Write-Log "WARNING: Falling back to PATH - venv not found at: $VenvPython"
}
Set-Location $ProjectRoot

$env:PYTHONIOENCODING = "utf-8"

$prevErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"

try {
    Write-Log "1/3 sync-users (must run first - updates user mappings in SQLite)..."
    $out1 = & $PythonExe -m src.cli sync-users 2>&1
    $out1 | ForEach-Object { Write-Log ($_.ToString()) }
    if ($LASTEXITCODE -ne 0) { throw "sync-users failed (exit code $LASTEXITCODE)" }

    Write-Log "2/3 report-monthly --target all --send..."
    $out2 = & $PythonExe -m src.cli report-monthly --target all --send 2>&1
    $out2 | ForEach-Object { Write-Log ($_.ToString()) }
    if ($LASTEXITCODE -ne 0) { throw "report-monthly all failed (exit code $LASTEXITCODE)" }

    Write-Log "3/3 report-monthly --target admin --send..."
    $out3 = & $PythonExe -m src.cli report-monthly --target admin --send 2>&1
    $out3 | ForEach-Object { Write-Log ($_.ToString()) }
    if ($LASTEXITCODE -ne 0) { throw "report-monthly admin failed (exit code $LASTEXITCODE)" }

    Write-Log "=== Monthly run completed OK ==="
} catch {
    Write-Log "ERROR: $_"
    $ErrorActionPreference = $prevErrorAction
    exit 1
}
$ErrorActionPreference = $prevErrorAction
