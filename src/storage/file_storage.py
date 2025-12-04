"""
File storage for exports and reports.
"""

import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime, date, timedelta
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

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
    
    def export_user_report_xlsx(self, report: UserReport) -> Path:
        """Export user report (weekly or monthly) to XLSX with formatting."""
        file_path = self._get_user_file_path(report.user_email, report.year, report.month, "xlsx")
        
        # Remove existing file if it exists to allow overwriting
        if file_path.exists():
            try:
                os.chmod(file_path, 0o666)
                file_path.unlink()
            except (PermissionError, OSError):
                pass
        
        # Create workbook and worksheet
        wb = Workbook()
        ws = wb.active
        ws.title = f"{report.report_type.title()} Report"
        
        # Define styles
        header_font = Font(bold=True, size=12, color="FFFFFF")
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        title_font = Font(bold=True, size=14)
        section_font = Font(bold=True, size=11)
        center_align = Alignment(horizontal="center", vertical="center")
        left_align = Alignment(horizontal="left", vertical="center")
        right_align = Alignment(horizontal="right", vertical="center")
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        row = 1
        
        # Title
        ws.merge_cells(f'A{row}:L{row}')
        title_cell = ws[f'A{row}']
        title_cell.value = f"{report.report_type.title()} User Report"
        title_cell.font = title_font
        title_cell.alignment = center_align
        row += 1
        
        # User info
        ws[f'A{row}'] = 'User:'
        ws[f'B{row}'] = report.user_name
        row += 1
        ws[f'A{row}'] = 'Email:'
        ws[f'B{row}'] = report.user_email
        row += 1
        ws[f'A{row}'] = 'Department:'
        ws[f'B{row}'] = report.department or 'N/A'
        row += 1
        ws[f'A{row}'] = 'Period:'
        ws[f'B{row}'] = report.period_string
        row += 1
        ws[f'A{row}'] = 'Generated:'
        ws[f'B{row}'] = report.generated_at.strftime("%Y-%m-%d %H:%M:%S") if report.generated_at else ''
        row += 2
        
        # Totals section
        ws[f'A{row}'] = 'Totals'
        ws[f'A{row}'].font = section_font
        row += 1
        
        ws[f'A{row}'] = 'Total Hours'
        ws[f'B{row}'] = report.total_hours
        ws[f'B{row}'].number_format = '0.00'
        ws[f'B{row}'].alignment = right_align
        row += 1
        
        ws[f'A{row}'] = 'Weekly Overtime'
        ws[f'B{row}'] = report.weekly_overtime
        ws[f'B{row}'].number_format = '0.00'
        ws[f'B{row}'].alignment = right_align
        row += 1
        
        ws[f'A{row}'] = 'Monthly Overtime'
        ws[f'B{row}'] = report.monthly_overtime
        ws[f'B{row}'].number_format = '0.00'
        ws[f'B{row}'].alignment = right_align
        row += 2
        
        # Projects Worked section
        if report.projects_worked:
            ws[f'A{row}'] = 'Projects Worked'
            ws[f'A{row}'].font = section_font
            row += 1
            for project in report.projects_worked:
                ws[f'A{row}'] = project
                row += 1
            row += 1
        
        # Missing Days section
        if report.missing_days:
            ws[f'A{row}'] = 'Missing Days'
            ws[f'A{row}'].font = section_font
            row += 1
            for missing_day in report.missing_days:
                ws[f'A{row}'] = missing_day.isoformat()
                row += 1
            row += 1
        
        # Daily Overtime Breakdown table
        if report.daily_breakdown:
            ws[f'A{row}'] = 'Daily Overtime Breakdown'
            ws[f'A{row}'].font = section_font
            row += 1
            
            headers = [
                'Date', 'Type', 'Toggl Hours', 'Total Hours', 'Expected Hours', 'OT Hours',
                'Project', 'Project ID', 'Project Hours', 'Task', 'Task ID', 'Task Hours'
            ]
            
            breakdown_header_row = row
            for col_idx, header in enumerate(headers, start=1):
                cell = ws.cell(row=row, column=col_idx)
                cell.value = header
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = center_align
                cell.border = thin_border
            row += 1
            
            for day_entry in report.daily_breakdown:
                date_str = day_entry.get('date')
                if isinstance(date_str, date):
                    date_str = date_str.isoformat()
                elif isinstance(date_str, str):
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
                        
                        data_row = [
                            date_str,
                            entry_type,
                            toggl_hours,
                            total_hours,
                            expected_hours if expected_hours > 0 else None,
                            ot_hours,
                            project.get('project_name', ''),
                            project_id if project_id is not None else '',
                            project_hours_total,
                            project.get('task_name', ''),
                            project.get('task_id') if project.get('task_id') is not None else '',
                            task_hours
                        ]
                        
                        for col_idx, value in enumerate(data_row, start=1):
                            cell = ws.cell(row=row, column=col_idx)
                            cell.value = value
                            cell.border = thin_border
                            
                            # Format numbers
                            if col_idx in [3, 4, 5, 6, 9, 12]:  # Numeric columns
                                if value is not None:
                                    cell.number_format = '0.00'
                                    cell.alignment = right_align
                                else:
                                    cell.alignment = right_align
                            elif col_idx == 2:  # Type
                                cell.alignment = center_align
                            else:
                                cell.alignment = left_align
                        
                        row += 1
                else:
                    # No projects - write single row
                    data_row = [
                        date_str,
                        entry_type,
                        toggl_hours,
                        total_hours,
                        expected_hours if expected_hours > 0 else None,
                        ot_hours,
                        '', '', '', '', '', ''
                    ]
                    
                    for col_idx, value in enumerate(data_row, start=1):
                        cell = ws.cell(row=row, column=col_idx)
                        cell.value = value
                        cell.border = thin_border
                        
                        # Format numbers
                        if col_idx in [3, 4, 5, 6]:  # Numeric columns
                            if value is not None:
                                cell.number_format = '0.00'
                                cell.alignment = right_align
                            else:
                                cell.alignment = right_align
                        elif col_idx == 2:  # Type
                            cell.alignment = center_align
                        else:
                            cell.alignment = left_align
                    
                    row += 1
        
        # Set column widths (increased by 30% from reasonable defaults)
        ws.column_dimensions['A'].width = 13.0  # Date (10 * 1.3)
        ws.column_dimensions['B'].width = 10.4  # Type (8 * 1.3)
        ws.column_dimensions['C'].width = 13.0  # Toggl Hours (10 * 1.3)
        ws.column_dimensions['D'].width = 13.0  # Total Hours (10 * 1.3)
        ws.column_dimensions['E'].width = 15.6  # Expected Hours (12 * 1.3)
        ws.column_dimensions['F'].width = 11.7  # OT Hours (9 * 1.3)
        ws.column_dimensions['G'].width = 26.0  # Project (20 * 1.3)
        ws.column_dimensions['H'].width = 13.0  # Project ID (10 * 1.3)
        ws.column_dimensions['I'].width = 15.6  # Project Hours (12 * 1.3)
        ws.column_dimensions['J'].width = 26.0  # Task (20 * 1.3)
        ws.column_dimensions['K'].width = 13.0  # Task ID (10 * 1.3)
        ws.column_dimensions['L'].width = 13.0  # Task Hours (10 * 1.3)
        
        # Freeze header row for breakdown table if it exists
        if report.daily_breakdown:
            ws.freeze_panes = f'A{breakdown_header_row + 1}'
        
        # Save workbook
        wb.save(file_path)
        
        return file_path
    
    def export_admin_report_xlsx(self, reports: List[UserReport], year: int, month: int) -> Path:
        """Export admin report (summary of all users) to XLSX with formatting."""
        file_path = self._get_role_file_path("admin", year, month, "xlsx")
        
        # Remove existing file if it exists to allow overwriting
        if file_path.exists():
            try:
                os.chmod(file_path, 0o666)
                file_path.unlink()
            except (PermissionError, OSError):
                pass
        
        # Create workbook and worksheet
        wb = Workbook()
        ws = wb.active
        ws.title = "Admin Report"
        
        # Define styles
        header_font = Font(bold=True, size=12, color="FFFFFF")
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        title_font = Font(bold=True, size=14)
        summary_font = Font(bold=True, size=11)
        center_align = Alignment(horizontal="center", vertical="center")
        left_align = Alignment(horizontal="left", vertical="center")
        right_align = Alignment(horizontal="right", vertical="center")
        thin_border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        row = 1
        
        # Title
        ws.merge_cells(f'A{row}:H{row}')
        title_cell = ws[f'A{row}']
        title_cell.value = 'Admin Report - All Users'
        title_cell.font = title_font
        title_cell.alignment = center_align
        row += 1
        
        # Period and metadata
        ws[f'A{row}'] = 'Period:'
        ws[f'B{row}'] = f"{year}-{month:02d}"
        row += 1
        ws[f'A{row}'] = 'Generated:'
        ws[f'B{row}'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row += 1
        ws[f'A{row}'] = 'Total Users:'
        ws[f'B{row}'] = len(reports)
        row += 2
        
        # Summary statistics - traktuj ujemne overtime jako 0
        total_hours = sum(r.total_hours for r in reports)
        total_overtime = sum(max(0.0, r.monthly_overtime) for r in reports)
        total_weekend_overtime = sum(max(0.0, r.weekend_overtime) for r in reports)
        
        ws[f'A{row}'] = 'Summary Statistics'
        ws[f'A{row}'].font = summary_font
        row += 1
        
        ws[f'A{row}'] = 'Total Hours (All Users)'
        ws[f'B{row}'] = total_hours
        ws[f'B{row}'].number_format = '0.00'
        ws[f'B{row}'].alignment = right_align
        row += 1
        
        ws[f'A{row}'] = 'Total Overtime (All Users)'
        ws[f'B{row}'] = total_overtime
        ws[f'B{row}'].number_format = '0.00'
        ws[f'B{row}'].alignment = right_align
        row += 1
        
        ws[f'A{row}'] = 'Total Weekend Overtime (All Users)'
        ws[f'B{row}'] = total_weekend_overtime
        ws[f'B{row}'].number_format = '0.00'
        ws[f'B{row}'].alignment = right_align
        row += 2
        
        # User Details Table Header
        headers = [
            'User', 'Department', 'Period Label',
            'Total Hours', 'Expected Hours', 'Monthly Overtime', 'Weekend Overtime', 'Missing Time Entries'
        ]
        
        header_row = row
        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=row, column=col_idx)
            cell.value = header
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center_align
            cell.border = thin_border
        row += 1
        
        # User Details Data
        sorted_reports = sorted(reports, key=lambda x: x.total_hours, reverse=True)
        for report in sorted_reports:
            # Traktuj ujemne overtime jako 0
            monthly_ot = max(0.0, report.monthly_overtime)
            weekend_ot = max(0.0, report.weekend_overtime)
            
            data_row = [
                report.user_name,
                report.department or 'N/A',
                report.period_label,
                report.total_hours,
                report.expected_hours,
                monthly_ot,
                weekend_ot,
                len(report.missing_days)
            ]
            
            for col_idx, value in enumerate(data_row, start=1):
                cell = ws.cell(row=row, column=col_idx)
                cell.value = value
                cell.border = thin_border
                
                # Format numbers
                if col_idx in [4, 5, 6, 7]:  # Total Hours, Expected Hours, Monthly Overtime, Weekend Overtime
                    cell.number_format = '0.00'
                    cell.alignment = right_align
                elif col_idx == 8:  # Missing Days
                    cell.alignment = center_align
                else:
                    cell.alignment = left_align
            
            row += 1
        
        # Set column widths for better readability (increased by 30%)
        ws.column_dimensions['A'].width = 32.5  # User (25 * 1.3)
        ws.column_dimensions['B'].width = 26.0  # Department (20 * 1.3)
        ws.column_dimensions['C'].width = 15.6  # Period Label (12 * 1.3)
        ws.column_dimensions['D'].width = 15.6  # Total Hours (12 * 1.3)
        ws.column_dimensions['E'].width = 18.2  # Expected Hours (14 * 1.3)
        ws.column_dimensions['F'].width = 20.8  # Monthly Overtime (16 * 1.3)
        ws.column_dimensions['G'].width = 23.4  # Weekend Overtime (18 * 1.3)
        ws.column_dimensions['H'].width = 19.5  # Missing Time Entries (15 * 1.3, zwiększone dla lepszej czytelności)
        
        # Freeze header row
        ws.freeze_panes = f'A{header_row + 1}'
        
        # Save workbook
        wb.save(file_path)
        
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
