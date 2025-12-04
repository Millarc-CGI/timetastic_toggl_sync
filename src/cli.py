"""
CLI for the Timetastic-Toggl sync system using the restructured architecture.
"""

import os
import sys
import click
from datetime import datetime, date, timedelta
from typing import Optional, List

from .config import load_settings
from .services import TogglService, TimetasticService, SlackService, UserService
from .storage import SQLiteStorage, FileStorage
from .logic import DataAggregator, OvertimeCalculator, ReportGenerator
from .access_control import PermissionManager
from .models.user import User


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
    
    # Pobieramy dane bezpośrednio z API (używają cache'ów wewnętrznych)
    start_iso = f"{start_date}T00:00:00Z"
    end_iso = f"{end_date}T23:59:59Z"
    
    # Pobierz time entries z Toggl (używa cache jeśli dostępny) - filtrujemy tylko po user_id
    user_ids = [user.toggl_user_id] if user.toggl_user_id else None
    all_time_entries = toggl_service.get_time_entries(start_iso, end_iso, user_ids=user_ids)
    
    # Filtruj po user_id (Toggl API powinien już zwrócić przefiltrowane, ale na wszelki wypadek filtrujemy lokalnie)
    if user.toggl_user_id:
        time_entries = [te for te in all_time_entries if te.user_id == user.toggl_user_id]
    else:
        time_entries = all_time_entries
    
    # Pobierz absences z Timetastic (używa cache jeśli dostępny)
    timetastic_user_id = user.timetastic_user_id if user.timetastic_user_id else None
    user_ids_for_absences = [timetastic_user_id] if timetastic_user_id else None
    absences = timetastic_service.get_holidays(start_iso, end_iso, user_ids=user_ids_for_absences)
    
    monthly_data = aggregator.aggregate_monthly(user.email, year, month, time_entries, absences)
    
    daily_data = monthly_data.get("daily_data", [])
    overtime_data = overtime_calc.calculate_user_overtime(
        user.email, year, month, daily_data
    )
    
    # Save processed data to SQLite (monthly statistics, daily statistics, overtime data)
    saved = storage.save_user_monthly_processed_data(user.email, year, month, monthly_data, overtime_data)
    if not saved:
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
@click.option("--user", "target_user", help="Generate report for specific user (email or full name)")
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

    print(f"📊 Generating monthly reports for {year}-{month:02d}...")

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
            print(f"🔄 Refreshing cache for whole month ({start_date} to {end_date}) before reporting...")
            _sync_range(settings, start_date, end_date, "monthly_refresh")

        # Initialize services
        storage = SQLiteStorage(settings)  # Still used for user management
        toggl_service = TogglService(settings, storage=storage)  # Create for API tracking and cache
        timetastic_service = TimetasticService(settings, storage=storage)  # Create for API tracking and cache
        
        # Refresh projects cache if requested
        if refresh_projects:
            try:
                toggl_service.get_projects(force_refresh=True)
            except Exception as e:
                print(f"⚠️ Warning: Failed to refresh projects cache: {e}")
        
        file_storage = FileStorage(settings)
        aggregator = DataAggregator(settings)
        overtime_calc = OvertimeCalculator(settings)
        report_gen = ReportGenerator(settings)

        if users is None:
            users = storage.get_all_users()
        if not users:
            print("❌ No users found. Run 'sync-users' first.")
            return

        if send_all_users and not settings.send_monthly_reports:
            print("⚠️ SEND_MONTHLY_REPORTS disabled; enable it to deliver Slack summaries.")
            send_all_users = False

        slack_service: Optional[SlackService] = SlackService(settings) if settings.send_monthly_reports else None
        slack_email_map: dict = {}
        if slack_service and send_all_users:
            slack_email_map = _build_slack_email_map(slack_service)

        excluded_emails = settings.excluded_report_emails
        eligible_users = users
        if send_all_users:
            eligible_users = [
                u for u in users
                if u.toggl_user_id and u.email and u.email.lower() not in excluded_emails
            ]
            if not eligible_users:
                print("⚠️ No eligible Toggl users found; nothing to send.")
                return
            print(f"📤 Sending Slack reports for {len(eligible_users)} Toggl users")
            print("📋 Recipients:")
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
                    print(f"   ❌ Failed to build report for {user_label}: {exc}")
                    continue

                if slack_service:
                    slack_user_id = user_obj.slack_user_id or slack_email_map.get(user_obj.email.lower())
                    if not slack_user_id:
                        failures += 1
                        print(f"   ⚠️ Slack user not found for {user_obj.email} (missing email match or deleted user); skipped sending.")
                        continue
                    try:
                        success = slack_service.send_dm(slack_user_id, report_gen.format_user_report_summary(user_report))
                    except Exception as exc:
                        success = False
                        print(f"   ❌ Slack send exception for {user_label}: {exc}")
                    status = "sent" if success else "failed"
                    if success:
                        successes += 1
                    else:
                        failures += 1
                    print(f"   📤 Slack report {status} for {user_label} (slack_id={slack_user_id})")
                else:
                    print(f"   ⚠️ Slack disabled; generated report for {user_label} but not sent.")
            print(f"✅ Bulk Slack reporting finished: {successes} sent, {failures} failed")
            return

        # Generate reports based on parameters
        if target_user:
            user_obj = _find_user_by_email_or_name(users, target_user)
            if user_obj:
                monthly_data, overtime_data, user_report = _generate_user_monthly_report(
                    user_obj, start_date, end_date, aggregator, overtime_calc, report_gen, toggl_service, timetastic_service, storage, year, month
                )
                xlsx_file = file_storage.export_user_report_xlsx(user_report)
                print(f"📄 User report exported to: {xlsx_file}")
                if slack_service:
                    if user_obj.slack_user_id:
                        # Use slack_user_id directly instead of searching by email
                        success = slack_service.send_dm(user_obj.slack_user_id, report_gen.format_user_report_summary(user_report))
                        if success:
                            print(f"📤 Monthly report sent to {user_obj.display_name}")
                        else:
                            print(f"⚠️ Failed to send monthly report to {user_obj.display_name}")
                    else:
                        # Fallback: try to find by email (for users without slack_user_id)
                        slack_service.send_monthly_report(user_obj.email, user_report.to_dict())
                        print(f"📤 Monthly report sent to {user_obj.display_name}")
            else:
                print(f"⚠️ User {target_user} not found or has no data for this period")

        elif role:
            if role == "admin":
                # Filter: only active Toggl users + admins + producers, excluding excluded users
                excluded_emails = settings.excluded_report_emails
                filtered_users_for_admin = [
                    user for user in users
                    if (user.toggl_user_id  # Active Toggl user
                        or (user.email and settings.is_admin(user.email))  # Admin
                        or (user.email and settings.is_producer(user.email)))  # Producer
                    and (not user.email or user.email.lower() not in excluded_emails)  # Not excluded
                ]
                
                all_user_data = {}
                all_overtime_data = {}
                for user in filtered_users_for_admin:
                    monthly_data, overtime_data, _ = _generate_user_monthly_report(
                        user, start_date, end_date, aggregator, overtime_calc, report_gen, toggl_service, timetastic_service, storage, year, month, force_refresh
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

        else:
            print("📊 Generating all report types...")
            all_user_data = {}
            all_overtime_data = {}
            admin_reports: Optional[list] = None
            # Filter: only active Toggl users + admins + producers, excluding excluded users
            filtered_users_for_reports = [
                user for user in users
                if (user.toggl_user_id  # Active Toggl user
                    or (user.email and settings.is_admin(user.email))  # Admin
                    or (user.email and settings.is_producer(user.email)))  # Producer
                and (not user.email or user.email.lower() not in excluded_emails)  # Not excluded
            ]
            print(f"[DEBUG] Generating reports for {len(filtered_users_for_reports)} users (filtered from {len(users)} total)")
            for user_obj in filtered_users_for_reports:
                monthly_data, overtime_data, user_report = _generate_user_monthly_report(
                    user_obj, start_date, end_date, aggregator, overtime_calc, report_gen, toggl_service, timetastic_service, storage, year, month
                )
                all_user_data[user_obj.email.lower()] = monthly_data
                all_overtime_data[user_obj.email.lower()] = overtime_data
                xlsx_file = file_storage.export_user_report_xlsx(user_report)
                print(f"   📄 User report for {user_obj.display_name}: {xlsx_file}")
                if send_all_users and slack_service:
                    success = slack_service.send_monthly_report(user_obj.email, user_report.to_dict())
                    status = "sent" if success else "failed"
                    print(f"      📤 Slack report {status} for {user_obj.display_name}")
            admin_reports = report_gen.generate_admin_report(filtered_users_for_reports, all_user_data, all_overtime_data, year, month)
            
            # Save admin statistics to SQLite
            for user_obj in filtered_users_for_reports:
                user_email = user_obj.email.lower()
                if user_email in all_user_data and user_email in all_overtime_data:
                    monthly_data = all_user_data[user_email]
                    overtime_data = all_overtime_data[user_email]
                    missing_count = len(monthly_data.get('missing_days', []))
                    storage.save_admin_statistics(
                        user_email=user_obj.email,
                        user_name=user_obj.display_name or user_obj.email,
                        department=user_obj.department,
                        year=year,
                        month=month,
                        total_hours=monthly_data.get('total_hours', 0.0),
                        expected_hours=overtime_data.get('monthly_expected_hours', 0.0),
                        monthly_overall_overtime=overtime_data.get('monthly_overtime', 0.0),
                        weekend_overtime=overtime_data.get('weekend_overtime', 0.0),
                        missing_entries_count=missing_count
                    )
            
            admin_xlsx = file_storage.export_admin_report_xlsx(admin_reports, year, month)
            print(f"   📄 Admin report: {admin_xlsx}")
            print(f"✅ Generated all reports for {year}-{month:02d} ({len(filtered_users_for_reports)} users)")

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
    """Generate weekly report for a single user."""
    start_iso = f"{week_start}T00:00:00Z"
    end_iso = f"{week_end}T23:59:59Z"
    
    # Pobierz time entries z Toggl (używa cache jeśli dostępny)
    user_ids = [user.toggl_user_id] if user.toggl_user_id else None
    all_time_entries = toggl_service.get_time_entries(start_iso, end_iso, user_ids=user_ids)
    
    # Filtruj po user_id
    if user.toggl_user_id:
        time_entries = [te for te in all_time_entries if te.user_id == user.toggl_user_id]
    else:
        time_entries = all_time_entries
    
    # Pobierz absences z Timetastic (używa cache jeśli dostępny)
    timetastic_user_id = user.timetastic_user_id if user.timetastic_user_id else None
    user_ids_for_absences = [timetastic_user_id] if timetastic_user_id else None
    absences = timetastic_service.get_holidays(start_iso, end_iso, user_ids=user_ids_for_absences)
    
    # Agreguj dane dla tygodnia
    weekly_data = aggregator.aggregate_weekly(user.email, week_start, week_end, time_entries, absences)
    
    # Oblicz overtime dla tygodnia
    daily_data = weekly_data.get("daily_data", [])
    daily_hours = [day['total_hours'] for day in daily_data]
    weekly_overtime = overtime_calc.calculate_weekly_overtime(user.email, week_start, daily_hours)
    
    # Oblicz weekend overtime (suma godzin z time entries w weekendy)
    weekend_overtime = sum(
        day.get('time_entry_hours', 0.0) 
        for day in daily_data 
        if day.get('is_weekend', False)
    )
    
    # Przygotuj overtime_data w formacie podobnym do monthly
    overtime_data = {
        'weekly_overtime': weekly_overtime,
        'monthly_overtime': 0.0,  # Nie ma monthly overtime dla tygodnia
        'weekend_overtime': weekend_overtime,
    }
    
    # Generuj raport
    weekly_report = report_gen.generate_weekly_user_report(
        user_email=user.email,
        user_name=user.display_name or user.email,
        week_start=week_start,
        week_end=week_end,
        user_data=weekly_data,
        overtime_data=overtime_data,
        department=user.department
    )
    
    return weekly_data, overtime_data, weekly_report


@cli.command()
@click.option("--week-start", help="Week start date (YYYY-MM-DD, defaults to last Monday)")
@click.option("--user", "target_user", help="Generate report for specific user (email or full name)")
@click.option("--send-all-users", is_flag=True, default=False, help="Send Slack reports to every user after generating CSVs")
@click.option("--force-refresh", is_flag=True, default=False, help="Force refresh cache before generating reports")
@click.option("--refresh-projects", is_flag=True, default=False, help="Force refresh projects cache before generating reports")
def report_weekly(week_start: Optional[str], target_user: Optional[str], send_all_users: bool, force_refresh: bool, refresh_projects: bool):
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
        # Default to last week (Monday to Sunday)
        today = date.today()
        days_since_monday = today.weekday()
        week_start_date = today - timedelta(days=days_since_monday + 7)
    
    week_end_date = week_start_date + timedelta(days=6)  # Sunday
    
    print(f"📊 Generating weekly reports for {week_start_date} to {week_end_date}")
    
    # Initialize services
    storage = SQLiteStorage(settings)
    toggl_service = TogglService(settings, storage)
    timetastic_service = TimetasticService(settings, storage)
    
    # Refresh projects cache if requested
    if refresh_projects:
        print(f"[DEBUG] Refreshing projects cache...")
        try:
            toggl_service.get_projects(force_refresh=True)
            print(f"[DEBUG] Projects cache refreshed")
        except Exception as e:
            print(f"[DEBUG] Warning: Failed to refresh projects cache: {e}")
    
    aggregator = DataAggregator(settings)
    overtime_calc = OvertimeCalculator(settings)
    report_gen = ReportGenerator(settings)
    
    # Get users
    users = storage.get_all_users()
    if not users:
        print("❌ No users found. Run 'sync-users' first.")
        return
    
    # Filter users: only active Toggl users + admins + producers, excluding excluded users
    excluded_emails = settings.excluded_report_emails
    filtered_users = [
        user for user in users
        if (user.toggl_user_id  # Active Toggl user
            or (user.email and settings.is_admin(user.email))  # Admin
            or (user.email and settings.is_producer(user.email)))  # Producer
        and (not user.email or user.email.lower() not in excluded_emails)  # Not excluded
    ]
    
    slack_service = SlackService(settings)
    
    try:
        if target_user:
            # Generate report for specific user (no Slack sending unless --send-all-users)
            user_obj = _find_user_by_email_or_name(filtered_users, target_user)
            if user_obj:
                weekly_data, overtime_data, weekly_report = _generate_user_weekly_report(
                    user_obj, week_start_date, week_end_date, aggregator, overtime_calc, report_gen,
                    toggl_service, timetastic_service, force_refresh
                )
                print(f"✅ Weekly report generated for {user_obj.display_name}")
                if send_all_users and user_obj.slack_user_id:
                    # Use slack_user_id directly instead of searching by email
                    success = slack_service.send_dm(user_obj.slack_user_id, report_gen.format_user_report_summary(weekly_report))
                    if success:
                        print(f"📤 Weekly report sent to {user_obj.display_name}")
                    else:
                        print(f"⚠️ Failed to send weekly report to {user_obj.display_name}")
            else:
                print(f"❌ User {target_user} not found or has no data for this week")
        
        elif send_all_users:
            # Generate reports for all eligible users
            print(f"📤 Generating weekly reports for {len(filtered_users)} users")
            failures = 0
            successes = 0
            
            for user_obj in filtered_users:
                user_label = user_obj.display_name or user_obj.email
                try:
                    weekly_data, overtime_data, weekly_report = _generate_user_weekly_report(
                        user_obj, week_start_date, week_end_date, aggregator, overtime_calc, report_gen,
                        toggl_service, timetastic_service, force_refresh
                    )
                    
                    slack_user_id = user_obj.slack_user_id
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
                        
                except Exception as exc:
                    failures += 1
                    print(f"   ❌ Failed to build report for {user_label}: {exc}")
                    continue
            
            print(f"✅ Bulk weekly reporting finished: {successes} sent, {failures} failed")
        
        else:
            # Generate reports for all users (no Slack sending unless --send-all-users)
            print(f"📊 Generating weekly reports for {len(filtered_users)} users...")
            for user_obj in filtered_users:
                try:
                    weekly_data, overtime_data, weekly_report = _generate_user_weekly_report(
                        user_obj, week_start_date, week_end_date, aggregator, overtime_calc, report_gen,
                        toggl_service, timetastic_service, force_refresh
                    )
                    print(f"   ✅ Weekly report generated for {user_obj.display_name}")
                    
                    if send_all_users:
                        slack_user_id = user_obj.slack_user_id
                        if not slack_user_id:
                            print(f"   ⚠️ Slack user not found for {user_obj.email}; skipped sending.")
                            continue
                        try:
                            success = slack_service.send_dm(slack_user_id, report_gen.format_user_report_summary(weekly_report))
                        except Exception as exc:
                            success = False
                            print(f"   ⚠️ Slack send exception for {user_obj.display_name}: {exc}")
                        status = "sent" if success else "failed"
                        print(f"   📤 Slack report {status} for {user_obj.display_name}")
                except Exception as exc:
                    print(f"   ❌ Failed to build report for {user_obj.display_name}: {exc}")
                    continue
            
            if send_all_users:
                print(f"✅ Generated and sent weekly reports for {week_start_date} to {week_end_date}")
            else:
                print(f"✅ Generated weekly reports for {week_start_date} to {week_end_date} (use --send-all-users to send via Slack)")
    
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
        excluded_emails = settings.excluded_report_emails
        users = [
            u for u in all_users
            if u.toggl_user_id and u.email and u.email.lower() not in excluded_emails
        ]
        
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


@cli.command()
@click.option("--year", type=int, help="Year (defaults to previous month)")
@click.option("--month", type=int, help="Month 1-12 (defaults to previous month)")
def send_admin_report(year: Optional[int], month: Optional[int]):
    """Send admin report to admins via Slack."""
    settings = load_settings()
    
    # Determine target month
    if not year or not month:
        today = date.today()
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        year, month = last_prev.year, last_prev.month
    
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
