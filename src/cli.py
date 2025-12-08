"""
CLI for the Timetastic-Toggl sync system using the restructured architecture.
"""

import os
import sys
import click
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any, Literal
from pathlib import Path

from .config import load_settings
from .services import TogglService, TimetasticService, SlackService, UserService
from .storage import SQLiteStorage, FileStorage
from .logic import DataAggregator, OvertimeCalculator, ReportGenerator, StatisticsGenerator
from .access_control import PermissionManager
from .models.user import User
from .models.project import Project


@click.group(help="Timetastic-Toggl Sync CLI - Automated time tracking integration")
def cli():
    """Main CLI group for the Timetastic-Toggl sync system."""
    pass


@cli.command()
def ping():
    """Test configuration and connections to all services."""
    settings = load_settings()
    
    print("🔍 Testing Configuration...")
    print(f"   TOGGL_BASE_URL: {settings.toggl_base_url}")
    print(f"   TIMETASTIC_BASE_URL: {settings.timetastic_base_url}")
    print(f"   EXPORTS_DIR: {settings.exports_dir}")
    print(f"   DATABASE_PATH: {settings.database_path}")
    print(f"   TOGGL_TOKEN set: {'✅' if settings.toggl_api_token else '❌'}")
    print(f"   TIMETASTIC_TOKEN set: {'✅' if settings.timetastic_api_token else '❌'}")
    print(f"   SLACK_TOKEN set: {'✅' if settings.slack_bot_token else '❌'}")
    print()
    
    # Test service connections
    print("🔗 Testing Service Connections...")
    
    # Test Toggl
    try:
        toggl_service = TogglService(settings)
        if toggl_service.test_connection():
            user_info = toggl_service.get_user_info()
            print(f"   ✅ Toggl: Connected as {user_info.get('fullname', 'Unknown')}")
        else:
            print("   ❌ Toggl: Connection failed")
    except Exception as e:
        print(f"   ❌ Toggl: Error - {e}")
    
    # Test Timetastic
    try:
        timetastic_service = TimetasticService(settings)
        if timetastic_service.test_connection():
            print("   ✅ Timetastic: Connection successful")
        else:
            print("   ❌ Timetastic: Connection failed")
    except Exception as e:
        print(f"   ❌ Timetastic: Error - {e}")
    
    # Test Slack
    try:
        slack_service = SlackService(settings)
        if slack_service.test_connection():
            print("   ✅ Slack: Connection successful")
        else:
            print("   ❌ Slack: Connection failed")
    except Exception as e:
        print(f"   ❌ Slack: Error - {e}")
    
    # Test storage
    try:
        storage = SQLiteStorage(settings)
        stats = storage.get_database_stats()
        print(f"   ✅ Database: {stats.get('users', 0)} users, {stats.get('time_entries', 0)} entries")
    except Exception as e:
        print(f"   ❌ Database: Error - {e}")


def _sync_range(settings, start_date: date, end_date: date, sync_type: str = "manual_sync"):
    """Internal helper to sync a given date range."""
    print(f"🔄 Starting sync for {start_date} to {end_date} (type: {sync_type})...")
    storage = SQLiteStorage(settings)
    toggl_service = TogglService(settings, storage=storage)
    timetastic_service = TimetasticService(settings, storage=storage)

    log_id = storage.log_sync_start(sync_type)
    try:
        start_iso = f"{start_date}T00:00:00Z"
        end_iso = f"{end_date}T23:59:59Z"

        print("📊 Fetching time entries from Toggl...")
        time_entries = toggl_service.get_time_entries(start_iso, end_iso, force_refresh=True)
        print(f"   ✅ Found {len(time_entries)} time entries")

        print("🏖️ Fetching absences from Timetastic...")
        absences = timetastic_service.get_holidays(start_iso, end_iso, force_refresh=True)
        # Removed duplicate absences log

        print("💾 Saving data to database...")
        print(f"   [DEBUG _sync_range] Saving {len(time_entries)} time entries and {len(absences)} absences")
        storage.save_time_entries(time_entries)
        storage.save_absences(absences)
        print(f"   [DEBUG _sync_range] Data saved to SQLite")

        storage.log_sync_end(log_id, "success", len(time_entries) + len(absences))
        print("✅ Sync completed successfully!")
    except Exception as e:
        storage.log_sync_end(log_id, "error", 0, [str(e)])
        print(f"❌ Sync failed: {e}")
        raise




def _sync_users_and_cache(settings):
    """Refresh user mappings from services and persist them for reporting."""
    user_service = UserService(settings)
    storage = SQLiteStorage(settings)

    print("🔄 Refreshing user mappings before reporting...")
    users = user_service.sync_users_from_services()
    saved = 0
    for user in users:
        if storage.save_user(user):
            saved += 1

    # Removed debug logs - stats calculation kept for potential future use
    stats = user_service.get_user_statistics(users)
    return users


def _find_user_by_email_or_name(users: List[User], search_term: str) -> Optional[User]:
    """Find user by email or by full name (case-insensitive)."""
    search_lower = search_term.lower().strip()
    
    # First try exact email match
    for user in users:
        if user.email.lower() == search_lower:
            return user
    
    # Then try name match (normalized comparison)
    search_normalized = " ".join(search_lower.split())
    for user in users:
        if user.full_name:
            user_name_normalized = " ".join(user.full_name.lower().strip().split())
            if user_name_normalized == search_normalized:
                return user
    
    return None


def _build_slack_email_map(slack_service: SlackService) -> dict:
    """Fetch Slack users once and build email->id map to avoid per-user lookups."""
    try:
        members = slack_service.get_users()
    except Exception as exc:
        print(f"⚠️ Slack lookup failed (users_list): {exc}")
        return {}

    mapping = {}
    skipped_deleted = 0
    skipped_bots = 0
    for member in members:
        if member.get("deleted"):
            skipped_deleted += 1
            continue
        if member.get("is_bot"):
            skipped_bots += 1
            continue
        profile = member.get("profile", {}) or {}
        email = (profile.get("email") or "").strip().lower()
        if not email:
            continue
        mapping[email] = member.get("id")

    # Removed debug logs
    return mapping


# === DATE RANGE HELPERS ===

def _get_previous_month() -> tuple[int, int, date, date]:
    """Return (year, month, start_date, end_date) for previous calendar month."""
    today = date.today()
    first_this = today.replace(day=1)
    last_prev = first_this - timedelta(days=1)
    start_date = last_prev.replace(day=1)
    return last_prev.year, last_prev.month, start_date, last_prev


def _get_month_range(year: int, month: int) -> tuple[date, date]:
    """Return (start_date, end_date) for given year/month."""
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)
    return start_date, end_date


def _resolve_month_params(year: Optional[int], month: Optional[int]) -> tuple[int, int, date, date]:
    """
    Resolve year/month parameters. Defaults to previous month if not provided.
    Returns (year, month, start_date, end_date).
    """
    if year and month:
        start_date, end_date = _get_month_range(year, month)
        return year, month, start_date, end_date
    return _get_previous_month()


def _get_last_week_range() -> tuple[date, date]:
    """Return (week_start, week_end) for last full week (Monday-Sunday)."""
    today = date.today()
    days_since_monday = today.weekday()
    week_start = today - timedelta(days=days_since_monday + 7)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


# === USER FILTERING HELPERS ===

def _get_eligible_users(users: List[User], settings) -> List[User]:
    """
    Get users eligible for reports:
    - Active Toggl users OR admins OR producers
    - Excluding users in EXCLUDED_REPORT_EMAILS
    """
    excluded = settings.excluded_report_emails
    return [
        u for u in users
        if (u.toggl_user_id or settings.is_admin(u.email) or settings.is_producer(u.email))
        and (not u.email or u.email.lower() not in excluded)
    ]


def _get_toggl_users_only(users: List[User], settings) -> List[User]:
    """Get only active Toggl users (for sending user reports via Slack)."""
    excluded = settings.excluded_report_emails
    return [
        u for u in users
        if u.toggl_user_id and u.email and u.email.lower() not in excluded
    ]


def _generate_user_report(
    user: User,
    start_date: date,
    end_date: date,
    report_type: Literal['monthly', 'weekly'],
    aggregator: DataAggregator,
    overtime_calc: OvertimeCalculator,
    report_gen: ReportGenerator,
    toggl_service: TogglService,
    timetastic_service: TimetasticService,
    force_refresh: bool = False,
    # Monthly-specific parameters
    storage: Optional[SQLiteStorage] = None,
    year: Optional[int] = None,
    month: Optional[int] = None,
    # Weekly-specific parameters
    week_start: Optional[date] = None,
    week_end: Optional[date] = None,
) -> tuple:
    """
    Unified function to generate monthly or weekly user reports.
    
    Args:
        report_type: 'monthly' or 'weekly'
        storage: Required for monthly reports
        year, month: Required for monthly reports
        week_start, week_end: Required for weekly reports (can be derived from start_date/end_date)
    """
    # === COMMON PART: Data fetching ===
    start_iso = f"{start_date}T00:00:00Z"
    end_iso = f"{end_date}T23:59:59Z"
    
    # Fetch time entries from Toggl
    user_ids = [user.toggl_user_id] if user.toggl_user_id else None
    all_time_entries = toggl_service.get_time_entries(
        start_iso, end_iso, user_ids=user_ids, force_refresh=force_refresh
    )
    
    # Filter by user_id
    if user.toggl_user_id:
        time_entries = [te for te in all_time_entries if te.user_id == user.toggl_user_id]
    else:
        time_entries = all_time_entries
    
    # Fetch absences from Timetastic
    timetastic_user_id = user.timetastic_user_id if user.timetastic_user_id else None
    user_ids_for_absences = [timetastic_user_id] if timetastic_user_id else None
    absences = timetastic_service.get_holidays(
        start_iso, end_iso, user_ids=user_ids_for_absences, force_refresh=force_refresh
    )
    
    # === DIFFERENCES: Data aggregation ===
    if report_type == 'monthly':
        if year is None or month is None:
            raise ValueError("year and month are required for monthly reports")
        
        user_data = aggregator.aggregate_monthly(user.email, year, month, time_entries, absences)
        daily_data = user_data.get("daily_data", [])
        
        # Calculate overtime for monthly report
        overtime_data = overtime_calc.calculate_user_overtime(
            user.email, year, month, daily_data
        )
        
        # Save to SQLite (only for monthly reports)
        if storage:
            saved = storage.save_user_monthly_processed_data(
                user.email, year, month, user_data, overtime_data
            )
            if not saved:
                print(f"   [DEBUG SQLite] Failed to save processed data to SQLite for {user.email} ({year}-{month:02d})")
        
        # Generate monthly report
        report = report_gen.generate_monthly_user_report(
            user_email=user.email,
            user_name=user.display_name,
            year=year,
            month=month,
            user_data=user_data,
            overtime_data=overtime_data,
            department=user.department,
        )
        
        print(f"   [DEBUG] Generating monthly report for {user.email} ({year}-{month:02d})")
        
    else:  # report_type == 'weekly'
        # Use week_start/week_end if provided, otherwise use start_date/end_date
        actual_week_start = week_start if week_start else start_date
        actual_week_end = week_end if week_end else end_date
        
        user_data = aggregator.aggregate_weekly(
            user.email, actual_week_start, actual_week_end, time_entries, absences
        )
        daily_data = user_data.get("daily_data", [])
        
        # Calculate overtime for weekly report
        daily_hours = [day['total_hours'] for day in daily_data]
        weekly_overtime = overtime_calc.calculate_weekly_overtime(
            user.email, actual_week_start, daily_hours
        )
        
        # Calculate weekend overtime
        weekend_overtime = sum(
            day.get('time_entry_hours', 0.0) 
            for day in daily_data 
            if day.get('is_weekend', False)
        )
        
        # Prepare overtime_data in format similar to monthly
        overtime_data = {
            'weekly_overtime': weekly_overtime,
            'monthly_overtime': 0.0,
            'weekend_overtime': weekend_overtime,
        }
        
        # Generate weekly report
        report = report_gen.generate_weekly_user_report(
            user_email=user.email,
            user_name=user.display_name or user.email,
            week_start=actual_week_start,
            week_end=actual_week_end,
            user_data=user_data,
            overtime_data=overtime_data,
            department=user.department
        )
    
    return user_data, overtime_data, report


def _generate_user_monthly_report(
    user,
    start_date: date,
    end_date: date,
    aggregator: DataAggregator,
    overtime_calc: OvertimeCalculator,
    report_gen: ReportGenerator,
    toggl_service: TogglService,
    timetastic_service: TimetasticService,
    storage: SQLiteStorage,
    year: int,
    month: int,
    force_refresh: bool = False,
):
    """Wrapper for monthly reports - calls unified _generate_user_report."""
    return _generate_user_report(
        user=user,
        start_date=start_date,
        end_date=end_date,
        report_type='monthly',
        aggregator=aggregator,
        overtime_calc=overtime_calc,
        report_gen=report_gen,
        toggl_service=toggl_service,
        timetastic_service=timetastic_service,
        force_refresh=force_refresh,
        storage=storage,
        year=year,
        month=month,
    )

@cli.command()
@click.option("--start", help="Start date (YYYY-MM-DD)")
@click.option("--end", help="End date (YYYY-MM-DD)")
def sync(start: Optional[str], end: Optional[str]):
    """Sync data from Toggl and Timetastic for the specified date range."""
    settings = load_settings()
    
    if start and end:
        try:
            start_date = datetime.strptime(start, "%Y-%m-%d").date()
            end_date = datetime.strptime(end, "%Y-%m-%d").date()
        except ValueError:
            print("❌ Invalid date format. Use YYYY-MM-DD")
            return
    elif start or end:
        print("❌ Provide both --start and --end or omit them to use the previous month")
        return
    else:
        today = date.today()
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        start_date = last_prev.replace(day=1)
        end_date = last_prev
    
    _sync_range(settings, start_date, end_date, "manual_sync")


@cli.command()
def refresh_cache():
    """Weekly refresh of previous month's data from Toggl (scheduled for Monday 8:00)."""
    settings = load_settings()
    
    print("🔄 Starting weekly cache refresh for previous month...")
    
    try:
        # Calculate previous month
        today = date.today()
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        start_date = last_prev.replace(day=1)
        end_date = last_prev
        
        print(f"   📅 Refreshing data for {start_date} to {end_date}")
        
        # Sync the range (this will update cache metadata)
        _sync_range(settings, start_date, end_date, "weekly_refresh")
        
        print("✅ Weekly cache refresh completed!")
        
    except Exception as e:
        print(f"❌ Weekly cache refresh failed: {e}")
        raise


@cli.command()
def sync_users():
    """Synchronize user mappings between all services."""
    settings = load_settings()
    
    print("👥 Synchronizing user mappings...")
    
    try:
        user_service = UserService(settings)
        storage = SQLiteStorage(settings)
        
        # Sync users from services
        users = user_service.sync_users_from_services()
        
        # Save users to storage
        for user in users:
            storage.save_user(user)
        
        print(f"✅ Synchronized {len(users)} users")
        
        # Show statistics
        stats = user_service.get_user_statistics(users)
        print(f"   📊 Total users: {stats['total_users']}")
        print(f"   🔗 Mapped users: {stats['mapped_users']} ({stats['mapping_percentage']:.1f}%)")
        print(f"   👑 Admin users: {stats['admin_users']}")
        print(f"   🎬 Producer users: {stats['producer_users']}")
        print(f"   👤 Regular users: {stats['regular_users']}")
        
        # Show mapping details
        print("\n🔍 Service mappings:")
        print(f"   📊 Toggl: {stats['toggl_mapped']} users")
        print(f"   🏖️ Timetastic: {stats['timetastic_mapped']} users")
        print(f"   💬 Slack: {stats['slack_mapped']} users")

        print("\n🧾 Detailed user list (by Toggl):")
        # Filter: show only active Toggl users + admins + producers, excluding excluded users
        excluded_emails = settings.excluded_report_emails
        filtered_users = [
            user for user in users
            if (user.toggl_user_id  # Active Toggl user
                or (user.email and settings.is_admin(user.email))  # Admin
                or (user.email and settings.is_producer(user.email)))  # Producer
            and (not user.email or user.email.lower() not in excluded_emails)  # Not excluded
        ]
        for idx, user in enumerate(filtered_users, start=1):
            excluded = ""
            if user.email and user.email.lower() in settings.excluded_report_emails:
                excluded = " [EXCLUDED]"
            
            role_tags = []
            if user.email and settings.is_admin(user.email):
                role_tags.append("[ADMIN]")
            if user.email and settings.is_producer(user.email):
                role_tags.append("[PRODUCER]")
            role_str = " " + " ".join(role_tags) if role_tags else ""
            
            print(
                f"   {idx}. {user.display_name} <{user.email}>{role_str}{excluded}"
            )
        
    except Exception as e:
        print(f"❌ User sync failed: {e}")
        raise


@cli.command()
@click.option("--year", type=int, help="Year (defaults to previous month)")
@click.option("--month", type=int, help="Month 1-12 (defaults to previous month)")
@click.option("--target-user", help="Generate report for specific user (email or full name)")
@click.option("--target", type=click.Choice(['all', 'admin', 'production']), default='all',
              help="Target: all (user reports), admin (admin summary), production (project stats)")
@click.option("--send", is_flag=True, default=False, help="Send reports via Slack after generation")
def report_monthly(year: Optional[int], month: Optional[int], target_user: Optional[str], target: str, send: bool):
    """Generate monthly reports."""
    settings = load_settings()

    # Resolve month parameters using helper
    year, month, start_date, end_date = _resolve_month_params(year, month)

    print(f"📊 Generating monthly reports for {year}-{month:02d}...")

    try:
        # Initialize services
        storage = SQLiteStorage(settings)  # Still used for user management
        toggl_service = TogglService(settings, storage=storage)  # Create for API tracking and cache
        timetastic_service = TimetasticService(settings, storage=storage)  # Create for API tracking and cache
        
        file_storage = FileStorage(settings)
        aggregator = DataAggregator(settings)
        overtime_calc = OvertimeCalculator(settings)
        report_gen = ReportGenerator(settings)
        stats_gen = StatisticsGenerator(settings)

        users = storage.get_all_users()
        if not users:
            print("❌ No users found. Run 'sync-users' first.")
            return

        # Check Slack settings if sending
        if send and not settings.send_monthly_reports:
            print("⚠️ SEND_MONTHLY_REPORTS disabled; enable it to deliver Slack summaries.")
            send = False

        slack_service: Optional[SlackService] = SlackService(settings) if settings.send_monthly_reports else None
        slack_email_map: dict = {}
        if slack_service and send and target == 'all':
            slack_email_map = _build_slack_email_map(slack_service)

        # Handle specific user
        if target_user:
            user_obj = _find_user_by_email_or_name(users, target_user)
            if user_obj:
                monthly_data, overtime_data, user_report = _generate_user_monthly_report(
                    user_obj, start_date, end_date, aggregator, overtime_calc, report_gen, toggl_service, timetastic_service, storage, year, month
                )
                xlsx_file = file_storage.export_user_report_xlsx(user_report)
                print(f"📄 User report exported to: {xlsx_file}")
                if send and slack_service:
                    slack_user_id = user_obj.slack_user_id or slack_email_map.get(user_obj.email.lower())
                    if slack_user_id:
                        success = slack_service.send_dm(slack_user_id, report_gen.format_user_report_summary(user_report))
                        if success:
                            print(f"📤 Monthly report sent to {user_obj.display_name}")
                        else:
                            print(f"⚠️ Failed to send monthly report to {user_obj.display_name}")
                    else:
                        print(f"⚠️ Slack user not found for {user_obj.email}")
            else:
                print(f"⚠️ User {target_user} not found or has no data for this period")
            return

        # Handle target groups
        if target == 'all':
            # Generate reports for all eligible Toggl users
            eligible_users = _get_toggl_users_only(users, settings)
            if not eligible_users:
                print("⚠️ No eligible Toggl users found.")
                return

            if send:
                print(f"📤 Sending Slack reports for {len(eligible_users)} Toggl users")
                print("📋 Recipients:")
                for idx, user_obj in enumerate(eligible_users, start=1):
                    slack_info = f", slack_id={user_obj.slack_user_id}" if user_obj.slack_user_id else ""
                    timetastic_info = f", timetastic_id={user_obj.timetastic_user_id}" if user_obj.timetastic_user_id else ""
                    print(f"   {idx}. {user_obj.display_name} <{user_obj.email}> (toggl_id={user_obj.toggl_user_id}{timetastic_info}{slack_info})")

            failures = 0
            successes = 0
            for user_obj in eligible_users:
                user_label = user_obj.display_name or user_obj.email
                try:
                    monthly_data, overtime_data, user_report = _generate_user_monthly_report(
                        user_obj, start_date, end_date, aggregator, overtime_calc, report_gen, toggl_service, timetastic_service, storage, year, month
                    )
                    xlsx_file = file_storage.export_user_report_xlsx(user_report)
                    print(f"   📄 User report for {user_label}: {xlsx_file}")
                except Exception as exc:
                    failures += 1
                    print(f"   ❌ Failed to build report for {user_label}: {exc}")
                    continue

                if send and slack_service:
                    slack_user_id = user_obj.slack_user_id or slack_email_map.get(user_obj.email.lower())
                    if not slack_user_id:
                        failures += 1
                        print(f"   ⚠️ Slack user not found for {user_obj.email}; skipped sending.")
                        continue
                    try:
                        success = slack_service.send_dm(slack_user_id, report_gen.format_user_report_summary(user_report))
                    except Exception as exc:
                        success = False
                        print(f"   ❌ Slack send exception for {user_label}: {exc}")
                    if success:
                        successes += 1
                    else:
                        failures += 1
                    status = "sent" if success else "failed"
                    print(f"   📤 Slack report {status} for {user_label}")

            if send:
                print(f"✅ Bulk Slack reporting finished: {successes} sent, {failures} failed")
            else:
                print(f"✅ Generated reports for {len(eligible_users)} users")

        elif target == 'admin':
            # Generate admin summary report
            filtered_users_for_admin = _get_eligible_users(users, settings)

            all_user_data = {}
            all_overtime_data = {}
            for user in filtered_users_for_admin:
                monthly_data, overtime_data, _ = _generate_user_monthly_report(
                    user, start_date, end_date, aggregator, overtime_calc, report_gen, toggl_service, timetastic_service, storage, year, month
                )
                all_user_data[user.email.lower()] = monthly_data
                all_overtime_data[user.email.lower()] = overtime_data

            admin_reports = report_gen.generate_admin_report(filtered_users_for_admin, all_user_data, all_overtime_data, year, month)

            # Save admin statistics to SQLite
            for user in filtered_users_for_admin:
                user_email = user.email.lower()
                if user_email in all_user_data and user_email in all_overtime_data:
                    monthly_data = all_user_data[user_email]
                    overtime_data = all_overtime_data[user_email]
                    missing_count = len(monthly_data.get('missing_days', []))
                    storage.save_admin_statistics(
                        user_email=user.email,
                        user_name=user.display_name or user.email,
                        department=user.department,
                        year=year,
                        month=month,
                        total_hours=monthly_data.get('total_hours', 0.0),
                        expected_hours=overtime_data.get('monthly_expected_hours', 0.0),
                        monthly_overall_overtime=overtime_data.get('monthly_overtime', 0.0),
                        weekend_overtime=overtime_data.get('weekend_overtime', 0.0),
                        missing_entries_count=missing_count
                    )

            xlsx_file = file_storage.export_admin_report_xlsx(admin_reports, year, month)
            print(f"📄 Admin report exported to: {xlsx_file}")

            if send and slack_service:
                _send_admin_report_via_slack(settings, slack_service, xlsx_file, year, month)

        elif target == 'production':
            # Generate project statistics
            filtered_users_for_production = _get_eligible_users(users, settings)

            all_user_data = {}
            all_overtime_data = {}
            for user in filtered_users_for_production:
                monthly_data, overtime_data, _ = _generate_user_monthly_report(
                    user, start_date, end_date, aggregator, overtime_calc, report_gen, toggl_service, timetastic_service, storage, year, month
                )
                all_user_data[user.email.lower()] = monthly_data
                all_overtime_data[user.email.lower()] = overtime_data

            print("📊 Generating monthly project statistics...")
            monthly_project_stats = stats_gen.generate_user_project_task_stats(
                all_user_data,
                filtered_users_for_production,
                all_overtime_data
            )

            if monthly_project_stats:
                project_stats_file = file_storage.export_monthly_project_stats_xlsx(
                    monthly_project_stats, year, month
                )
                print(f"📄 Monthly project statistics: {project_stats_file}")

                if send:
                    _send_project_stats_to_producers(settings, project_stats_file, year, month)
            else:
                print("⚠️ No project statistics data found")

    except Exception as e:
        print(f"❌ Report generation failed: {e}")
        raise


def _generate_user_weekly_report(
    user: User,
    week_start: date,
    week_end: date,
    aggregator: DataAggregator,
    overtime_calc: OvertimeCalculator,
    report_gen: ReportGenerator,
    toggl_service: TogglService,
    timetastic_service: TimetasticService,
    force_refresh: bool = False
) -> tuple:
    """Wrapper for weekly reports - calls unified _generate_user_report."""
    return _generate_user_report(
        user=user,
        start_date=week_start,
        end_date=week_end,
        report_type='weekly',
        aggregator=aggregator,
        overtime_calc=overtime_calc,
        report_gen=report_gen,
        toggl_service=toggl_service,
        timetastic_service=timetastic_service,
        force_refresh=force_refresh,
        week_start=week_start,
        week_end=week_end,
    )


@cli.command()
@click.option("--week-start", help="Week start date (YYYY-MM-DD, defaults to last Monday)")
@click.option("--target-user", help="Generate report for specific user (email or full name)")
@click.option("--target", type=click.Choice(['all']), default='all',
              help="Target: all (user reports)")
@click.option("--send", is_flag=True, default=False, help="Send reports via Slack after generation")
def report_weekly(week_start: Optional[str], target_user: Optional[str], target: str, send: bool):
    """Generate weekly reports (Monday to Sunday)."""
    settings = load_settings()
    
    # Calculate week range
    if week_start:
        try:
            week_start_date = datetime.strptime(week_start, "%Y-%m-%d").date()
        except ValueError:
            print(f"❌ Invalid date format: {week_start}. Use YYYY-MM-DD")
            return
    else:
        week_start_date, week_end_date = _get_last_week_range()
        print(f"📊 Generating weekly reports for {week_start_date} to {week_end_date}")
    
    week_end_date = week_start_date + timedelta(days=6)  # Sunday
    
    # Initialize services
    storage = SQLiteStorage(settings)
    toggl_service = TogglService(settings, storage)
    timetastic_service = TimetasticService(settings, storage)
    
    aggregator = DataAggregator(settings)
    overtime_calc = OvertimeCalculator(settings)
    report_gen = ReportGenerator(settings)
    
    # Get users
    users = storage.get_all_users()
    if not users:
        print("❌ No users found. Run 'sync-users' first.")
        return
    
    # Check Slack settings if sending
    if send and not settings.send_monthly_reports:
        print("⚠️ SEND_MONTHLY_REPORTS disabled; enable it to deliver Slack summaries.")
        send = False
    
    slack_service: Optional[SlackService] = SlackService(settings) if settings.send_monthly_reports else None
    slack_email_map: dict = {}
    if slack_service and send and target == 'all':
        slack_email_map = _build_slack_email_map(slack_service)
    
    # Filter users: only active Toggl users, excluding excluded users
    filtered_users = _get_toggl_users_only(users, settings)
    
    try:
        if target_user:
            # Generate report for specific user
            user_obj = _find_user_by_email_or_name(filtered_users, target_user)
            if user_obj:
                weekly_data, overtime_data, weekly_report = _generate_user_weekly_report(
                    user_obj, week_start_date, week_end_date, aggregator, overtime_calc, report_gen,
                    toggl_service, timetastic_service
                )
                print(f"✅ Weekly report generated for {user_obj.display_name}")
                if send and slack_service:
                    slack_user_id = user_obj.slack_user_id or slack_email_map.get(user_obj.email.lower())
                    if slack_user_id:
                        success = slack_service.send_dm(slack_user_id, report_gen.format_user_report_summary(weekly_report))
                        if success:
                            print(f"📤 Weekly report sent to {user_obj.display_name}")
                        else:
                            print(f"⚠️ Failed to send weekly report to {user_obj.display_name}")
                    else:
                        print(f"⚠️ Slack user not found for {user_obj.email}")
            else:
                print(f"❌ User {target_user} not found or has no data for this week")
        
        elif target == 'all':
            # Generate reports for all eligible users
            if send:
                print(f"📤 Generating weekly reports for {len(filtered_users)} users")
            else:
                print(f"📊 Generating weekly reports for {len(filtered_users)} users...")
            
            failures = 0
            successes = 0
            
            for user_obj in filtered_users:
                user_label = user_obj.display_name or user_obj.email
                try:
                    weekly_data, overtime_data, weekly_report = _generate_user_weekly_report(
                        user_obj, week_start_date, week_end_date, aggregator, overtime_calc, report_gen,
                        toggl_service, timetastic_service
                    )
                    
                    if send and slack_service:
                        slack_user_id = user_obj.slack_user_id or slack_email_map.get(user_obj.email.lower())
                        if not slack_user_id:
                            failures += 1
                            print(f"   ⚠️ Slack user not found for {user_obj.email}; skipped sending.")
                            continue
                        try:
                            success = slack_service.send_dm(slack_user_id, report_gen.format_user_report_summary(weekly_report))
                        except Exception as exc:
                            success = False
                            print(f"   ⚠️ Slack send exception for {user_label}: {exc}")
                        status = "sent" if success else "failed"
                        if success:
                            successes += 1
                        else:
                            failures += 1
                        print(f"   📤 Slack report {status} for {user_label}")
                    else:
                        print(f"   ✅ Weekly report generated for {user_label}")
                        
                except Exception as exc:
                    failures += 1
                    print(f"   ❌ Failed to build report for {user_label}: {exc}")
                    continue
            
            if send:
                print(f"✅ Bulk weekly reporting finished: {successes} sent, {failures} failed")
            else:
                print(f"✅ Generated weekly reports for {week_start_date} to {week_end_date}")
    
    except Exception as e:
        print(f"❌ Weekly report generation failed: {e}")
        raise


@cli.command()
@click.option("--year", type=int, help="Year")
@click.option("--month", type=int, help="Month")
def export(year: Optional[int], month: Optional[int]):
    """Export data to various formats."""
    settings = load_settings()
    
    if not year or not month:
        # Default to previous month
        today = date.today()
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        year, month = last_prev.year, last_prev.month
    
    print(f"📁 Exporting data for {year}-{month:02d}...")
    
    try:
        storage = SQLiteStorage(settings)
        file_storage = FileStorage(settings)
        
        # Get date range
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)
        
        # Get data
        time_entries = storage.get_time_entries_for_period(start_date, end_date)
        absences = []
        users = storage.get_all_users()
        
        for user in users:
            user_absences = storage.get_absences_for_user(user.email, start_date, end_date)
            absences.extend(user_absences)
        
        # Export raw data
        raw_file = file_storage.export_raw_data(time_entries, absences, year, month)
        print(f"✅ Raw data exported to: {raw_file}")
        
        # List available reports
        available_reports = file_storage.list_available_reports(year, month)
        print(f"📊 Available reports for {year}-{month:02d}:")
        for report_type, files in available_reports.items():
            if files:
                print(f"   {report_type}: {len(files)} files")
                for file_path in files[:3]:  # Show first 3 files
                    print(f"     • {file_path.name}")
                if len(files) > 3:
                    print(f"     • ... and {len(files) - 3} more")
        
    except Exception as e:
        print(f"❌ Export failed: {e}")
        raise


@cli.command()
def status():
    """Show system status and statistics."""
    settings = load_settings()
    
    print("📊 System Status")
    print("=" * 50)
    
    try:
        storage = SQLiteStorage(settings)
        stats = storage.get_database_stats()
        
        print(f"🗄️ Database: {settings.database_path}")
        print(f"   Users: {stats.get('users', 0)}")
        print(f"   Time Entries: {stats.get('time_entries', 0)}")
        print(f"   Absences: {stats.get('absences', 0)}")
        print(f"   Reports: {stats.get('monthly_reports', 0)}")
        print(f"   Sync Logs: {stats.get('sync_logs', 0)}")
        print(f"   Size: {stats.get('db_size_mb', 0):.1f} MB")
        print()
        
        # Recent sync history
        sync_history = storage.get_sync_history(5)
        if sync_history:
            print("🔄 Recent Sync History:")
            for sync in sync_history:
                status_icon = "✅" if sync['status'] == 'success' else "❌"
                print(f"   {status_icon} {sync['sync_type']} - {sync['start_time']} ({sync['status']})")
                if sync['entries_processed']:
                    print(f"      Processed: {sync['entries_processed']} entries")
            print()
        
        # Available exports
        file_storage = FileStorage(settings)
        today = date.today()
        current_month = today.replace(day=1)
        
        print("📁 Available Exports:")
        for i in range(3):  # Show last 3 months
            check_date = current_month - timedelta(days=30 * i)
            reports = file_storage.list_available_reports(check_date.year, check_date.month)
            
            total_files = sum(len(files) for files in reports.values())
            if total_files > 0:
                print(f"   {check_date.year}-{check_date.month:02d}: {total_files} files")
        
    except Exception as e:
        print(f"❌ Status check failed: {e}")


@cli.command()
@click.option("--days", default=7, help="Number of days to check back (default: 7)")
def send_reminders(days: int):
    """Check for missing time entries and send Slack reminders to active Toggl users."""
    settings = load_settings()
    
    if not settings.send_missing_entries_notifications:
        print("ℹ️ Missing entries notifications are disabled in configuration")
        return
    
    print(f"🔍 Checking for missing entries in the last {days} days...")
    
    try:
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        
        # Initialize services
        slack_service = SlackService(settings)
        storage = SQLiteStorage(settings)
        aggregator = DataAggregator(settings)
        toggl_service = TogglService(settings, storage=storage)
        timetastic_service = TimetasticService(settings, storage=storage)
        
        # Get users - only active Toggl users, excluding excluded users
        all_users = storage.get_all_users()
        if not all_users:
            print("❌ No users found. Run 'sync-users' first.")
            return
        
        # Filter: only active Toggl users, excluding excluded users
        users = _get_toggl_users_only(all_users, settings)
        
        if not users:
            print("⚠️ No eligible Toggl users found.")
            return
        
        print(f"📋 Checking {len(users)} active Toggl users...")
        
        # Get time entries and absences for the period (fresh data from API)
        start_iso = f"{start_date}T00:00:00Z"
        end_iso = f"{end_date}T23:59:59Z"
        
        print("📊 Fetching time entries from Toggl...")
        all_time_entries = toggl_service.get_time_entries(start_iso, end_iso)
        print(f"   ✅ Found {len(all_time_entries)} time entries")
        
        print("🏖️ Fetching absences from Timetastic...")
        all_absences = timetastic_service.get_holidays(start_iso, end_iso)
        print(f"   ✅ Found {len(all_absences)} absences")
        
        # Detect missing entries
        print("🔍 Detecting missing entries...")
        missing_by_user = aggregator.detect_missing_entries(users, all_time_entries, all_absences, start_date, end_date)
        
        # Count users with missing entries
        users_with_missing = sum(1 for missing_days in missing_by_user.values() if missing_days)
        print(f"   Found {users_with_missing} user(s) with missing entries")
        
        # Send notifications only to users with missing entries
        notifications_sent = 0
        notifications_failed = 0
        
        print("📤 Sending reminders...")
        for user in users:
            user_email = user.email.lower()
            missing_days = missing_by_user.get(user_email, [])
            
            if missing_days:
                if user.slack_user_id:
                    success = slack_service.send_missing_entries_reminder(user_email, missing_days, days)
                    if success:
                        notifications_sent += 1
                        print(f"   ✅ Sent reminder to {user.display_name} ({len(missing_days)} missing days)")
                    else:
                        notifications_failed += 1
                        print(f"   ❌ Failed to send reminder to {user.display_name}")
                else:
                    notifications_failed += 1
                    print(f"   ⚠️ No Slack ID for {user.display_name}, skipped")
        
        print(f"✅ Sent {notifications_sent} reminders, {notifications_failed} failed/skipped")
        
    except Exception as e:
        print(f"❌ Failed to send reminders: {e}")
        raise


def _send_admin_report_via_slack(settings, slack_service: SlackService, file_path: Path, year: int, month: int):
    """Helper to send admin report via Slack."""
    if not settings.admin_emails:
        print("⚠️ No admin emails found in ADMIN_EMAILS")
        return
    
    print(f"📤 Sending admin report to {len(settings.admin_emails)} admin(s)...")
    success_count = 0
    for admin_email in settings.admin_emails:
        success = slack_service.send_admin_report(str(admin_email), str(file_path), year, month)
        status = "✅ sent" if success else "❌ failed"
        print(f"   {status} to {admin_email}")
        if success:
            success_count += 1
    
    print(f"✅ Sent admin report to {success_count}/{len(settings.admin_emails)} admin(s)")


def _send_project_stats_to_producers(settings, file_path: Path, year: int, month: int, project_name: Optional[str] = None):
    """Helper function to send project stats report to producers."""
    slack_service = SlackService(settings) if settings.send_monthly_reports else None
    if not slack_service:
        print("❌ Slack service not available. Check SEND_MONTHLY_REPORTS setting.")
        return
    
    if not settings.producer_emails:
        print("⚠️ No producer emails found in PRODUCER_EMAILS")
        return
    
    print(f"📤 Sending project stats report to {len(settings.producer_emails)} producer(s)...")
    success_count = 0
    for producer_email in settings.producer_emails:
        print(f"   🔍 Checking producer: {producer_email}")
        success = slack_service.send_project_stats_report(str(producer_email), str(file_path), year, month, project_name)
        status = "✅ sent" if success else "❌ failed"
        print(f"      {status} to {producer_email}")
        if success:
            success_count += 1
    
    print(f"✅ Sent project stats report to {success_count}/{len(settings.producer_emails)} producer(s)")


@cli.command()
@click.option("--year", type=int, help="Year (defaults to previous month)")
@click.option("--month", type=int, help="Month 1-12 (defaults to previous month)")
def send_admin_report(year: Optional[int], month: Optional[int]):
    """Send admin report to admins via Slack."""
    settings = load_settings()
    
    # Resolve month parameters using helper
    year, month, _, _ = _resolve_month_params(year, month)
    
    print(f"📤 Sending admin report for {year}-{month:02d} to admins...")
    
    try:
        # Initialize services
        slack_service = SlackService(settings) if settings.send_monthly_reports else None
        if not slack_service:
            print("❌ Slack service not available. Check SEND_MONTHLY_REPORTS setting.")
            return
        
        file_storage = FileStorage(settings)
        admin_xlsx_path = file_storage._get_role_file_path("admin", year, month, "xlsx")
        
        # Check if file exists
        if not admin_xlsx_path.exists():
            print(f"❌ Admin report file not found: {admin_xlsx_path}")
            print(f"   Please generate the report first using: report-monthly --role admin")
            return
        
        # Send to all admins
        if not settings.admin_emails:
            print("⚠️ No admin emails found in ADMIN_EMAILS")
            return
        
        print(f"📤 Sending admin report to {len(settings.admin_emails)} admin(s)...")
        success_count = 0
        for admin_email in settings.admin_emails:
            print(f"   🔍 Checking admin: {admin_email}")
            success = slack_service.send_admin_report(str(admin_email), str(admin_xlsx_path), year, month)
            status = "✅ sent" if success else "❌ failed"
            print(f"      {status} to {admin_email}")
            if success:
                success_count += 1
        
        print(f"✅ Sent admin report to {success_count}/{len(settings.admin_emails)} admin(s)")
        
    except Exception as e:
        print(f"❌ Failed to send admin report: {e}")
        raise


@cli.command()
@click.option("--year", type=int, help="Year (defaults to previous month)")
@click.option("--month", type=int, help="Month 1-12 (defaults to previous month)")
def send_proj_stats(year: Optional[int], month: Optional[int]):
    """Send project statistics report to producers via Slack."""
    settings = load_settings()
    
    # Resolve month parameters using helper
    year, month, _, _ = _resolve_month_params(year, month)
    
    print(f"📤 Sending project stats report for {year}-{month:02d} to producers...")
    
    try:
        # Initialize services
        slack_service = SlackService(settings) if settings.send_monthly_reports else None
        if not slack_service:
            print("❌ Slack service not available. Check SEND_MONTHLY_REPORTS setting.")
            return
        
        file_storage = FileStorage(settings)
        project_stats_path = file_storage._get_role_file_path("project_stats", year, month, "xlsx")
        
        # Check if file exists
        if not project_stats_path.exists():
            print(f"❌ Project stats report file not found: {project_stats_path}")
            print(f"   Please generate the report first using: report-monthly --proj-stats")
            return
        
        # Send to all producers
        if not settings.producer_emails:
            print("⚠️ No producer emails found in PRODUCER_EMAILS")
            return
        
        print(f"📤 Sending project stats report to {len(settings.producer_emails)} producer(s)...")
        success_count = 0
        for producer_email in settings.producer_emails:
            print(f"   🔍 Checking producer: {producer_email}")
            success = slack_service.send_project_stats_report(str(producer_email), str(project_stats_path), year, month)
            status = "✅ sent" if success else "❌ failed"
            print(f"      {status} to {producer_email}")
            if success:
                success_count += 1
        
        print(f"✅ Sent project stats report to {success_count}/{len(settings.producer_emails)} producer(s)")
    
    except Exception as e:
        print(f"❌ Failed to send project stats report: {e}")
        raise


@cli.command()
def test_slack():
    """Test Slack integration by sending a test message."""
    settings = load_settings()
    
    if not settings.slack_test_user_id:
        print("❌ SLACK_TEST_USER_ID not set in configuration")
        return
    
    print(f"🧪 Testing Slack integration with user {settings.slack_test_user_id}...")
    
    try:
        slack_service = SlackService(settings)
        success = slack_service.send_test_message(settings.slack_test_user_id)
        
        if success:
            print("✅ Test message sent successfully!")
        else:
            print("❌ Failed to send test message")
    
    except Exception as e:
        print(f"❌ Slack test failed: {e}")


def _get_active_projects(toggl_service: TogglService) -> List[Project]:
    """Get list of active projects from Toggl."""
    try:
        projects_data = toggl_service.get_projects()
        projects = []
        for project_data in projects_data:
            try:
                project = Project.from_toggl(project_data)
                if project.active:
                    projects.append(project)
            except Exception:
                continue
        return projects
    except Exception as e:
        print(f"⚠️ Failed to fetch projects: {e}")
        return []


def _ensure_project_cache(
    settings,
    toggl_service: TogglService,
    timetastic_service: TimetasticService,
    project_start_date: date,
    end_date: date
):
    """Ensure cache exists for all months in project period."""
    current = project_start_date.replace(day=1)
    end_month = end_date.replace(day=1)
    
    months_to_cache = []
    while current <= end_month:
        year = current.year
        month = current.month
        months_to_cache.append((year, month))
        
        if month == 12:
            current = current.replace(year=year + 1, month=1)
        else:
            current = current.replace(month=month + 1)
    
    for year, month in months_to_cache:
        month_start = date(year, month, 1)
        if month == 12:
            month_end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            month_end = date(year, month + 1, 1) - timedelta(days=1)
        
        start_iso = f"{month_start}T00:00:00Z"
        end_iso = f"{month_end}T23:59:59Z"
        
        try:
            toggl_service.get_time_entries(start_iso, end_iso, force_refresh=False)
            timetastic_service.get_holidays(start_iso, end_iso, force_refresh=False)
        except Exception:
            pass


@cli.command()
@click.option("--project-name", multiple=True, help="Project name(s) to generate stats for (can be specified multiple times)")
@click.option("--start-date", help="Start date (YYYY-MM-DD, defaults to project first tracking date)")
@click.option("--end-date", help="End date (YYYY-MM-DD, defaults to today)")
@click.option("--target", type=click.Choice(['production']), default='production',
              help="Target: production (project stats for producers)")
@click.option("--send", is_flag=True, default=False, help="Send project statistics report to producers via Slack")
def report_project_stats(project_name: tuple, start_date: Optional[str], end_date: Optional[str], target: str, send: bool):
    """Generate project overtime statistics for selected projects."""
    settings = load_settings()
    
    print("📊 Generating project overtime statistics...")
    
    try:
        # Initialize services
        storage = SQLiteStorage(settings)
        toggl_service = TogglService(settings, storage=storage)
        timetastic_service = TimetasticService(settings, storage=storage)
        
        # Get active projects
        active_projects = _get_active_projects(toggl_service)
        if not active_projects:
            print("❌ No active projects found")
            return
        
        # Select projects
        selected_projects: List[Project] = []
        project_names_list = list(project_name) if project_name else []
        
        if not project_names_list:
            # Interactive selection
            print("\n📋 Available active projects:")
            for idx, proj in enumerate(active_projects, start=1):
                print(f"   {idx}. {proj.name} (ID: {proj.project_id})")
            
            response = input("\nEnter project names or numbers (comma-separated, or 'all' for all projects): ").strip()
            if response.lower() == 'all':
                selected_projects = active_projects
            else:
                tokens = [t.strip() for t in response.split(",")]
                for token in tokens:
                    # Try as number first
                    try:
                        idx = int(token) - 1
                        if 0 <= idx < len(active_projects):
                            selected_projects.append(active_projects[idx])
                            continue
                    except ValueError:
                        pass
                    
                    # Try as name
                    normalized_token = token.lower().strip()
                    for proj in active_projects:
                        if proj.name.lower().strip() == normalized_token:
                            selected_projects.append(proj)
                            break
        else:
            # Use provided project names
            normalized_names = {name.lower().strip() for name in project_names_list}
            for proj in active_projects:
                if proj.name.lower().strip() in normalized_names:
                    selected_projects.append(proj)
        
        if not selected_projects:
            print("❌ No projects selected")
            return
        
        print(f"\n✅ Selected {len(selected_projects)} project(s):")
        for proj in selected_projects:
            print(f"   • {proj.name}")
        
        # Parse dates
        end_date_obj = date.today()
        if end_date:
            try:
                end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
            except ValueError:
                print(f"❌ Invalid end date format: {end_date}. Use YYYY-MM-DD")
                return
        
        # Get users
        users = storage.get_all_users()
        if not users:
            print("❌ No users found. Run 'sync-users' first.")
            return
        
        # Filter eligible users
        eligible_users = _get_toggl_users_only(users, settings)
        
        if not eligible_users:
            print("❌ No eligible users found")
            return
        
        # Initialize logic components
        aggregator = DataAggregator(settings)
        overtime_calc = OvertimeCalculator(settings)
        stats_gen = StatisticsGenerator(settings)
        file_storage = FileStorage(settings)
        
        # Process each project
        projects_data: Dict[str, List[Dict[str, Any]]] = {}
        project_info: Dict[str, Dict[str, Any]] = {}  # project_name -> {start_date, first_tracking_date}
        
        for project in selected_projects:
            project_name_display = project.name
            print(f"\n📈 Processing project: {project_name_display} (ID: {project.project_id})")
            
            # Find first tracking date
            first_tracking_date = toggl_service.get_project_first_tracking_date(
                project=project
            )
            
            if not first_tracking_date:
                if project.start_date:
                    first_tracking_date = project.start_date
                else:
                    continue
            
            print(f"   ✅ First tracking date: {first_tracking_date}")
            
            # Determine date range
            start_date_obj = first_tracking_date
            if start_date:
                try:
                    user_start = datetime.strptime(start_date, "%Y-%m-%d").date()
                    if user_start > first_tracking_date:
                        start_date_obj = user_start
                except ValueError:
                    pass
            
            if start_date_obj > end_date_obj:
                continue
            
            # Ensure cache for project period (cache will auto-refresh if stale)
            _ensure_project_cache(settings, toggl_service, timetastic_service, start_date_obj, end_date_obj)
            
            # Generate monthly sequence
            months_sequence = []
            current = start_date_obj.replace(day=1)
            end_month = end_date_obj.replace(day=1)
            while current <= end_month:
                months_sequence.append((current.year, current.month))
                if current.month == 12:
                    current = current.replace(year=current.year + 1, month=1)
                else:
                    current = current.replace(month=current.month + 1)
            
            print(f"   📅 Processing {len(months_sequence)} month(s)...")
            
            # Aggregate data for all months
            all_user_data: Dict[str, Dict[str, Any]] = {}
            all_overtime_data: Dict[str, Dict[str, Any]] = {}
            user_project_entries_all: Dict[str, List] = {}  # user_email -> list of project entries
            
            for year, month in months_sequence:
                month_start = date(year, month, 1)
                if month == 12:
                    month_end = date(year + 1, 1, 1) - timedelta(days=1)
                else:
                    month_end = date(year, month + 1, 1) - timedelta(days=1)
                
                # Skip if outside project range
                if month_end < start_date_obj or month_start > end_date_obj:
                    continue
                
                start_iso = f"{month_start}T00:00:00Z"
                end_iso = f"{month_end}T23:59:59Z"
                
                # Get time entries and absences for all users
                all_time_entries = toggl_service.get_time_entries(start_iso, end_iso)
                all_absences = timetastic_service.get_holidays(start_iso, end_iso)
                
                # Filter entries for this project
                project_entries = [
                    te for te in all_time_entries
                    if (project.project_id and te.project_id == project.project_id) or
                       (te.project_name and te.project_name.lower().strip() == project_name_display.lower().strip())
                ]
                
                # Process each user
                users_with_data = 0
                for user in eligible_users:
                    user_email = user.email.lower()
                    
                    # Filter entries for this user
                    user_time_entries = [
                        te for te in all_time_entries
                        if te.user_id == user.toggl_user_id
                    ]
                    
                    # Filter project entries for this user
                    user_project_entries = [
                        te for te in project_entries
                        if te.user_id == user.toggl_user_id
                    ]
                    
                    if user_project_entries:
                        users_with_data += 1
                        # Store entries for calculating first/last entry dates
                        if user_email not in user_project_entries_all:
                            user_project_entries_all[user_email] = []
                        user_project_entries_all[user_email].extend(user_project_entries)
                    
                    # Filter absences for this user
                    timetastic_user_id = user.timetastic_user_id if user.timetastic_user_id else None
                    user_absences = [
                        abs for abs in all_absences
                        if timetastic_user_id and abs.user_id == timetastic_user_id
                    ]
                    
                    # Aggregate monthly data
                    monthly_data = aggregator.aggregate_monthly(
                        user_email, year, month, user_time_entries, user_absences
                    )
                    
                    # Calculate overtime
                    daily_data = monthly_data.get("daily_data", [])
                    overtime_data = overtime_calc.calculate_user_overtime(
                        user_email, year, month, daily_data
                    )
                    
                    # Merge into combined data
                    if user_email not in all_user_data:
                        all_user_data[user_email] = {
                            'daily_data': [],
                            'project_hours': {},
                            'project_task_hours': {},
                            'total_hours': 0.0,
                        }
                    
                    combined = all_user_data[user_email]
                    combined['daily_data'].extend(daily_data)
                    combined['total_hours'] += monthly_data.get('total_hours', 0.0)
                    
                    # Merge project hours
                    for proj_name, hours in (monthly_data.get('project_hours') or {}).items():
                        combined['project_hours'][proj_name] = combined['project_hours'].get(proj_name, 0.0) + hours
                    
                    # Merge project task hours
                    for proj_name, tasks in (monthly_data.get('project_task_hours') or {}).items():
                        if proj_name not in combined['project_task_hours']:
                            combined['project_task_hours'][proj_name] = {}
                        for task_name, task_hours in tasks.items():
                            combined['project_task_hours'][proj_name][task_name] = \
                                combined['project_task_hours'][proj_name].get(task_name, 0.0) + task_hours
                    
                    # Merge overtime data
                    if user_email not in all_overtime_data:
                        all_overtime_data[user_email] = {'daily_breakdown': []}
                    all_overtime_data[user_email]['daily_breakdown'].extend(
                        overtime_data.get('daily_breakdown', [])
                    )
            
            # Generate project-specific statistics
            project_stats = stats_gen.generate_project_specific_stats(
                all_user_data,
                eligible_users,
                all_overtime_data,
                project_name=project_name_display,
                start_date=start_date_obj,
                end_date=end_date_obj,
            )
            
            # Calculate first and last entry dates per user
            user_entry_dates: Dict[str, Dict[str, Optional[date]]] = {}
            for user_email, entries in user_project_entries_all.items():
                if entries:
                    entry_dates = [e.date for e in entries]
                    user_entry_dates[user_email] = {
                        'first_entry': min(entry_dates),
                        'last_entry': max(entry_dates)
                    }
                else:
                    user_entry_dates[user_email] = {
                        'first_entry': None,
                        'last_entry': None
                    }
            
            # Add entry dates to project stats
            for stat in project_stats:
                user_email = stat.get('user_email', '').lower()
                if user_email in user_entry_dates:
                    stat['first_entry'] = user_entry_dates[user_email]['first_entry']
                    stat['last_entry'] = user_entry_dates[user_email]['last_entry']
            
            if project_stats:
                projects_data[project_name_display] = project_stats
                # Store project info
                project_info[project_name_display] = {
                    'start_date': project.start_date,
                    'first_tracking_date': first_tracking_date
                }
                print(f"   ✅ Generated {len(project_stats)} row(s) for {project_name_display}")
            else:
                print(f"   ⚠️ No data found for {project_name_display}")
        
        # Export to XLSX
        if projects_data:
            # Generate filename
            if len(selected_projects) == 1:
                project_name_safe = selected_projects[0].name.replace("/", "_").replace("\\", "_").replace(":", "_")
                filename = f"project_{project_name_safe}_{end_date_obj.year}-{end_date_obj.month:02d}.xlsx"
            else:
                filename = f"projects_{end_date_obj.year}-{end_date_obj.month:02d}.xlsx"
            
            export_path = file_storage.exports_dir / filename
            stats_gen.export_project_overtime_xlsx(projects_data, export_path, project_info)
            print(f"\n✅ Project statistics exported to: {export_path}")
            
            # Send to producers if requested
            if send:
                # Extract project name(s) for message
                if len(selected_projects) == 1:
                    project_name_for_message = selected_projects[0].name
                elif len(selected_projects) > 1:
                    project_name_for_message = f"{len(selected_projects)} projects"
                else:
                    project_name_for_message = None
                _send_project_stats_to_producers(settings, export_path, end_date_obj.year, end_date_obj.month, project_name_for_message)
        else:
            print("\n❌ No project data to export")
    
    except Exception as e:
        print(f"❌ Project statistics generation failed: {e}")
        raise


if __name__ == "__main__":
    cli()
