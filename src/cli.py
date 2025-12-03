"""
CLI for the Timetastic-Toggl sync system using the restructured architecture.
"""

import os
import sys
import click
from datetime import datetime, date, timedelta
from typing import Optional

from .config import load_settings
from .services import TogglService, TimetasticService, SlackService, UserService
from .storage import SQLiteStorage, FileStorage
from .logic import DataAggregator, OvertimeCalculator, ReportGenerator
from .access_control import PermissionManager


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
        time_entries = toggl_service.get_time_entries(start_iso, end_iso)
        print(f"   ✅ Found {len(time_entries)} time entries")

        print("🏖️ Fetching absences from Timetastic...")
        absences = timetastic_service.get_holidays(start_iso, end_iso)
        # Removed duplicate absences log

        print("💾 Saving data to database...")
        print(f"   [DEBUG _sync_range] Saving {len(time_entries)} time entries and {len(absences)} absences")
        if absences:
            print(f"   [DEBUG _sync_range] Sample absences before save (first 3):")
            for abs in absences[:3]:
                print(f"      {abs.start_date} to {abs.end_date} | type={abs.absence_type} | status={abs.status} | user_email={abs.user_email} | notes={abs.notes[:50] if abs.notes else None}")
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

    print("?? Refreshing user mappings before reporting...")
    users = user_service.sync_users_from_services()
    saved = 0
    for user in users:
        if storage.save_user(user):
            saved += 1

    # Removed debug logs - stats calculation kept for potential future use
    stats = user_service.get_user_statistics(users)
    return users


def _build_slack_email_map(slack_service: SlackService) -> dict:
    """Fetch Slack users once and build email->id map to avoid per-user lookups."""
    try:
        members = slack_service.get_users()
    except Exception as exc:
        print(f"?? Slack lookup failed (users_list): {exc}")
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
    """Fetch cached data, aggregate, calculate overtime and build UserReport."""
    print(f"   [DEBUG] Generating report for {user.email} ({year}-{month:02d})")
    
    # TODO: WRÓCIMY PÓŹNIEJ - SQLite storage dla processed statistics
    # Wyłączone na razie - nie używamy SQLite do przechowywania processed statistics
    # Zostajemy przy cache'ach API (Timetastic, Toggl) i bezpośrednim pobieraniu danych z API
    # 
    # # Check if processed results exist in SQLite
    # monthly_stats = None
    # daily_stats = None
    # overtime_stats = None
    # 
    # if not force_refresh:
    #     monthly_stats = storage.get_monthly_statistics(user.email, year, month)
    #     if monthly_stats:
    #         daily_stats = storage.get_daily_statistics(user.email, year, month)
    #         overtime_stats = storage.get_overtime_data(user.email, year, month)
    # 
    # if monthly_stats and daily_stats and overtime_stats and not force_refresh:
    #     # Use cached processed results from SQLite
    #     print(f"   [DEBUG] Using cached processed results from SQLite")
    #     
    #     # Reconstruct monthly_data from cached statistics
    #     monthly_data = {
    #         'total_hours': monthly_stats['total_hours'],
    #         'absence_hours': monthly_stats['absence_hours'],
    #         'working_days': monthly_stats['working_days'],
    #         'project_hours': monthly_stats['project_hours'],
    #         'absence_breakdown': monthly_stats['absence_breakdown'],
    #         'missing_days': monthly_stats['missing_days'],
    #         'daily_data': daily_stats
    #     }
    #     
    #     # Reconstruct overtime_data from cached statistics
    #     overtime_data = overtime_stats
    #     
    #     print(f"   [DEBUG] Cached: Total hours={monthly_data.get('total_hours', 0):.2f}h")
    # else:
    
    # Process from raw data (time entries and absences) - pobieramy bezpośrednio z API
    print(f"   [DEBUG] Processing from raw data (fetching from API)...")
    
    # TODO: WRÓCIMY PÓŹNIEJ - SQLite storage dla raw data
    # Wyłączone na razie - nie używamy SQLite do przechowywania raw data
    # time_entries = storage.get_time_entries_for_user(user.email, start_date, end_date)
    # absences = storage.get_absences_for_user(user.email, start_date, end_date)
    
    # Pobieramy dane bezpośrednio z API (używają cache'ów wewnętrznych)
    start_iso = f"{start_date}T00:00:00Z"
    end_iso = f"{end_date}T23:59:59Z"
    
    # Pobierz time entries z Toggl (używa cache jeśli dostępny) - filtrujemy tylko po user_id
    user_ids = [user.toggl_user_id] if user.toggl_user_id else None
    print(f"   [DEBUG] API: Fetching Toggl entries for user_id={user_ids}, user_email={user.email}")
    all_time_entries = toggl_service.get_time_entries(start_iso, end_iso, user_ids=user_ids)
    
    # Filtruj po user_id (Toggl API powinien już zwrócić przefiltrowane, ale na wszelki wypadek filtrujemy lokalnie)
    if user.toggl_user_id:
        time_entries = [te for te in all_time_entries if te.user_id == user.toggl_user_id]
    else:
        time_entries = all_time_entries
    
    print(f"   [DEBUG] API: Found {len(time_entries)} time entries from Toggl API")
    
    # Pobierz absences z Timetastic (używa cache jeśli dostępny)
    timetastic_user_id = user.timetastic_user_id if user.timetastic_user_id else None
    user_ids_for_absences = [timetastic_user_id] if timetastic_user_id else None
    absences = timetastic_service.get_holidays(start_iso, end_iso, user_ids=user_ids_for_absences)
    print(f"   [DEBUG] API: Found {len(absences)} absences from Timetastic API")
    
    monthly_data = aggregator.aggregate_monthly(user.email, year, month, time_entries, absences)
    print(f"   [DEBUG] Aggregator: Total hours={monthly_data.get('total_hours', 0):.2f}h")
    
    daily_data = monthly_data.get("daily_data", [])
    overtime_data = overtime_calc.calculate_user_overtime(
        user.email, year, month, daily_data
    )
    print(f"   [DEBUG] OvertimeCalc: Monthly OT={overtime_data.get('monthly_overtime', 0):.2f}h")
    
    # Save processed data to SQLite (monthly statistics, daily statistics, overtime data)
    saved = storage.save_user_monthly_processed_data(user.email, year, month, monthly_data, overtime_data)
    if saved:
        print(f"   [DEBUG SQLite] Saved processed data to SQLite for {user.email} ({year}-{month:02d})")
        print(f"      - Monthly statistics: {monthly_data.get('total_hours', 0):.2f}h total, {monthly_data.get('working_days', 0)} working days")
        print(f"      - Daily statistics: {len(daily_data)} days")
        print(f"      - Overtime data: {overtime_data.get('monthly_overtime', 0):.2f}h monthly overtime")
    else:
        print(f"   [DEBUG SQLite] Failed to save processed data to SQLite for {user.email} ({year}-{month:02d})")
    
    monthly_report = report_gen.generate_monthly_user_report(
        user_email=user.email,
        user_name=user.display_name,
        year=year,
        month=month,
        user_data=monthly_data,
        overtime_data=overtime_data,
        department=user.department,
    )
    print(f"   [DEBUG] ReportGen: Report created, total_hours={monthly_report.total_hours:.2f}h")
    
    return monthly_data, overtime_data, monthly_report

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

        print("\n🧾 Detailed user list:")
        for idx, user in enumerate(users, start=1):
            excluded = ""
            if user.email and user.email.lower() in settings.excluded_report_emails:
                excluded = " [EXCLUDED]"
            print(
                f"   {idx}. {user.display_name} <{user.email}> "
                f"(toggl={user.toggl_user_id}, timetastic={user.timetastic_user_id}, slack={user.slack_user_id}){excluded}"
            )
        
    except Exception as e:
        print(f"❌ User sync failed: {e}")
        raise


@cli.command()
@click.option("--days", default=7, help="Number of days to check back (default: 7)")
def check_missing(days: int):
    """Check for missing time entries and send Slack reminders."""
    settings = load_settings()
    
    if not settings.send_missing_entries_notifications:
        print("ℹ️ Missing entries notifications are disabled in configuration")
        return
    
    print(f"🔍 Checking for missing entries in the last {days} days...")
    
    try:
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        
        # Initialize services
        user_service = UserService(settings)
        slack_service = SlackService(settings)
        storage = SQLiteStorage(settings)
        aggregator = DataAggregator(settings)
        
        # Get users
        users = storage.get_all_users()
        if not users:
            print("❌ No users found. Run 'sync-users' first.")
            return

        
        # Get time entries and absences
        time_entries = storage.get_time_entries_for_period(start_date, end_date)
        absences = []
        
        # Get absences for each user
        for user in users:
            user_absences = storage.get_absences_for_user(user.email, start_date, end_date)
            absences.extend(user_absences)
        
        # Detect missing entries
        missing_by_user = aggregator.detect_missing_entries(users, time_entries, absences, start_date, end_date)
        
        # Send notifications
        notifications_sent = 0
        for user_email, missing_days in missing_by_user.items():
            if missing_days:
                user = next((u for u in users if u.email.lower() == user_email), None)
                if user and user.slack_user_id:
                    success = slack_service.send_missing_entries_reminder(user_email, missing_days, days)
                    if success:
                        notifications_sent += 1
                        print(f"   📤 Sent reminder to {user.display_name}")
                    else:
                        print(f"   ❌ Failed to send reminder to {user.display_name}")
        
        print(f"✅ Sent {notifications_sent} missing entry reminders")
        
    except Exception as e:
        print(f"❌ Missing entries check failed: {e}")
        raise


@cli.command()
@click.option("--year", type=int, help="Year (defaults to previous month)")
@click.option("--month", type=int, help="Month 1-12 (defaults to previous month)")
@click.option("--user", "target_user", help="Generate report for specific user email")
@click.option("--role", type=click.Choice(['admin', 'user']), help="Generate report for specific role")
@click.option("--send-all-users", is_flag=True, default=False, help="Send Slack reports to every user after generating CSVs")
@click.option("--refresh-cache", is_flag=True, default=False, help="Refresh the target month's data from Toggl/Timetastic before generating reports")
@click.option("--force-refresh", is_flag=True, default=False, help="Force reprocessing of statistics even if cached results exist")
@click.option("--refresh-projects", is_flag=True, default=False, help="Force refresh projects cache before generating reports")
def report_monthly(year: Optional[int], month: Optional[int], target_user: Optional[str], role: Optional[str], send_all_users: bool, refresh_cache: bool, force_refresh: bool, refresh_projects: bool):
    """Generate monthly reports."""
    settings = load_settings()

    # Determine target month
    if not year or not month:
        today = date.today()
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        year, month = last_prev.year, last_prev.month

    print(f"?? Generating monthly reports for {year}-{month:02d}...")

    try:
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)

        # Optionally refresh cache (users + month data) before reporting
        users = None
        if refresh_cache:
            users = _sync_users_and_cache(settings)
            print(f"?? Refreshing cache for whole month ({start_date} to {end_date}) before reporting...")
            _sync_range(settings, start_date, end_date, "monthly_refresh")

        # Initialize services
        print(f"[DEBUG] Initializing services for {year}-{month:02d}...")
        storage = SQLiteStorage(settings)  # Still used for user management
        toggl_service = TogglService(settings, storage=storage)  # Create for API tracking and cache
        timetastic_service = TimetasticService(settings, storage=storage)  # Create for API tracking and cache
        
        # Refresh projects cache if requested
        if refresh_projects:
            print(f"[DEBUG] Refreshing projects cache...")
            try:
                toggl_service.get_projects(force_refresh=True)
                print(f"[DEBUG] Projects cache refreshed")
            except Exception as e:
                print(f"[DEBUG] Warning: Failed to refresh projects cache: {e}")
        
        file_storage = FileStorage(settings)
        aggregator = DataAggregator(settings)
        overtime_calc = OvertimeCalculator(settings)
        report_gen = ReportGenerator(settings)
        print(f"[DEBUG] Services initialized")

        if users is None:
            users = storage.get_all_users()
        if not users:
            print("? No users found. Run 'sync-users' first.")
            return
        print(f"[DEBUG] Found {len(users)} users in storage")

        if send_all_users and not settings.send_monthly_reports:
            print("?? SEND_MONTHLY_REPORTS disabled; enable it to deliver Slack summaries.")
            send_all_users = False

        slack_service: Optional[SlackService] = SlackService(settings) if settings.send_monthly_reports else None
        slack_email_map: dict = {}
        if slack_service and send_all_users:
            slack_email_map = _build_slack_email_map(slack_service)

        excluded_emails = settings.excluded_report_emails
        included_emails = settings.included_report_emails
        eligible_users = users
        if send_all_users:
            if included_emails:
                eligible_users = [
                    u for u in users
                    if u.toggl_user_id and u.email and u.email.lower() in included_emails
                ]
            else:
                eligible_users = [
                    u for u in users
                    if u.toggl_user_id and u.email and u.email.lower() not in excluded_emails
                ]
            if not eligible_users:
                print("?? No eligible Toggl users found; nothing to send.")
                return
            print(f"?? Sending Slack reports for {len(eligible_users)} Toggl users")
            print("?? Recipients:")
            for idx, user_obj in enumerate(eligible_users, start=1):
                slack_info = f", slack_id={user_obj.slack_user_id}" if user_obj.slack_user_id else ""
                timetastic_info = f", timetastic_id={user_obj.timetastic_user_id}" if user_obj.timetastic_user_id else ""
                print(f"   {idx}. {user_obj.display_name} <{user_obj.email}> (toggl_id={user_obj.toggl_user_id}{timetastic_info}{slack_info})")

        if send_all_users:
            failures = 0
            successes = 0
            for user_obj in eligible_users:
                user_label = user_obj.display_name or user_obj.email
                try:
                    monthly_data, overtime_data, user_report = _generate_user_monthly_report(
                        user_obj, start_date, end_date, aggregator, overtime_calc, report_gen, toggl_service, timetastic_service, storage, year, month, force_refresh
                    )
                except Exception as exc:
                    failures += 1
                    print(f"   ? Failed to build report for {user_label}: {exc}")
                    continue

                print(f"   ?? Overtime debug for {user_label}:")
                print(report_gen.format_overtime_debug(overtime_data))

                if slack_service:
                    slack_user_id = user_obj.slack_user_id or slack_email_map.get(user_obj.email.lower())
                    if not slack_user_id:
                        failures += 1
                        print(f"   ? Slack user not found for {user_obj.email} (missing email match or deleted user); skipped sending.")
                        continue
                    try:
                        success = slack_service.send_dm(slack_user_id, report_gen.format_user_report_summary(user_report))
                    except Exception as exc:
                        success = False
                        print(f"   ? Slack send exception for {user_label}: {exc}")
                    status = "sent" if success else "failed"
                    if success:
                        successes += 1
                    else:
                        failures += 1
                    print(f"   ?? Slack report {status} for {user_label} (slack_id={slack_user_id})")
                else:
                    print(f"   ?? Slack disabled; generated report for {user_label} but not sent.")
            print(f"? Bulk Slack reporting finished: {successes} sent, {failures} failed")
            return

        # Generate reports based on parameters
        if target_user:
            user_email = target_user.lower()
            user_obj = next((u for u in users if u.email.lower() == user_email), None)
            if user_obj:
                monthly_data, overtime_data, user_report = _generate_user_monthly_report(
                    user_obj, start_date, end_date, aggregator, overtime_calc, report_gen, toggl_service, timetastic_service, storage, year, month
                )
                print(f"?? Overtime debug for {user_obj.display_name}:")
                print(report_gen.format_overtime_debug(overtime_data))
                csv_file = file_storage.export_user_report_csv(user_report)
                print(f"? User report exported to: {csv_file}")
                if slack_service:
                    slack_service.send_monthly_report(user_obj.email, user_report.to_dict())
                    print(f"?? Monthly report sent to {user_obj.display_name}")
            else:
                print(f"? User {target_user} not found or has no data for this period")

        elif role:
            if role == "admin":
                all_user_data = {}
                for user in users:
                    monthly_data, _, _ = _generate_user_monthly_report(
                        user, start_date, end_date, aggregator, overtime_calc, report_gen, toggl_service, timetastic_service, storage, year, month, force_refresh
                    )
                    all_user_data[user.email.lower()] = monthly_data
                admin_reports = report_gen.generate_admin_report(users, all_user_data, year, month)
                csv_file = file_storage.export_admin_report_csv(admin_reports, year, month)
                print(f"? Admin report exported to: {csv_file}")

        else:
            print("?? Generating all report types...")
            all_user_data = {}
            admin_reports: Optional[list] = None
            for user_obj in users:
                monthly_data, overtime_data, user_report = _generate_user_monthly_report(
                    user_obj, start_date, end_date, aggregator, overtime_calc, report_gen, toggl_service, timetastic_service, storage, year, month
                )
                all_user_data[user_obj.email.lower()] = monthly_data
                csv_file = file_storage.export_user_report_csv(user_report)
                print(f"   ? User report for {user_obj.display_name}: {csv_file}")
                print(report_gen.format_overtime_debug(overtime_data))
                if send_all_users and slack_service:
                    success = slack_service.send_monthly_report(user_obj.email, user_report.to_dict())
                    status = "sent" if success else "failed"
                    print(f"      ?? Slack report {status} for {user_obj.display_name}")
            admin_reports = report_gen.generate_admin_report(users, all_user_data, year, month)
            admin_csv = file_storage.export_admin_report_csv(admin_reports, year, month)
            print(f"   ? Admin report: {admin_csv}")
            print(f"? Generated all reports for {year}-{month:02d}")

    except Exception as e:
        print(f"? Report generation failed: {e}")
        raise


@cli.command()
def notify_users():
    """Send weekly Slack notifications about missing entries."""
    settings = load_settings()
    
    if not settings.send_missing_entries_notifications:
        print("ℹ️ Missing entries notifications are disabled in configuration")
        return
    
    print("📤 Sending weekly missing entries notifications...")
    
    try:
        # Use the check_missing command with default settings
        check_missing.callback(settings.missing_entries_check_days)
        
    except Exception as e:
        print(f"❌ Notification sending failed: {e}")
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


if __name__ == "__main__":
    cli()
