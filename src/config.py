"""
Configuration loader for the Timetastic + Toggl integrator.

- Reads environment variables (and .env if present).
- Provides a single Settings object you can import anywhere.
- Keeps Slack and access-control settings alongside API/base settings.
"""

import os
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Set, List, Dict, Any

# Load .env if present
try:
    import importlib
    dotenv = importlib.import_module("dotenv")
    dotenv.load_dotenv()
except Exception:
    pass

# helper functions for parsing CSV strings
def _split_csv(s: str) -> List[str]:
    return [x.strip() for x in s.split(",") if x and x.strip()]

# helper functions for parsing CSV strings to sets
def _split_csv_set(s: str) -> Set[str]:
    return {x.strip().lower() for x in s.split(",") if x and x.strip()}

# helper function for parsing JSON strings
def _parse_json(s: str, default: Any = None) -> Any:
    if not s or not s.strip():
        return default
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return default

# Overtime rules parsing removed - will be implemented in overtime_calculator.py

@dataclass
class Settings:
    # API Configuration
    toggl_base_url: str
    toggl_reports_base_url: str
    toggl_api_token: str
    timetastic_base_url: str
    timetastic_api_token: str
    workspace_id: Optional[str]
    
    # Timezone
    timezone: str
    
    # Working Hours Configuration
    default_daily_hours: float
    default_weekly_hours: float
    default_monthly_hours: float
    
    # Overtime Rules (simplified - will be implemented in overtime_calculator)
    # For now, using simple default daily hours
    
    # Absence rules will be implemented in logic/ folder
    
    # Storage and Exports
    exports_dir: str
    database_path: str
    cache_dir: str
    
    # Slack Configuration
    slack_bot_token: str
    slack_default_sender_name: str
    slack_dm_fallback_channel: str
    slack_org_email_domain: str
    refresh_day_of_week: str
    refresh_time: str
    slack_signing_secret: str
    
    # Access Control
    admin_emails: Set[str]
    producer_emails: Set[str]
    excluded_admin_emails: Set[str]  # Admins excluded from receiving admin reports
    run_token: str
    email_aliases: Dict[str, str]  # Maps alternative emails to canonical email
    
    # Notification Settings
    send_monthly_reports: bool
    send_admin_notifications: bool
    excluded_report_emails: Set[str]
    included_report_emails: Set[str]
    
    # Logging
    log_level: str
    log_file: Optional[str]
    
    # Testing (Optional)
    slack_test_user_id: Optional[str]
    slack_test_email: Optional[str]
    toggl_test_start_date: Optional[str]
    toggl_test_end_date: Optional[str]
    toggl_test_user_id: Optional[str]
    timetastic_test_start_date: Optional[str]
    timetastic_test_end_date: Optional[str]
    timetastic_test_user_id: Optional[str]

    # --- helper methods (optional, convenience) ---
    def is_admin(self, email: str) -> bool:
        return email.strip().lower() in self.admin_emails

    def is_producer(self, email: str) -> bool:
        return email.strip().lower() in self.producer_emails

# Overtime rules will be implemented in logic/overtime_calculator.py
# For now, using simple default daily hours calculation

def load_settings() -> Settings:
    """Read runtime configuration from environment variables / .env."""
    return Settings(
        # API Configuration
        toggl_base_url=os.getenv("TOGGL_BASE_URL", "https://api.track.toggl.com/api/v9"),
        toggl_reports_base_url=os.getenv("TOGGL_REPORTS_BASE_URL", "https://api.track.toggl.com/reports/api/v3"),
        toggl_api_token=os.getenv("TOGGL_API_TOKEN", "").strip(),
        timetastic_base_url=os.getenv("TIMETASTIC_BASE_URL", "https://app.timetastic.co.uk/api"),
        timetastic_api_token=os.getenv("TIMETASTIC_API_TOKEN", "").strip(),
        workspace_id=(os.getenv("WORKSPACE_ID", "").strip() or None),
        
        # Timezone
        timezone=os.getenv("TIMEZONE", "UTC").strip(),
        
        # Working Hours Configuration
        default_daily_hours=float(os.getenv("DEFAULT_WORKING_HOURS_DAILY", os.getenv("DEFAULT_DAILY_HOURS", "8"))),
        default_weekly_hours=float(os.getenv("DEFAULT_WORKING_HOURS_WEEKLY", "40")),
        default_monthly_hours=float(os.getenv("DEFAULT_WORKING_HOURS_MONTHLY", "160")),
        
        # Overtime Rules (simplified for now)
        # Complex overtime logic will be implemented in logic/overtime_calculator.py
        
        # Absence rules will be implemented in logic/ folder
        
        # Storage and Exports
        exports_dir=os.getenv("EXPORTS_DIR", "./exports").strip(),
        database_path=os.getenv("DATABASE_PATH", "./data/sync.db").strip(),
        # Cache directory for API responses (Toggl, Timetastic)
        cache_dir=os.getenv("CACHE_DIR", "./cache").strip(),
        
        # Slack Configuration
        slack_bot_token=os.getenv("SLACK_BOT_TOKEN", "").strip(),
        slack_default_sender_name=os.getenv("SLACK_DEFAULT_SENDER_NAME", "MillarcAI").strip(),
        slack_dm_fallback_channel=os.getenv("SLACK_DM_FALLBACK_CHANNEL", "general").strip(),
        slack_org_email_domain=os.getenv("SLACK_ORG_EMAIL_DOMAIN", "millarcgroup.slack.com").strip(),
        refresh_day_of_week=os.getenv("REFRESH_DAY_OF_WEEK", "Monday").strip(),
        refresh_time=os.getenv("REFRESH_TIME", "08:00").strip(),
        slack_signing_secret=os.getenv("SLACK_SIGNING_SECRET", "").strip(), 
        # Access Control
        admin_emails=_split_csv_set(os.getenv("ADMIN_EMAILS", "")),
        producer_emails=_split_csv_set(os.getenv("PRODUCER_EMAILS", "")),
        excluded_admin_emails=_split_csv_set(os.getenv("EXCLUDED_ADMIN_EMAILS", "")),
        run_token=os.getenv("RUN_TOKEN", "").strip(),
        # Email aliases: maps alternative emails to canonical email (normalized to lowercase)
        email_aliases={k.lower().strip(): v.lower().strip() for k, v in (_parse_json(os.getenv("EMAIL_ALIASES", "{}"), {}) or {}).items()},
        
        # Notification Settings
        send_monthly_reports=os.getenv("SEND_MONTHLY_REPORTS", "true").lower() == "true",
        send_admin_notifications=os.getenv("SEND_ADMIN_NOTIFICATIONS", "true").lower() == "true",
        excluded_report_emails=_split_csv_set(os.getenv("EXCLUDED_REPORT_EMAILS", "")),
        included_report_emails=_split_csv_set(
            os.getenv("INCLUDED_REPORT_EMAILS", os.getenv("INCLUDED_REPORT_EMAIL", ""))
        ),
        
        # Logging
        log_level=os.getenv("LOG_LEVEL", "INFO").strip(),
        log_file=(os.getenv("LOG_FILE", "").strip() or None),
        
        # Testing (Optional)
        slack_test_user_id=(os.getenv("SLACK_TEST_USER_ID", "").strip() or None),
        slack_test_email=(os.getenv("SLACK_TEST_EMAIL", "").strip() or None),
        toggl_test_start_date=(os.getenv("TOGGL_TEST_START_DATE", "").strip() or None),
        toggl_test_end_date=(os.getenv("TOGGL_TEST_END_DATE", "").strip() or None),
        toggl_test_user_id=(os.getenv("TOGGL_TEST_USER_ID", "").strip() or None),
        timetastic_test_start_date=(os.getenv("TIMETASTIC_TEST_START_DATE", "").strip() or None),
        timetastic_test_end_date=(os.getenv("TIMETASTIC_TEST_END_DATE", "").strip() or None),
        timetastic_test_user_id=(os.getenv("TIMETASTIC_TEST_USER_ID", "").strip() or None),
    )
