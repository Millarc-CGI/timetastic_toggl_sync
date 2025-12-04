"""
Report generator for creating various types of reports.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, date

from ..config import Settings
from ..models.user import User
from ..models.report import MonthlyReport, UserReport


class ReportGenerator:
    """Generates various types of reports."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
    
    def generate_user_report(
        self,
        user_email: str,
        user_name: str,
        year: int,
        month: int,
        user_data: Dict[str, Any],
        overtime_data: Dict[str, Any],
        report_type: str = "monthly",
        period_label: Optional[str] = None,
        department: Optional[str] = None
    ) -> UserReport:
        """Generate detailed report for a specific user."""
        
        project_hours = user_data.get('project_hours', {})
        project_tasks = {
            project: dict(tasks)
            for project, tasks in (user_data.get('project_task_hours') or {}).items()
        }
        missing_days = user_data.get('missing_days', [])
        no_project_entries_count = user_data.get('no_project_entries_count', 0)
        
        if not period_label and year and month:
            period_label = f"{year}-{month:02d}"
        
        return UserReport(
            user_email=user_email,
            user_name=user_name,
            department=department,
            year=year,
            month=month,
            report_type=report_type,
            period_label=period_label,
            total_hours=user_data.get('total_hours', 0),
            weekly_overtime=overtime_data.get('weekly_overtime', 0),
            monthly_overtime=overtime_data.get('monthly_overtime', 0),
            projects_worked=list(project_hours.keys()),
            project_tasks=project_tasks,
            missing_days=missing_days,
            no_project_entries_count=no_project_entries_count,
            generated_at=datetime.now()
        )

    def generate_weekly_user_report(
        self,
        user_email: str,
        user_name: str,
        week_start: date,
        week_end: date,
        user_data: Dict[str, Any],
        overtime_data: Dict[str, Any],
        department: Optional[str] = None
    ) -> UserReport:
        """Generate a weekly report for a user."""
        period_label = f"{week_start.strftime('%Y-%m-%d')} to {week_end.strftime('%Y-%m-%d')}"
        return self.generate_user_report(
            user_email,
            user_name,
            year=week_start.year,
            month=week_start.month,
            user_data=user_data,
            overtime_data=overtime_data,
            report_type="weekly",
            period_label=period_label,
            department=department
        )

    def generate_monthly_user_report(
        self,
        user_email: str,
        user_name: str,
        year: int,
        month: int,
        user_data: Dict[str, Any],
        overtime_data: Dict[str, Any],
        department: Optional[str] = None
    ) -> UserReport:
        """Generate a monthly report for a user."""
        return self.generate_user_report(
            user_email,
            user_name,
            year,
            month,
            user_data,
            overtime_data,
            report_type="monthly",
            period_label=f"{year}-{month:02d}",
            department=department
        )
    
    def generate_monthly_report(
        self,
        user_email: str,
        user_name: str,
        year: int,
        month: int,
        user_data: Dict[str, Any]
    ) -> MonthlyReport:
        """Generate monthly report for a user."""
        
        absence_breakdown = user_data.get('absence_breakdown', {})
        total_absence_days = sum(absence_breakdown.values())
        
        return MonthlyReport(
            user_email=user_email,
            user_name=user_name,
            year=year,
            month=month,
            total_hours=user_data.get('total_hours', 0),
            overtime_hours=0,
            total_absence_days=total_absence_days,
            generated_at=datetime.now()
        )
    
    def generate_admin_report(
        self,
        users: List[User],
        all_user_data: Dict[str, Dict[str, Any]],
        year: int,
        month: int
    ) -> List[UserReport]:
        """Generate comprehensive admin report for all users."""
        
        reports = []
        
        for user in users:
            user_email = user.email.lower()
            user_data = all_user_data.get(user_email, {})
            
            if not user_data:
                continue
            
            # Generate user report
            report = self.generate_monthly_user_report(
                user_email=user.email,
                user_name=user.display_name,
                year=year,
                month=month,
                user_data=user_data,
                overtime_data={},  # Would need overtime calculation
                department=user.department
            )
            
            reports.append(report)
        
        return reports
    
    def format_user_report_summary(self, report: UserReport) -> str:
        """Format user report as a summary string."""
        
        lines = []
        lines.append(f"📊 {report.report_type.title()} Report - {report.user_name}")
        lines.append(f"📧 Email: {report.user_email}")
        lines.append(f"📅 Period: {report.period_string}")
        lines.append("")
        
        lines.append("⏰ Time Tracking:")
        lines.append(f"  • Total Hours: {report.total_hours:.1f}h")
        lines.append("")
        
        show_weekly = report.report_type != "monthly" and report.weekly_overtime
        show_monthly = report.report_type != "weekly" and report.monthly_overtime
        if show_weekly or show_monthly:
            lines.append("⏱️ Overtime:")
            if show_weekly:
                lines.append(f"  • Weekly Overtime: {report.weekly_overtime:.1f}h")
            if show_monthly:
                lines.append(f"  • Monthly Overtime: {report.monthly_overtime:.1f}h")
            lines.append("")
        
        if report.projects_worked:
            lines.append("📁 Projects Worked On:")
            task_map = report.project_tasks or {}
            for project in report.projects_worked:
                lines.append(f"  • {project}")
                tasks = task_map.get(project, {})
                if tasks:
                    for task_name, hours in sorted(tasks.items(), key=lambda x: x[0]):
                        lines.append(f"      - {task_name}: {hours:.1f}h")
            lines.append("")
        
        if report.has_missing_entries:
            lines.append("⚠️ Missing Entries:")
            lines.append(f"  • Missing Entries (Days): {len(report.missing_days)}")
            for missing_day in report.missing_days[:5]:  # Show first 5
                lines.append(f"  • {missing_day.strftime('%Y-%m-%d (%A)')}")
            if len(report.missing_days) > 5:
                lines.append(f"  • ... and {len(report.missing_days) - 5} more")
            lines.append("")
            if report.report_type in {"weekly", "monthly"}:
                scope = "this past week" if report.report_type == "weekly" else "last month"
                lines.append(f"⚠️ Please update Toggl for the missing days above so we can close {scope} on time.")
                lines.append("")
        
        # Reminder about entries without project
        if report.has_no_project_entries:
            lines.append("⚠️ Entries Without Project:")
            lines.append(f"  • Found {report.no_project_entries_count} time entry/entries without assigned project")
            lines.append("")
            if report.report_type in {"weekly", "monthly"}:
                lines.append("⚠️ Please assign projects to your time entries so we can properly track project work.")
                lines.append("")
        
        return "\n".join(lines)

    def format_overtime_debug(self, overtime_data: Dict[str, Any]) -> str:
        """Debug string for overtime snapshot to aid troubleshooting."""
        if not overtime_data:
            return "No overtime data available."
        lines = []
        monthly_total = overtime_data.get("monthly_total_hours", 0.0)
        monthly_expected = overtime_data.get("monthly_expected_hours", 0.0)
        monthly_overtime = overtime_data.get('monthly_overtime', 0.0)
        lines.append(
            f"   - monthly: worked={monthly_total:.2f}h expected={monthly_expected:.2f}h "
            f"overtime={monthly_overtime:.2f}h"
        )
        lines.append(f"   - daily overtime total: {monthly_overtime:.2f}h")
        lines.append(f"   - weekend overtime: {overtime_data.get('weekend_overtime', 0.0):.2f}h")
        return "\n".join(lines)
    
    def format_overtime_table(self, daily_data: List[Dict[str, Any]], overtime_data: Dict[str, Any]) -> str:
        """Format detailed overtime table with daily breakdown, weekly and monthly totals."""
        lines = []
        
        # Get daily breakdown from overtime_data
        daily_breakdown = overtime_data.get('daily_breakdown', [])
        
        # Create a map of date -> breakdown info for quick lookup
        breakdown_map = {item['date']: item for item in daily_breakdown}
        
        # Header
        lines.append("Date        | Toggl  | Total  | OT hours | Type")
        lines.append("-" * 60)
        
        # Daily rows
        for day in daily_data:
            date_obj = day['date']
            toggl_h = day.get('time_entry_hours', 0.0)
            total_h = day.get('total_hours', 0.0)
            
            # Get overtime info from breakdown
            breakdown_info = breakdown_map.get(date_obj, {})
            ot_hours = breakdown_info.get('hours', 0.0)
            day_type = breakdown_info.get('type', 'weekday')
            
            # Format type - check if it's actually a weekend from daily_data
            is_weekend = day.get('is_weekend', False)
            if is_weekend or day_type == 'weekend':
                type_str = 'weekend'
            else:
                type_str = 'normal'
            
            lines.append(
                f"{date_obj} | {toggl_h:6.1f}h | {total_h:6.1f}h | {ot_hours:8.1f}h | {type_str}"
            )
        
        lines.append("")
        
        # Weekly totals
        lines.append("Weekly totals:")
        weekly_breakdown = overtime_data.get('weekly_breakdown', {}) or {}
        for week_start in sorted(weekly_breakdown.keys()):
            info = weekly_breakdown[week_start]
            worked = info.get('total_hours', 0.0)
            expected = info.get('expected_hours', 0.0)
            overtime = info.get('overtime', 0.0)
            lines.append(
                f"  Week starting {week_start}: worked={worked:.2f}h, expected={expected:.2f}h, overtime={overtime:.2f}h"
            )
        
        lines.append("")
        
        # Monthly totals
        lines.append("Monthly totals:")
        monthly_total = overtime_data.get('monthly_total_hours', 0.0)
        monthly_expected = overtime_data.get('monthly_expected_hours', 0.0)
        monthly_overtime = overtime_data.get('monthly_overtime', 0.0)
        weekend_overtime = overtime_data.get('weekend_overtime', 0.0)
        
        lines.append(f"  Worked hours:   {monthly_total:.2f}h")
        lines.append(f"  Expected hours: {monthly_expected:.2f}h")
        lines.append(f"  Monthly overtime: {monthly_overtime:.2f}h")
        lines.append(f"  Weekend overtime: {weekend_overtime:.2f}h")
        
        return "\n".join(lines)
    
    def format_admin_summary(self, reports: List[UserReport]) -> str:
        """Format admin summary of all users."""
        
        if not reports:
            return "No user reports available."
        
        lines = []
        lines.append("👥 Admin Summary - All Users")
        lines.append(f"📅 Period: {reports[0].period_string}")
        lines.append(f"👤 Total Users: {len(reports)}")
        lines.append("")
        
        # Summary statistics
        total_hours = sum(r.total_hours for r in reports)
        total_overtime = sum(r.monthly_overtime for r in reports)
        total_missing_days = sum(len(r.missing_days) for r in reports)
        
        lines.append("📊 Summary Statistics:")
        lines.append(f"  • Total Hours: {total_hours:.1f}h")
        lines.append(f"  • Total Overtime: {total_overtime:.1f}h")
        lines.append(f"  • Total Missing Days: {total_missing_days}")
        lines.append(f"  • Average Hours per User: {total_hours / len(reports):.1f}h")
        lines.append("")
        
        # Top performers
        top_performers = sorted(reports, key=lambda x: x.total_hours, reverse=True)[:5]
        lines.append("🏆 Top Performers (by hours):")
        for i, report in enumerate(top_performers, 1):
            lines.append(f"  {i}. {report.user_name}: {report.total_hours:.1f}h")
        lines.append("")
        
        # Users with missing entries
        users_with_missing = [r for r in reports if r.has_missing_entries]
        if users_with_missing:
            lines.append("⚠️ Users with Missing Entries:")
            for report in users_with_missing:
                lines.append(f"  • {report.user_name}: {len(report.missing_days)} missing days")
            lines.append("")
        
        # Department breakdown (if available)
        departments = {}
        for report in reports:
            dept = report.department or 'Unknown'
            if dept not in departments:
                departments[dept] = {'users': 0, 'hours': 0}
            departments[dept]['users'] += 1
            departments[dept]['hours'] += report.total_hours
        
        if len(departments) > 1:
            lines.append("🏢 Department Breakdown:")
            for dept, stats in sorted(departments.items(), key=lambda x: x[1]['hours'], reverse=True):
                avg_hours = stats['hours'] / stats['users'] if stats['users'] > 0 else 0
                lines.append(f"  • {dept}: {stats['users']} users, {stats['hours']:.1f}h total, {avg_hours:.1f}h avg")
            lines.append("")
        
        return "\n".join(lines)
    
