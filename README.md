# Timetastic-Toggl Sync

A comprehensive integrator for **Toggl Track** (time tracking) + **Timetastic** (absences) with **Slack notifications** and **automated reporting**.

## 🎯 Project Goals

- **Automated daily sync** of time tracking data from Toggl and absences from Timetastic
- **Monthly reports** with overtime calculations and project statistics
- **Slack notifications** via weekly and monthly reports (include missing entries)
- **Role-based access control** for different types of reports (Admin/Producer/User)
- **Simple overtime calculation** with standard thresholds
- **Project-focused analytics** for producers and managers

## 🏗️ Architecture

The system is built with a modular architecture:

```
src/
├── config.py              # Configuration management
├── cli.py                 # Command-line interface
├── models/                # Data models
│   ├── user.py            # User mappings across services
│   ├── time_entry.py      # Toggl time entries
│   ├── absence.py         # Timetastic absences
│   └── report.py          # Report data structures
├── services/              # External API integrations
│   ├── toggl_service.py   # Toggl Track API
│   ├── timetastic_service.py # Timetastic API
│   ├── slack_service.py   # Slack notifications
│   └── user_service.py    # User management
├── storage/               # Data persistence
│   ├── sqlite_storage.py  # SQLite database operations
│   └── file_storage.py    # CSV/JSON exports
├── logic/                 # Business logic
│   ├── data_aggregator.py # Data merging and processing
│   ├── overtime_calculator.py # Overtime calculations
│   ├── statistics_generator.py # Analytics generation
│   ├── report_generator.py # Report creation
│   └── date_ranges.py     # Timezone-aware date helpers
├── access_control/        # Role-based permissions
│   └── permissions.py     # Access control logic
```

> Local API smoke tests live under `src/tests/` for developer use only and are not part of the packaged architecture.


## 🚀 Features

### Core Functionality
- **Data Synchronization**: Automatic fetching from Toggl and Timetastic APIs
- **User Mapping**: Intelligent mapping of users across all three services
- **Data Aggregation**: Merging time entries with absences using configurable rules
- **Overtime Calculation**: Simple overtime calculation with configurable thresholds (8h/day, 40h/week, 160h/month)

### Reporting & Analytics
- **Monthly Reports**: Comprehensive reports for users, projects, and administrators
- **Project Analytics**: Detailed project statistics and user contributions
- **Overtime Tracking**: Automated overtime calculations with simple 1.5x multiplier
- **Attendance Analysis**: Missing entries detection and absence tracking

### Notifications & Communication
- **Slack Integration**: Automated notifications via weekly and monthly reports
- **Role-based Messaging**: Different notification types for different user roles
- **Missing Entries**: Included in weekly and monthly reports (no separate reminders)

### Access Control
- **Role-based Reports**: Admin, Producer, and User-specific report access
- **Secure File Access**: Role-based file permissions and access control
- **Audit Logging**: Comprehensive logging of all system operations

## 📋 Requirements

- **Python 3.11+**
- **API Access**:
  - **TOGGL_API_TOKEN** – Generated in Toggl Track (Profile Settings → API Token)
  - **TIMETASTIC_API_TOKEN** – Generated in Timetastic (Settings → Integrations)
  - **SLACK_BOT_TOKEN** – Generated in Slack (App Management → OAuth & Permissions)

## 🔧 Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd timetastic_toggl_sync
   ```

2. **Install dependencies** (use `python -m pip` so packages go into the correct venv):
   ```bash
   python -m pip install -r requirements.txt
   ```
   Or run the setup script: `.\scripts\setup_venv.ps1`

3. **Configure environment**:
   ```bash
   cp env.example .env
   # Edit .env with your API tokens and settings
   ```

4. **Test connections**:
   ```bash
   python -m src.cli ping
   ```

## ⚙️ Configuration

### Environment Variables

Copy `env.example` to `.env` and configure the following:

#### API Configuration
```env
TOGGL_BASE_URL=https://api.track.toggl.com/api/v9
TOGGL_API_TOKEN=your_toggl_api_token
TIMETASTIC_BASE_URL=https://app.timetastic.co.uk/api
TIMETASTIC_API_TOKEN=your_timetastic_api_token
WORKSPACE_ID=optional_workspace_id
```

#### Slack Integration
```env
SLACK_BOT_TOKEN=xoxb-your-slack-bot-token
SLACK_DEFAULT_SENDER_NAME=
SLACK_DM_FALLBACK_CHANNEL=general
SLACK_ORG_EMAIL_DOMAIN=yourcompany.slack.com
```

#### Working Hours & Overtime Rules
```env
DEFAULT_WORKING_HOURS_DAILY=8
# Overtime calculation uses simple 8h/day thresholds
```

#### Access Control
```env
ADMIN_EMAILS=admin@company.com,hr@company.com
PRODUCER_EMAILS=producer1@company.com,producer2@company.com
```

#### Absence Rules
```env
# Absence rules will be implemented in logic/ folder
```

## 🖥️ Usage

### Command Line Interface

The system provides a comprehensive CLI for all operations:

#### Basic Operations
```bash
# Test all connections
python -m src.cli ping

# Sync user mappings between services
python -m src.cli sync-users

# Sync data for a date range
python -m src.cli sync --start 2025-10-01 --end 2025-10-31

# Sync previous month without passing dates (this uses the default previous calendar month)
python -m src.cli sync

# Check system status
python -m src.cli status
```

#### Reporting

**Monthly Reports:**
```bash
# Generate reports for all users (previous month)
python -m src.cli report-monthly --target all

# Generate reports for all users + send via Slack
python -m src.cli report-monthly --target all --send

# Generate admin report only
python -m src.cli report-monthly --target admin

# Generate admin report + send via Slack
python -m src.cli report-monthly --target admin --send

# Generate project statistics (production) + send via Slack
python -m src.cli report-monthly --target production --send

# Generate report for specific user (by email or full name)
python -m src.cli report-monthly --target-user user@company.com
python -m src.cli report-monthly --target-user "John Doe"



**Weekly Reports:**
```bash
# Generate weekly reports for all users (last week, Monday to Sunday)
python -m src.cli report-weekly --target all

# Generate weekly reports for all users + send via Slack
python -m src.cli report-weekly --target all --send

# Generate weekly report for specific week
python -m src.cli report-weekly --week-start 2025-11-25 --target all

# Generate report for specific user
python -m src.cli report-weekly --target-user "John Doe"
```

**Project Statistics:**
```bash
# Generate project-specific statistics (interactive selection)
python -m src.cli report-project-stats

# Generate statistics for specific project(s) + send to producers
python -m src.cli report-project-stats --project-name "Project Name" --target production --send
python -m src.cli report-project-stats --project-name "Project 1" --project-name "Project 2" --target production --send

# Generate statistics with custom date range
python -m src.cli report-project-stats --project-name "Project Name" --start-date 2025-10-01 --end-date 2025-12-31 --target production --send
```

**Additional Commands:**
```bash
# Send admin report to admins via Slack (requires generated admin report)
python -m src.cli send-admin-report
python -m src.cli send-admin-report --select-month 2025-11
```

> **Note:** Cache is automatically refreshed based on TTL (7 days for previous month, 30 days for older months). No manual cache refresh flags are needed.

> **Note:** Missing entries reminders are included in weekly and monthly reports. No separate send-reminders command.

#### Data Export
```bash
# Export raw data for a specific month
python -m src.cli export --select-month 2025-10
```

### Testing API Connections

Test individual service connections:

```bash
# Test Slack
python -m src.tests.slack_test

# Test Toggl
python -m src.tests.toggl_test

# Test Timetastic
python -m src.tests.timetastic_test
```

### Debug Scripts
- `python -m src.tests.report_debug` – fetches data for the configured test user and prints weekly/monthly summaries (plus optional Slack delivery).
- `python -m src.tests.report_debug --bulk` – reruns monthly report generation for all synced users and prints each user's hours, overtime, and missing entries.
- `python -m src.tests.project_stats_debug --select-month 2025-10 --limit 5` – aggregates workspace time entries, runs `StatisticsGenerator.generate_project_stats`, and prints the top projects for the selected month.

## 📊 Report Types

### User Reports
- Personal time tracking summary
- Overtime calculations (daily/weekly/monthly)
- Project breakdown with task details
- Daily overtime breakdown with project and task hours
- Missing entries tracking
- Export to XLSX with formatted tables and wide columns

### Producer Reports
- Project-focused analytics
- User contributions per project
- Cost estimation (if hourly rates configured)
- Project efficiency metrics
- Monthly project statistics with project overtime (`--target production`)
- Project-specific statistics with project overtime (`report-project-stats --target production`)
- Automatic Slack delivery via `--send` flag with `--target production`

### Admin Reports
- Complete organizational overview with all user statistics
- Department breakdown
- Monthly and weekend overtime tracking
- Missing time entries tracking
- Export to XLSX with formatted tables and wide columns
- Slack delivery via `send-admin-report` command
- SQLite storage in `admin_statistics` table
- Main sheet columns: `Total Hours, Monthly Overtime, Weekend Overtime, Working Days, Missing Toggl Entries`; summary shows `Expected Hours (per user)`.
- Per-user sheets added to the same admin workbook with compact table: `Date, Type (weekend/blank), Toggl Hours, Absences, Total Hours, Expected Hours, Overtime, Weekend Overtime, Missing Toggl Entries`.

## 🔐 Access Control

The system implements role-based access control:

- **Admin**: Full access to all reports and system settings
- **Producer**: Access to workspace user data for project tracking and statistics dashboards
- **User**: Access to personal reports only

Reports are stored with role-specific naming:
- `admin_YYYY-MM.xlsx` - Admin reports (XLSX format)
- `project_stats_YYYY-MM.xlsx` - Monthly project statistics (XLSX format)
- `user_email_YYYY-MM.xlsx` - Individual user reports (XLSX format)
- `user_combined_database_YYYY-MM.xlsx` - Single workbook with one sheet per user
- All month-based commands now use `--select-month YYYY-MM` (default: previous month): `report-monthly`, `send-admin-report`, `export`.

## 📅 Automation & Scheduling

### Windows (Task Scheduler + PowerShell)

1. Ensure venv is set up: `.\scripts\setup_venv.ps1`
2. From project root, register tasks: `.\scripts\setup_tasks.ps1`
3. Verify in Task Scheduler (`taskschd.msc`)

| Task        | Schedule               | Action            |
| ----------- | ---------------------- | ----------------- |
| tts_weekly  | Monday 10:00           | refresh-cache + report-weekly |
| tts_monthly | 1st day of month 10:05 | sync-users + report-monthly (all, admin, production) |
| tts_backup  | Monday 02:00           | SQLite backup (90-day retention) |

**Order matters:** In `tts_monthly`, `sync-users` runs first – it updates user mappings (Toggl/Timetastic/Slack) in SQLite. Reports read from this table, so new users only appear after sync-users.

**Health check:** Before reports, `run_weekly.ps1` and `run_monthly.ps1` run `ping --check`. If any service (Toggl, Timetastic, Slack, DB) fails, the run is skipped and the error is logged.

Logs: `logs/run_weekly_YYYY-MM-DD.log`, `logs/run_monthly_YYYY-MM-DD.log`, `logs/run_backup_YYYY-MM-DD.log`

### Linux/Mac (cron)

### Daily Sync
Set up automated daily synchronization using cron (Linux/Mac):

```bash
# Daily sync at 6 AM
0 6 * * * cd /path/to/project && python -m src.cli sync --start $(date -d yesterday +\%Y-\%m-\%d) --end $(date -d yesterday +\%Y-\%m-\%d)
```

### Weekly Reports
```bash
# Weekly report generation (every Monday at 9 AM) - refresh cache + send weekly reports
# Reports include missing entries reminders
0 9 * * 1 cd /path/to/project && python -m src.cli refresh-cache && python -m src.cli report-weekly --target all --send
```

### Monthly Reports
```bash
# IMPORTANT: sync-users first (updates user mappings). Reports read from SQLite users table.
# Monthly (1st of each month at 8 AM) – sequential: sync-users, then all reports
0 8 1 * * cd /path/to/project && python -m src.cli sync-users && \
  python -m src.cli report-monthly --target all --send && \
  python -m src.cli report-monthly --target admin --send && \
  python -m src.cli report-monthly --target production --send

# Generate reports for a specific past month (override default previous month)
python -m src.cli report-monthly --target all --select-month 2024-11
```

## 🗄️ Data Storage

### SQLite Database
- **Location**: `./data/sync.db` (configurable)
- **Tables**: users, time_entries, absences, sync_log, monthly_reports
- **Features**: Automatic cleanup of old data, comprehensive indexing
- **Retention:** `refresh-cache` runs cleanup before sync (default: delete data older than 18 months). Use `refresh-cache --retention-months 0` to disable.

### File Exports
- **Location**: `./exports/YYYY-MM/` (configurable)
- **Formats**: XLSX (formatted reports), JSON (raw data backup)
- **Organization**: Role-based file naming and directory structure
- **Features**: Formatted tables, wide columns, frozen headers, color-coded headers
- Combined user workbook available as `user_combined_database_YYYY-MM.xlsx` (arkusze per user).

### Backup

**Local backup** (current setup): Use `scripts/backup_db.py` directly or `scripts/run_backup.ps1` (PowerShell wrapper with logging). Creates SQLite copy + SHA256 checksum + SQL dump in `./backups/` with 90-day retention. Scheduled via Task Scheduler (`tts_backup`, Monday 02:00).

**GitHub Actions** (`.github/workflows/backup.yml`): Prepared for future use when the project runs on NAS or cloud. Not used with local setup – the workflow has no access to the local SQLite database.

## 🔧 Customization

### Overtime Rules
Simple overtime calculation is implemented:
- Daily: 8 hours threshold


### Absence Rules
Customize how different absence types are handled:

```env
# Absence rules will be implemented in logic/ folder
```

### Notification Settings
```env
SLACK_NOTIFICATION_DAY=Friday
SLACK_NOTIFICATION_TIME=09:00
SEND_MONTHLY_REPORTS=true
EXCLUDED_REPORT_EMAILS=
SEND_ADMIN_NOTIFICATIONS=true
REFRESH_DAY_OF_WEEK=Monday
REFRESH_TIME=03:00
```

## 🚀 Future Plans

### Web Application
When ready for a web interface, the recommended tech stack is:
- **Backend**: FastAPI (Python-based, familiar, auto-docs)
- **Frontend**: React/Vue or Streamlit (simple Python-based UI)
- **Database**: PostgreSQL (for production scalability)
- **Authentication**: OAuth2 with Slack/Google login
- **Deployment**: Docker containers on NAS or cloud

### Enhanced Features
- Real-time dashboards
- Advanced analytics and forecasting
- Integration with payroll systems
- Mobile app for time entry
- Advanced reporting with charts and graphs

## 🐛 Troubleshooting

### Common Issues

1. **API Connection Errors**:
   - Verify API tokens are correct
   - Check network connectivity
   - Ensure API endpoints are accessible

2. **User Mapping Issues**:
   - Run `sync-users` to update mappings
   - Verify email addresses match across services
   - Check user permissions in each service

3. **Slack Notification Failures**:
   - Verify bot token and permissions
   - Check if users are in the workspace
   - Test connections with `ping` command

4. **Report Generation Errors**:
   - Ensure data is synced first
   - Check date ranges and user existence
   - Verify file system permissions

### Logging
The system provides comprehensive logging:
- Database operations
- API calls and responses
- Error tracking and debugging
- Sync history and statistics

## 📄 License

[Add your license information here]

## 🤝 Contributing

[Add contribution guidelines here]

## 📞 Support

For support and questions:
- Check the troubleshooting section
- Review the configuration documentation
- Test individual components using the test scripts
- Check system logs for detailed error information


[![CI Status](https://github.com/Millarc-CGI/timetastic_toggl_sync/actions/workflows/ci.yml/badge.svg)](https://github.com/Millarc-CGI/timetastic_toggl_sync/actions)