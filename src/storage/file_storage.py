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
from ..models.report import MonthlyReport, ProjectReport, UserReport


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
        """Export monthly report to CSV."""
        if role == "user":
            file_path = self._get_user_file_path(report.user_email, report.year, report.month, "csv")
        else:
            file_path = self._get_role_file_path(role, report.year, report.month, "csv")
        
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
            writer.writerow(['Billable Hours', f"{report.billable_hours:.2f}"])
            writer.writerow(['Overtime Hours', f"{report.overtime_hours:.2f}"])
            writer.writerow([])
            
            # Absence summary
            writer.writerow(['Absence Summary'])
            writer.writerow(['Vacation Days', report.vacation_days])
            writer.writerow(['Sick Days', report.sick_days])
            writer.writerow(['Personal Days', report.personal_days])
            writer.writerow(['Other Absence Days', report.other_absence_days])
            writer.writerow([])
            
            # Project breakdown
            if report.project_hours:
                writer.writerow(['Project Breakdown'])
                writer.writerow(['Project', 'Hours'])
                for project, hours in report.project_hours.items():
                    writer.writerow([project, f"{hours:.2f}"])
        
        return file_path
    
    def export_project_report_csv(self, report: ProjectReport) -> Path:
        """Export project report to CSV."""
        file_path = self._get_role_file_path("project", report.year, report.month, "csv")
        
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Header
            writer.writerow(['Project Report'])
            writer.writerow(['Project', report.project_name])
            writer.writerow(['Project ID', report.project_id or 'N/A'])
            writer.writerow(['Period', report.period_string])
            writer.writerow(['Generated', report.generated_at.isoformat() if report.generated_at else ''])
            writer.writerow([])
            
            # Project statistics
            writer.writerow(['Project Statistics'])
            writer.writerow(['Total Hours', f"{report.total_hours:.2f}"])
            writer.writerow(['Total Users', report.total_users])
            writer.writerow(['Average Hours per User', f"{report.average_hours_per_user:.2f}"])
            if report.estimated_cost:
                writer.writerow(['Estimated Cost', f"${report.estimated_cost:.2f}"])
            if report.hourly_rate:
                writer.writerow(['Hourly Rate', f"${report.hourly_rate:.2f}"])
            writer.writerow([])
            
            # User breakdown
            if report.user_hours:
                writer.writerow(['User Breakdown'])
                writer.writerow(['User', 'Hours', 'Percentage'])
                total_hours = sum(report.user_hours.values())
                for user, hours in sorted(report.user_hours.items(), key=lambda x: x[1], reverse=True):
                    percentage = (hours / total_hours * 100) if total_hours > 0 else 0
                    writer.writerow([user, f"{hours:.2f}", f"{percentage:.1f}%"])
        
        return file_path
    
    def export_admin_report_csv(self, reports: List[UserReport], year: int, month: int) -> Path:
        """Export admin report (summary of all users) to CSV."""
        file_path = self._get_role_file_path("admin", year, month, "csv")
        
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
            total_billable = sum(r.billable_hours for r in reports)
            
            writer.writerow(['Summary Statistics'])
            writer.writerow(['Total Hours (All Users)', f"{total_hours:.2f}"])
            writer.writerow(['Total Overtime (All Users)', f"{total_overtime:.2f}"])
            writer.writerow(['Total Billable Hours (All Users)', f"{total_billable:.2f}"])
            writer.writerow(['Average Hours per User', f"{total_hours / len(reports):.2f}" if reports else "0.00"])
            writer.writerow([])
            
            # Individual user details
            writer.writerow(['User Details'])
            writer.writerow([
                'User', 'Email', 'Department', 'Total Hours', 'Billable Hours', 
                'Overtime', 'Vacation Days', 'Sick Days', 'Projects Count', 'Missing Days'
            ])
            
            for report in sorted(reports, key=lambda x: x.total_hours, reverse=True):
                writer.writerow([
                    report.user_name,
                    report.user_email,
                    report.department or 'N/A',
                    f"{report.total_hours:.2f}",
                    f"{report.billable_hours:.2f}",
                    f"{report.monthly_overtime:.2f}",
                    report.absence_breakdown.get('vacation', 0),
                    report.absence_breakdown.get('sick', 0),
                    len(report.projects_worked),
                    len(report.missing_days)
                ])
        
        return file_path
    
    def export_producer_report_csv(self, project_reports: List[ProjectReport], year: int, month: int) -> Path:
        """Export producer report (project-focused) to CSV."""
        file_path = self._get_role_file_path("producer", year, month, "csv")
        
        with open(file_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Header
            writer.writerow(['Producer Report - Projects'])
            writer.writerow(['Period', f"{year}-{month:02d}"])
            writer.writerow(['Generated', datetime.now().isoformat()])
            writer.writerow(['Total Projects', len(project_reports)])
            writer.writerow([])
            
            # Project summary
            total_hours = sum(r.total_hours for r in project_reports)
            total_users = sum(r.total_users for r in project_reports)
            
            writer.writerow(['Project Summary'])
            writer.writerow(['Total Hours (All Projects)', f"{total_hours:.2f}"])
            writer.writerow(['Total Users (All Projects)', total_users])
            writer.writerow(['Average Hours per Project', f"{total_hours / len(project_reports):.2f}" if project_reports else "0.00"])
            writer.writerow([])
            
            # Individual project details
            writer.writerow(['Project Details'])
            writer.writerow([
                'Project Name', 'Project ID', 'Total Hours', 'Total Users', 
                'Average Hours per User', 'Estimated Cost', 'Hourly Rate'
            ])
            
            for report in sorted(project_reports, key=lambda x: x.total_hours, reverse=True):
                writer.writerow([
                    report.project_name,
                    report.project_id or 'N/A',
                    f"{report.total_hours:.2f}",
                    report.total_users,
                    f"{report.average_hours_per_user:.2f}",
                    f"${report.estimated_cost:.2f}" if report.estimated_cost else 'N/A',
                    f"${report.hourly_rate:.2f}" if report.hourly_rate else 'N/A'
                ])
        
        return file_path
    
    # Utility methods
    def list_available_reports(self, year: int, month: int) -> Dict[str, List[Path]]:
        """List available report files for a given month."""
        month_dir = self._ensure_month_dir(year, month)
        
        reports = {
            'admin': [],
            'producer': [],
            'user': [],
            'project': [],
            'raw': []
        }
        
        for file_path in month_dir.glob("*.csv"):
            filename = file_path.name
            
            if filename.startswith("admin_"):
                reports['admin'].append(file_path)
            elif filename.startswith("producer_"):
                reports['producer'].append(file_path)
            elif filename.startswith("project_"):
                reports['project'].append(file_path)
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
