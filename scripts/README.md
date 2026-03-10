# Automation Scripts

PowerShell scripts for scheduled tasks (weekly, monthly, backup).

## Python Resolution

The scripts search for Python in this order:

1. `../Scripts/python.exe` – venv in parent directory (project inside venv)
2. `venv/Scripts/python.exe` – venv inside project
3. `.venv/Scripts/python.exe` – alternative venv name
4. `python` – fallback to system PATH

The script logs which Python is used. If you see "WARNING: Falling back to PATH", the venv was not found – check that `Scripts/python.exe` exists in the expected location.

**Why this matters:** When you run `python scripts/backup_db.py` manually, you typically have the venv activated. When the script runs from Task Scheduler, there is no activation – the script must find Python explicitly. Using the full path ensures the same Python (and packages) is used in both cases.

## UTF-8 Encoding

`PYTHONIOENCODING=utf-8` is set before invoking Python. This avoids `UnicodeEncodeError` when Python prints emoji (e.g. in backup_db.py) on Windows with cp1250 encoding.

## Stderr Handling

PowerShell with `$ErrorActionPreference = "Stop"` treats stderr from external programs as errors. Python writes tracebacks to stderr, which could cause the script to throw before capturing the full output. The scripts temporarily set `Continue` when invoking Python so all output (including tracebacks) is logged.
