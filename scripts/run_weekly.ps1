# run_weekly.ps1 - Weekly tasks: refresh-cache + report-weekly (reports include missing entries reminders)
# Run: .\scripts\run_weekly.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$DateStr = Get-Date -Format "yyyy-MM-dd"
$LogFile = Join-Path $LogDir "run_weekly_$DateStr.log"

# UTF-8 for Python output (cli uses emoji) and log file
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

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
    Add-Content -Path $LogFile -Value $Line -Encoding UTF8
}

Write-Log "=== Weekly run started ==="
Write-Log "Using Python: $PythonExe"
if ($PythonExe -eq "python") {
    Write-Log "WARNING: Falling back to PATH - venv not found at: $VenvPython"
}
Set-Location $ProjectRoot

$prevErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"

try {
    Write-Log "0/3 Health check (ping --check)..."
    $pingOut = & $PythonExe -m src.cli ping --check 2>&1
    $pingOut | ForEach-Object { Write-Log ($_.ToString()) }
    if ($LASTEXITCODE -ne 0) {
        Write-Log "ERROR: Health check failed - skipping weekly run"
        $ErrorActionPreference = $prevErrorAction
        exit 1
    }

    Write-Log "1/3 refresh-cache..."
    $out1 = & $PythonExe -m src.cli refresh-cache 2>&1
    $out1 | ForEach-Object { Write-Log ($_.ToString()) }
    if ($LASTEXITCODE -ne 0) { throw "refresh-cache failed (exit code $LASTEXITCODE)" }

    Write-Log "2/3 report-weekly --target all --send..."
    $out2 = & $PythonExe -m src.cli report-weekly --target all --send 2>&1
    $out2 | ForEach-Object { Write-Log ($_.ToString()) }
    if ($LASTEXITCODE -ne 0) { throw "report-weekly failed (exit code $LASTEXITCODE)" }

    Write-Log "=== Weekly run completed OK ==="
} catch {
    Write-Log "ERROR: $_"
    $ErrorActionPreference = $prevErrorAction
    exit 1
}
$ErrorActionPreference = $prevErrorAction
