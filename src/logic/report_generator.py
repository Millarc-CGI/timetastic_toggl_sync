"""
Report generator for creating various types of reports.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, date

from ..config import Settings
from ..models.user import User
from ..models.report import MonthlyReport, ProjectReport, UserReport


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
        missing_days = user_data.get('missing_days', [])
        
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
            missing_days=missing_days,
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
    
    def generate_project_report(
        self,
        project_name: str,
        project_id: Optional[int],
        year: int,
        month: int,
        project_stats: Dict[str, Any]
    ) -> ProjectReport:
        """Generate report for a specific project."""
        
        return ProjectReport(
            project_name=project_name,
            project_id=project_id,
            year=year,
            month=month,
            total_hours=project_stats.get('total_hours', 0),
            total_users=project_stats.get('total_users', 0),
            average_hours_per_user=project_stats.get('average_hours_per_user', 0),
            user_hours=project_stats.get('user_distribution', {}),
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
    
    def generate_producer_report(
        self,
        project_stats: Dict[str, Dict[str, Any]],
        year: int,
        month: int
    ) -> List[ProjectReport]:
        """Generate project-focused report for producers."""
        
        reports = []
        
        for project_name, stats in project_stats.items():
            report = self.generate_project_report(
                project_name=project_name,
                project_id=stats.get('project_id'),
                year=year,
                month=month,
                project_stats=stats
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
        
        if report.weekly_overtime > 0 or report.monthly_overtime > 0:
            lines.append("⏱️ Overtime:")
            if report.weekly_overtime:
                lines.append(f"  • Weekly Overtime: {report.weekly_overtime:.1f}h")
            if report.monthly_overtime:
                lines.append(f"  • Monthly Overtime: {report.monthly_overtime:.1f}h")
            lines.append("")
        
        if report.projects_worked:
            lines.append("📁 Projects Worked On:")
            lines.append(f"  • Total Projects: {len(report.projects_worked)}")
            for project in report.projects_worked:
                lines.append(f"  • {project}")
            lines.append("")
        
        if report.has_missing_entries:
            lines.append("⚠️ Missing Entries:")
            lines.append(f"  • Missing Days: {len(report.missing_days)}")
            for missing_day in report.missing_days[:5]:  # Show first 5
                lines.append(f"  • {missing_day.strftime('%Y-%m-%d (%A)')}")
            if len(report.missing_days) > 5:
                lines.append(f"  • ... and {len(report.missing_days) - 5} more")
            lines.append("")
        
        lines.append(f"📅 Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M')}")
        
        return "\n".join(lines)
    
    def format_project_report_summary(self, report: ProjectReport) -> str:
        """Format project report as a summary string."""
        
        lines = []
        lines.append(f"📈 Project Report - {report.project_name}")
        if report.project_id:
            lines.append(f"🆔 Project ID: {report.project_id}")
        lines.append(f"📅 Period: {report.period_string}")
        lines.append("")
        
        lines.append("📊 Project Statistics:")
        lines.append(f"  • Total Hours: {report.total_hours:.1f}h")
        lines.append(f"  • Total Users: {report.total_users}")
        lines.append(f"  • Average Hours per User: {report.average_hours_per_user:.1f}h")
        lines.append("")
        
        if report.user_hours:
            lines.append("👥 User Contributions:")
            sorted_users = sorted(report.user_hours.items(), key=lambda x: x[1], reverse=True)
            for user, hours in sorted_users:
                percentage = (hours / report.total_hours * 100) if report.total_hours > 0 else 0
                lines.append(f"  • {user}: {hours:.1f}h ({percentage:.1f}%)")
            lines.append("")
        
        lines.append(f"📅 Generated: {report.generated_at.strftime('%Y-%m-%d %H:%M')}")
        
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
        
        lines.append(f"📅 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        
        return "\n".join(lines)
    
    def format_producer_summary(self, reports: List[ProjectReport]) -> str:
        """Format producer summary of all projects."""
        
        if not reports:
            return "No project reports available."
        
        lines = []
        lines.append("📈 Producer Summary - All Projects")
        lines.append(f"📅 Period: {reports[0].period_string}")
        lines.append(f"📁 Total Projects: {len(reports)}")
        lines.append("")
        
        # Summary statistics
        total_hours = sum(r.total_hours for r in reports)
        total_users = sum(r.total_users for r in reports)
        
        lines.append("📊 Project Summary:")
        lines.append(f"  • Total Hours: {total_hours:.1f}h")
        lines.append(f"  • Total Users: {total_users}")
        lines.append(f"  • Average Hours per Project: {total_hours / len(reports):.1f}h")
        lines.append("")
        
        # Top projects by hours
        top_projects = sorted(reports, key=lambda x: x.total_hours, reverse=True)[:5]
        lines.append("🏆 Top Projects (by hours):")
        for i, report in enumerate(top_projects, 1):
            lines.append(f"  {i}. {report.project_name}: {report.total_hours:.1f}h")
        lines.append("")
        
        # Projects by user count
        projects_by_users = sorted(reports, key=lambda x: x.total_users, reverse=True)[:5]
        lines.append("👥 Most Collaborative Projects:")
        for i, report in enumerate(projects_by_users, 1):
            lines.append(f"  {i}. {report.project_name}: {report.total_users} users")
        lines.append("")
        
        lines.append(f"📅 Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        
        return "\n".join(lines)
