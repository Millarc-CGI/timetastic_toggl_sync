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
from .logic import DataAggregator, OvertimeCalculator, StatisticsGenerator, ReportGenerator
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


@cli.command()
@click.option("--start", required=True, help="Start date (YYYY-MM-DD)")
@click.option("--end", required=True, help="End date (YYYY-MM-DD)")
def sync(start: str, end: str):
    """Sync data from Toggl and Timetastic for the specified date range."""
    settings = load_settings()
    
    try:
        start_date = datetime.strptime(start, "%Y-%m-%d").date()
        end_date = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError:
        print("❌ Invalid date format. Use YYYY-MM-DD")
        return
    
    print(f"🔄 Starting sync for {start_date} to {end_date}...")
    
    # Initialize services
    toggl_service = TogglService(settings)
    timetastic_service = TimetasticService(settings)
    storage = SQLiteStorage(settings)
    
    # Start sync log
    log_id = storage.log_sync_start("manual_sync")
    
    try:
        # Convert dates to ISO format for APIs
        start_iso = f"{start_date}T00:00:00Z"
        end_iso = f"{end_date}T23:59:59Z"
        
        # Fetch time entries
        print("📊 Fetching time entries from Toggl...")
        time_entries = toggl_service.get_time_entries(start_iso, end_iso)
        print(f"   ✅ Found {len(time_entries)} time entries")
        
        # Fetch absences
        print("🏖️ Fetching absences from Timetastic...")
        absences = timetastic_service.get_holidays(start_iso, end_iso)
        print(f"   ✅ Found {len(absences)} absences")
        
        # Save to storage
        print("💾 Saving data to database...")
        storage.save_time_entries(time_entries)
        storage.save_absences(absences)
        
        # Log success
        storage.log_sync_end(log_id, "success", len(time_entries) + len(absences))
        
        print("✅ Sync completed successfully!")
        
    except Exception as e:
        storage.log_sync_end(log_id, "error", 0, [str(e)])
        print(f"❌ Sync failed: {e}")
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
@click.option("--user", help="Generate report for specific user email")
@click.option("--role", type=click.Choice(['admin', 'producer', 'user']), help="Generate report for specific role")
def report_monthly(year: Optional[int], month: Optional[int], user: Optional[str], role: Optional[str]):
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
        # Initialize services
        storage = SQLiteStorage(settings)
        file_storage = FileStorage(settings)
        aggregator = DataAggregator(settings)
        overtime_calc = OvertimeCalculator(settings)
        report_gen = ReportGenerator(settings)
        stats_gen = StatisticsGenerator(settings)
        
        # Get date range
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)
        
        # Get users
        users = storage.get_all_users()
        if not users:
            print("❌ No users found. Run 'sync-users' first.")
            return
        
        # Get data
        time_entries = storage.get_time_entries_for_period(start_date, end_date)
        absences = []
        for user in users:
            user_absences = storage.get_absences_for_user(user.email, start_date, end_date)
            absences.extend(user_absences)
        
        # Aggregate data for all users
        all_user_data = {}
        for user in users:
            user_entries = [e for e in time_entries if e.user_email and e.user_email.lower() == user.email.lower()]
            user_absences = [a for a in absences if a.user_email and a.user_email.lower() == user.email.lower()]
            
            user_data = aggregator.aggregate_monthly(user.email, year, month, user_entries, user_absences)
            all_user_data[user.email.lower()] = user_data
        
        # Generate reports based on parameters
        if user:
            # Generate report for specific user
            user_email = user.lower()
            if user_email in all_user_data:
                user_data = all_user_data[user_email]
                user_obj = next((u for u in users if u.email.lower() == user_email), None)
                
                if user_obj:
                    # Generate overtime data
                    overtime_data = overtime_calc.calculate_user_overtime(user_obj.email, year, month, user_data['daily_data'])
                    
                    # Generate user report
                    user_report = report_gen.generate_monthly_user_report(
                        user_obj.email,
                        user_obj.display_name,
                        year,
                        month,
                        user_data,
                        overtime_data,
                        department=user_obj.department
                    )
                    
                    # Export to CSV
                    csv_file = file_storage.export_user_report_csv(user_report)
                    print(f"✅ User report exported to: {csv_file}")
                    
                    # Send Slack notification if enabled
                    if settings.send_monthly_reports:
                        slack_service = SlackService(settings)
                        slack_service.send_monthly_report(user_obj.email, user_report.to_dict())
                        print(f"📤 Monthly report sent to {user_obj.display_name}")
            else:
                print(f"❌ User {user} not found or has no data for this period")
        
        elif role:
            # Generate report for specific role
            if role == "admin":
                admin_reports = report_gen.generate_admin_report(users, all_user_data, year, month)
                csv_file = file_storage.export_admin_report_csv(admin_reports, year, month)
                print(f"✅ Admin report exported to: {csv_file}")
                
            elif role == "producer":
                project_stats = stats_gen.generate_project_stats(all_user_data, users)
                producer_reports = report_gen.generate_producer_report(project_stats, year, month)
                csv_file = file_storage.export_producer_report_csv(producer_reports, year, month)
                print(f"✅ Producer report exported to: {csv_file}")
        
        else:
            # Generate all reports
            print("📊 Generating all report types...")
            
            # Admin report
            admin_reports = report_gen.generate_admin_report(users, all_user_data, year, month)
            admin_csv = file_storage.export_admin_report_csv(admin_reports, year, month)
            print(f"   ✅ Admin report: {admin_csv}")
            
            # Producer report
            project_stats = stats_gen.generate_project_stats(all_user_data, users)
            producer_reports = report_gen.generate_producer_report(project_stats, year, month)
            producer_csv = file_storage.export_producer_report_csv(producer_reports, year, month)
            print(f"   ✅ Producer report: {producer_csv}")
            
            # Individual user reports
            for user_obj in users:
                user_email = user_obj.email.lower()
                if user_email in all_user_data:
                    user_data = all_user_data[user_email]
                    overtime_data = overtime_calc.calculate_user_overtime(user_obj.email, year, month, user_data['daily_data'])
                    
                    user_report = report_gen.generate_monthly_user_report(
                        user_obj.email,
                        user_obj.display_name,
                        year,
                        month,
                        user_data,
                        overtime_data,
                        department=user_obj.department
                    )
                    
                    csv_file = file_storage.export_user_report_csv(user_report)
                    print(f"   ✅ User report for {user_obj.display_name}: {csv_file}")
            
            print(f"✅ Generated all reports for {year}-{month:02d}")
        
    except Exception as e:
        print(f"❌ Report generation failed: {e}")
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
