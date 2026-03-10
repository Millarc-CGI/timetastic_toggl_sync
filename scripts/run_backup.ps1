# run_backup.ps1 - Backup SQLite database (copy + SQL dump, 90-day retention)
# Creates: sync_YYYY-MM-DD_HH-MM.db, .sha256, .sql
# Run: .\scripts\run_backup.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$DateStr = Get-Date -Format "yyyy-MM-dd"
$LogFile = Join-Path $LogDir "run_backup_$DateStr.log"

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

Write-Log "=== Backup run started ==="
Write-Log "Using Python: $PythonExe"
if ($PythonExe -eq "python") {
    Write-Log "WARNING: Falling back to PATH - venv not found at:"
    Write-Log "  $VenvPython"
    Write-Log "  $(Join-Path $ProjectRoot 'venv\Scripts\python.exe')"
}
Set-Location $ProjectRoot

# Force UTF-8 for Python output (avoids UnicodeEncodeError with emoji on Windows cp1250)
$env:PYTHONIOENCODING = "utf-8"

try {
    $BackupScript = Join-Path $ProjectRoot "scripts\backup_db.py"
    # Use Continue to avoid PowerShell throwing on Python stderr (e.g. traceback lines)
    $prevErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $output = & $PythonExe $BackupScript --backup-dir ./backups --retention-days 90 2>&1
    $ErrorActionPreference = $prevErrorAction
    $output | ForEach-Object { Write-Log ($_.ToString()) }
    if ($LASTEXITCODE -ne 0) { throw "backup_db.py failed (exit code $LASTEXITCODE)" }

    Write-Log "=== Backup run completed OK ==="
} catch {
    Write-Log "ERROR: $_"
    exit 1
}
