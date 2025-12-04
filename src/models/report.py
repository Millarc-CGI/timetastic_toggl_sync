"""
Report models for different types of reports.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from datetime import datetime, date


@dataclass
class MonthlyReport:
    """Simplified monthly report for a specific user."""
    
    user_email: str
    user_name: str
    year: int
    month: int
    total_hours: float = 0.0
    overtime_hours: float = 0.0
    total_absence_days: float = 0.0
    generated_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.generated_at is None:
            self.generated_at = datetime.now()
    
    @property
    def period_string(self) -> str:
        return f"{self.year}-{self.month:02d}"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'user_email': self.user_email,
            'user_name': self.user_name,
            'year': self.year,
            'month': self.month,
            'total_hours': self.total_hours,
            'overtime_hours': self.overtime_hours,
            'total_absence_days': self.total_absence_days,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
        }


@dataclass
class UserReport:
    """Individual user report with detailed breakdown."""
    
    user_email: str
    user_name: str
    department: Optional[str] = None
    year: int = 0
    month: int = 0
    report_type: str = "monthly"
    period_label: Optional[str] = None
    
    # Time tracking summary
    total_hours: float = 0.0
    
    # Overtime breakdown
    weekly_overtime: float = 0.0
    monthly_overtime: float = 0.0
    
    # Project summary
    projects_worked: List[str] = None
    project_tasks: Dict[str, Dict[str, float]] = None
    
    # Missing entries
    missing_days: List[date] = None
    
    # Entries without project
    no_project_entries_count: int = 0
    
    # Daily overtime breakdown
    daily_breakdown: List[Dict[str, Any]] = None
    
    # Metadata
    generated_at: Optional[datetime] = None
    
    def __post_init__(self):
        """Initialize default values after dataclass creation."""
        if self.projects_worked is None:
            self.projects_worked = []
        if self.project_tasks is None:
            self.project_tasks = {}
        if self.missing_days is None:
            self.missing_days = []
        if self.daily_breakdown is None:
            self.daily_breakdown = []
        if self.generated_at is None:
            self.generated_at = datetime.now()
        if not self.period_label:
            if self.year > 0 and self.month > 0:
                self.period_label = f"{self.year}-{self.month:02d}"
            else:
                self.period_label = "All Time"
    
    @property
    def period_string(self) -> str:
        """Get period as string."""
        return self.period_label or "All Time"
    
    @property
    def has_missing_entries(self) -> bool:
        """Check if user has missing time entries."""
        return len(self.missing_days) > 0
    
    @property
    def has_no_project_entries(self) -> bool:
        """Check if user has entries without project."""
        return self.no_project_entries_count > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary for storage."""
        return {
            'user_email': self.user_email,
            'user_name': self.user_name,
            'department': self.department,
            'year': self.year,
            'month': self.month,
            'report_type': self.report_type,
            'period_label': self.period_label,
            'total_hours': self.total_hours,
            'weekly_overtime': self.weekly_overtime,
            'monthly_overtime': self.monthly_overtime,
            'projects_worked': self.projects_worked,
            'project_tasks': self.project_tasks,
            'missing_days': [d.isoformat() for d in self.missing_days],
            'no_project_entries_count': self.no_project_entries_count,
            'daily_breakdown': self.daily_breakdown,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
        }
