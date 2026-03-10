# setup_venv.ps1 - Install project dependencies into the venv
# Uses python -m pip to avoid broken pip.exe (e.g. wrong path in launcher)
# Run from project root: .\scripts\setup_venv.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

# Find venv Python (same logic as run_backup.ps1)
$VenvParent = Split-Path -Parent $ProjectRoot
$VenvPython = Join-Path $VenvParent "Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "ERROR: venv Python not found at: $VenvPython"
    Write-Host "Create venv first: python -m venv $VenvParent"
    exit 1
}

$RequirementsPath = Join-Path $ProjectRoot "requirements.txt"
if (-not (Test-Path $RequirementsPath)) {
    Write-Host "ERROR: requirements.txt not found at: $RequirementsPath"
    exit 1
}

Write-Host "Installing dependencies into venv..."
Write-Host "  Python: $VenvPython"
Write-Host "  Requirements: $RequirementsPath"
Write-Host ""

& $VenvPython -m pip install -r $RequirementsPath

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pip install failed"
    exit 1
}

Write-Host ""
Write-Host "[OK] Dependencies installed. Run: python -m src.cli ping"
