"""
File storage for exports and reports.
"""

import csv
import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime, date, timedelta
from pathlib import Path

from ..config import Settings
from ..models.user import User
from ..models.time_entry import TimeEntry
from ..models.absence import Absence
from ..models.report import MonthlyReport, UserReport


class FileStorage:
    """File storage for exports and reports."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.exports_dir = Path(settings.exports_dir)
        self.exports_dir.mkdir(parents=True, exist_ok=True)
    
    def _ensure_month_dir(self, year: int, month: int) -> Path:
        """Ensure month directory exists and return path."""
        month_dir = self.exports_dir / f"{year:04d}-{month:02d}"
        month_dir.mkdir(parents=True, exist_ok=True)
        return month_dir
    
    def _get_role_file_path(self, role: str, year: int, month: int, file_type: str = "csv") -> Path:
        """Get file path for role-based report."""
        month_dir = self._ensure_month_dir(year, month)
        return month_dir / f"{role}_{year:04d}-{month:02d}.{file_type}"
    
    def _get_user_file_path(self, user_email: str, year: int, month: int, file_type: str = "csv") -> Path:
        """Get file path for user-specific report."""
        month_dir = self._ensure_month_dir(year, month)
        # Sanitize email for filename
        safe_email = user_email.replace('@', '_at_').replace('.', '_')
        return month_dir / f"user_{safe_email}_{year:04d}-{month:02d}.{file_type}"
    
    # JSON exports (raw data backup)
    def export_raw_data(
        self, 
        time_entries: List[TimeEntry], 
        absences: List[Absence], 
        year: int, 
        month: int,
        prefix: str = "raw"
    ) -> Path:
        """Export raw data to JSON file."""
        month_dir = self._ensure_month_dir(year, month)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        filename = f"{prefix}_{year:04d}-{month:02d}_{timestamp}.json"
        file_path = month_dir / filename
        
        data = {
            'export_info': {
                'timestamp': datetime.now().isoformat(),
                'year': year,
                'month': month,
                'time_entries_count': len(time_entries),
                'absences_count': len(absences)
            },
            'time_entries': [entry.to_dict() for entry in time_entries],
            'absences': [absence.to_dict() for absence in absences]
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        
        return file_path
    
    # CSV exports for reports
    def export_monthly_report_csv(self, report: MonthlyReport, role: str = "user") -> Path:
        """Export simplified monthly report to CSV."""
        if role == "user":
            file_path = self._get_user_file_path(report.user_email, report.year, report.month, "csv")
        else:
            file_path = self._get_role_file_path(role, report.year, report.month, "csv")
        
        # Remove existing file if it exists to allow overwriting (handles permission issues)
        if file_path.exists():
            try:
                # Try to make file writable and remove it
                os.chmod(file_path, 0o666)  # Make writable
                file_path.unlink()  # Remove file
            except (PermissionError, OSError) as e:
                # If file is open in another program, try to continue anyway
                # The 'w' mode should still work if file becomes available
                pass
        
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Header
            writer.writerow(['Monthly Report'])
            writer.writerow(['User', report.user_name])
            writer.writerow(['Email', report.user_email])
            writer.writerow(['Period', report.period_string])
            writer.writerow(['Generated', report.generated_at.isoformat() if report.generated_at else ''])
            writer.writerow([])

            # Time tracking summary
            writer.writerow(['Time Tracking Summary'])
            writer.writerow(['Total Hours', f"{report.total_hours:.2f}"])
            writer.writerow(['Overtime Hours', f"{report.overtime_hours:.2f}"])
            writer.writerow(['Total Absence Days', f"{report.total_absence_days:.2f}"])
            writer.writerow([])

        return file_path

    def export_user_report_csv(self, report: UserReport) -> Path:
        """Export user report (weekly or monthly) to CSV."""
        file_path = self._get_user_file_path(report.user_email, report.year, report.month, "csv")
        
        # Remove existing file if it exists to allow overwriting (handles permission issues)
        if file_path.exists():
            try:
                # Try to make file writable and remove it
                os.chmod(file_path, 0o666)  # Make writable
                file_path.unlink()  # Remove file
            except (PermissionError, OSError) as e:
                # If file is open in another program, try to continue anyway
                # The 'w' mode should still work if file becomes available
                pass
        
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([f"{report.report_type.title()} User Report"])
            writer.writerow(['User', report.user_name])
            writer.writerow(['Email', report.user_email])
            writer.writerow(['Department', report.department or 'N/A'])
            writer.writerow(['Period', report.period_string])
            writer.writerow(['Generated', report.generated_at.isoformat() if report.generated_at else ''])
            writer.writerow([])
            writer.writerow(['Totals'])
            writer.writerow(['Total Hours', f"{report.total_hours:.2f}"])
            writer.writerow(['Weekly Overtime', f"{report.weekly_overtime:.2f}"])
            writer.writerow(['Monthly Overtime', f"{report.monthly_overtime:.2f}"])
            writer.writerow([])
            if report.projects_worked:
                writer.writerow(['Projects Worked'])
                for project in report.projects_worked:
                    writer.writerow([project])
                writer.writerow([])
            if report.missing_days:
                writer.writerow(['Missing Days'])
                for missing_day in report.missing_days:
                    writer.writerow([missing_day.isoformat()])
                writer.writerow([])
            
            # Daily Overtime Breakdown
            if report.daily_breakdown:
                writer.writerow(['Daily Overtime Breakdown'])
                writer.writerow([
                    'Date', 'Type', 'Toggl Hours', 'Total Hours', 'Expected Hours', 'OT Hours',
                    'Project', 'Project ID', 'Project Hours', 'Task', 'Task ID', 'Task Hours'
                ])
                
                for day_entry in report.daily_breakdown:
                    date_str = day_entry.get('date')
                    if isinstance(date_str, date):
                        date_str = date_str.isoformat()
                    elif isinstance(date_str, str):
                        # Try to parse and format if needed
                        try:
                            date_obj = datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
                            date_str = date_obj.isoformat()
                        except:
                            pass
                    
                    entry_type = day_entry.get('type', '')
                    toggl_hours = day_entry.get('toggl_hours', 0.0)
                    total_hours = day_entry.get('total_hours', 0.0)
                    expected_hours = day_entry.get('expected_hours', 0.0)
                    ot_hours = day_entry.get('hours', 0.0)
                    
                    projects = day_entry.get('projects', [])
                    
                    if projects:
                        # Calculate project hours (sum of all tasks for each project)
                        project_hours_map = {}
                        for project in projects:
                            project_id = project.get('project_id')
                            if project_id not in project_hours_map:
                                project_hours_map[project_id] = 0.0
                            project_hours_map[project_id] += project.get('hours', 0.0)
                        
                        # Write one row per project/task
                        for project in projects:
                            project_id = project.get('project_id')
                            project_hours_total = project_hours_map.get(project_id, 0.0)
                            task_hours = project.get('hours', 0.0)
                            
                            writer.writerow([
                                date_str,
                                entry_type,
                                f"{toggl_hours:.2f}",
                                f"{total_hours:.2f}",
                                f"{expected_hours:.2f}" if expected_hours > 0 else '',
                                f"{ot_hours:.2f}",
                                project.get('project_name', ''),
                                project_id if project_id is not None else '',
                                f"{project_hours_total:.2f}",
                                project.get('task_name', ''),
                                project.get('task_id') if project.get('task_id') is not None else '',
                                f"{task_hours:.2f}"
                            ])
                    else:
                        # No projects - write single row
                        writer.writerow([
                            date_str,
                            entry_type,
                            f"{toggl_hours:.2f}",
                            f"{total_hours:.2f}",
                            f"{expected_hours:.2f}" if expected_hours > 0 else '',
                            f"{ot_hours:.2f}",
                            '', '', '', '', '', ''
                        ])
                
                writer.writerow([])
        
        return file_path
    
    def export_admin_report_csv(self, reports: List[UserReport], year: int, month: int) -> Path:
        """Export admin report (summary of all users) to CSV."""
        file_path = self._get_role_file_path("admin", year, month, "csv")
        
        # Remove existing file if it exists to allow overwriting (handles permission issues)
        if file_path.exists():
            try:
                # Try to make file writable and remove it
                os.chmod(file_path, 0o666)  # Make writable
                file_path.unlink()  # Remove file
            except (PermissionError, OSError) as e:
                # If file is open in another program, try to continue anyway
                # The 'w' mode should still work if file becomes available
                pass
        
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Header
            writer.writerow(['Admin Report - All Users'])
            writer.writerow(['Period', f"{year}-{month:02d}"])
            writer.writerow(['Generated', datetime.now().isoformat()])
            writer.writerow(['Total Users', len(reports)])
            writer.writerow([])
            
            # Summary statistics
            total_hours = sum(r.total_hours for r in reports)
            total_overtime = sum(r.monthly_overtime for r in reports)
            
            writer.writerow(['Summary Statistics'])
            writer.writerow(['Total Hours (All Users)', f"{total_hours:.2f}"])
            writer.writerow(['Total Overtime (All Users)', f"{total_overtime:.2f}"])
            writer.writerow(['Average Hours per User', f"{total_hours / len(reports):.2f}" if reports else "0.00"])
            writer.writerow([])
            
            # Individual user details
            writer.writerow(['User Details'])
            writer.writerow([
                'User', 'Email', 'Department', 'Report Type', 'Period Label',
                'Total Hours', 'Weekly Overtime', 'Monthly Overtime',
                'Projects Count', 'Missing Days'
            ])
            
            for report in sorted(reports, key=lambda x: x.total_hours, reverse=True):
                writer.writerow([
                    report.user_name,
                    report.user_email,
                    report.department or 'N/A',
                    report.report_type,
                    report.period_label,
                    f"{report.total_hours:.2f}",
                    f"{report.weekly_overtime:.2f}",
                    f"{report.monthly_overtime:.2f}",
                    len(report.projects_worked),
                    len(report.missing_days)
                ])
        
        return file_path
    
    # Utility methods
    def list_available_reports(self, year: int, month: int) -> Dict[str, List[Path]]:
        """List available report files for a given month."""
        month_dir = self._ensure_month_dir(year, month)
        
        reports = {
            'admin': [],
            'user': [],
            'raw': []
        }
        
        for file_path in month_dir.glob("*.csv"):
            filename = file_path.name
            
            if filename.startswith("admin_"):
                reports['admin'].append(file_path)
            elif filename.startswith("user_"):
                reports['user'].append(file_path)
        
        for file_path in month_dir.glob("*.json"):
            filename = file_path.name
            if filename.startswith("raw_"):
                reports['raw'].append(file_path)
        
        return reports
    
    def get_report_file_info(self, file_path: Path) -> Dict[str, Any]:
        """Get information about a report file."""
        try:
            stat = file_path.stat()
            return {
                'path': str(file_path),
                'size_bytes': stat.st_size,
                'size_mb': stat.st_size / (1024 * 1024),
                'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'exists': True
            }
        except FileNotFoundError:
            return {
                'path': str(file_path),
                'exists': False
            }
    
    def cleanup_old_reports(self, months_to_keep: int = 12):
        """Clean up old report files."""
        cutoff_date = datetime.now() - timedelta(days=months_to_keep * 30)
        
        deleted_count = 0
        for month_dir in self.exports_dir.iterdir():
            if not month_dir.is_dir():
                continue
            
            try:
                # Extract year-month from directory name
                year_month = month_dir.name
                if '-' in year_month and len(year_month.split('-')) == 2:
                    year_str, month_str = year_month.split('-')
                    year = int(year_str)
                    month = int(month_str)
                    
                    # Check if this month is older than cutoff
                    month_date = datetime(year, month, 1)
                    if month_date < cutoff_date:
                        # Delete the entire month directory
                        import shutil
                        shutil.rmtree(month_dir)
                        deleted_count += 1
                        print(f"Deleted old reports: {month_dir}")
            except (ValueError, OSError) as e:
                print(f"Error processing directory {month_dir}: {e}")
        
        print(f"Cleanup completed: {deleted_count} month directories deleted")
        return deleted_count
