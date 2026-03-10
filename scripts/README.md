# Automation Scripts

PowerShell scripts for scheduled tasks (weekly, monthly, backup).

- **run_weekly.ps1** – health check (ping --check) + refresh-cache (includes 18‑month cleanup before sync) + report-weekly (all users, via Slack). Reports include missing entries reminders.
- **run_monthly.ps1** – health check + sync-users + report-monthly (all, admin) via Slack.
- **run_backup.ps1** – SQLite backup with SQL dump and 90-day retention.

If health check fails (Toggl, Timetastic, Slack, or DB unavailable), the run is skipped and the error is logged.

## setup_venv.ps1

Installs project dependencies using `python -m pip` (avoids broken pip.exe launcher).
Run from project root: `.\scripts\setup_venv.ps1`

## setup_tasks.ps1

Registers Windows Task Scheduler jobs using `Register-ScheduledTask`. Run from project root: `.\scripts\setup_tasks.ps1`

| Task        | Schedule              | Action            |
| ----------- | --------------------- | ----------------- |
| tts_weekly  | Monday 10:00          | run_weekly.ps1    |
| tts_monthly | 1st day of month 10:05| run_monthly.ps1   |
| tts_backup  | Monday 02:00          | run_backup.ps1    |

If a task already exists, it is updated. Verify in Task Scheduler (`taskschd.msc`).

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

## Venv Repair (if pip.exe has wrong path)

If venv was copied or the user path changed, `pip.exe` may have a hardcoded wrong path. The project folders (`timetastic_toggl_sync`, etc.) are **siblings** to `Scripts/` and `Lib/` – they are NOT inside the venv's managed directories.

To repair venv without touching projects:

```powershell
cd C:\Users\hanna.kachurouskaya\Documents\venv
Remove-Item -Recurse -Force Scripts, Lib, pyvenv.cfg
python -m venv .
.\Scripts\python.exe -m pip install -r timetastic_toggl_sync\requirements.txt
```

Only `Scripts`, `Lib`, and `pyvenv.cfg` are removed. Project folders stay.
