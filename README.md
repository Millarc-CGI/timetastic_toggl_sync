# Timetastic-Toggl Sync

A comprehensive integrator for **Toggl Track** (time tracking) + **Timetastic** (absences) with **Slack notifications** and **automated reporting**.

## 🎯 Project Goals

- **Automated daily sync** of time tracking data from Toggl and absences from Timetastic
- **Monthly reports** with overtime calculations and project statistics
- **Slack notifications** for missing time entries and monthly summaries
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
- **Slack Integration**: Automated notifications for missing entries and monthly reports
- **Role-based Messaging**: Different notification types for different user roles
- **Weekly Reminders**: Automated weekly checks for missing time entries

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

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

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

# Check system status
python -m src.cli status
```

#### Reporting
```bash
# Generate all monthly reports (previous month)
python -m src.cli report-monthly

# Generate reports for specific month
python -m src.cli report-monthly --year 2025 --month 10

# Generate admin report only
python -m src.cli report-monthly --role admin

# Generate producer report only
python -m src.cli report-monthly --role producer

# Generate report for specific user
python -m src.cli report-monthly --user user@company.com
```

#### Notifications
```bash
# Check for missing entries and send Slack reminders
python -m src.cli check-missing

# Send weekly notifications (uses configured schedule)
python -m src.cli notify-users

# Test Slack integration
python -m src.cli test-slack
```

#### Data Export
```bash
# Export raw data for a specific month
python -m src.cli export --year 2025 --month 10
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

## 📊 Report Types

### User Reports
- Personal time tracking summary
- Overtime calculations
- Project breakdown
- Absence summary
- Missing entries tracking

### Producer Reports
- Project-focused analytics
- User contributions per project
- Cost estimation (if hourly rates configured)
- Project efficiency metrics

### Admin Reports
- Complete organizational overview
- All user statistics
- Department breakdown
- Financial summaries
- System-wide analytics

## 🔐 Access Control

The system implements role-based access control:

- **Admin**: Full access to all reports and system settings
- **Producer**: Access to project reports and user data for project tracking
- **User**: Access to personal reports only

Reports are stored with role-specific naming:
- `admin_YYYY-MM.csv` - Admin reports
- `producer_YYYY-MM.csv` - Producer reports  
- `user_email_YYYY-MM.csv` - Individual user reports

## 📅 Automation & Scheduling

### Daily Sync
Set up automated daily synchronization using cron (Linux/Mac) or Task Scheduler (Windows):

```bash
# Daily sync at 6 AM
0 6 * * * cd /path/to/project && python -m src.cli sync --start $(date -d yesterday +\%Y-\%m-\%d) --end $(date -d yesterday +\%Y-\%m-\%d)
```

### Weekly Notifications
```bash
# Weekly missing entries check (Fridays at 9 AM)
0 9 * * 5 cd /path/to/project && python -m src.cli notify-users
```

### Monthly Reports
```bash
# Monthly report generation (1st of each month at 8 AM)
0 8 1 * * cd /path/to/project && python -m src.cli report-monthly
```

## 🗄️ Data Storage

### SQLite Database
- **Location**: `./data/sync.db` (configurable)
- **Tables**: users, time_entries, absences, sync_log, monthly_reports
- **Features**: Automatic cleanup of old data, comprehensive indexing

### File Exports
- **Location**: `./exports/YYYY-MM/` (configurable)
- **Formats**: CSV, JSON
- **Organization**: Role-based file naming and directory structure

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
MISSING_ENTRIES_CHECK_DAYS=7
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
   - Test with `test-slack` command

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
