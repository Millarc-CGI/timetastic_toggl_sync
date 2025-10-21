"""
Report models for different types of reports.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from datetime import datetime, date


@dataclass
class MonthlyReport:
    """Monthly report for a specific user."""
    
    user_email: str
    user_name: str
    year: int
    month: int
    
    # Time tracking data
    total_hours: float = 0.0
    billable_hours: float = 0.0
    overtime_hours: float = 0.0
    
    # Absence data
    vacation_days: int = 0
    sick_days: int = 0
    personal_days: int = 0
    other_absence_days: int = 0
    
    # Project breakdown
    project_hours: Dict[str, float] = None
    
    # Metadata
    generated_at: Optional[datetime] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    
    def __post_init__(self):
        """Initialize default values after dataclass creation."""
        if self.project_hours is None:
            self.project_hours = {}
        if self.generated_at is None:
            self.generated_at = datetime.now()
    
    @property
    def month_name(self) -> str:
        """Get month name."""
        month_names = [
            'January', 'February', 'March', 'April', 'May', 'June',
            'July', 'August', 'September', 'October', 'November', 'December'
        ]
        return month_names[self.month - 1] if 1 <= self.month <= 12 else 'Unknown'
    
    @property
    def period_string(self) -> str:
        """Get period as string."""
        return f"{self.year}-{self.month:02d}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary for storage."""
        return {
            'user_email': self.user_email,
            'user_name': self.user_name,
            'year': self.year,
            'month': self.month,
            'total_hours': self.total_hours,
            'billable_hours': self.billable_hours,
            'overtime_hours': self.overtime_hours,
            'vacation_days': self.vacation_days,
            'sick_days': self.sick_days,
            'personal_days': self.personal_days,
            'other_absence_days': self.other_absence_days,
            'project_hours': self.project_hours,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
        }


@dataclass
class ProjectReport:
    """Project-focused report for producers."""
    
    project_name: str
    project_id: Optional[int] = None
    year: int = 0
    month: int = 0
    
    # Project statistics
    total_hours: float = 0.0
    total_users: int = 0
    average_hours_per_user: float = 0.0
    
    # User breakdown
    user_hours: Dict[str, float] = None
    
    # Cost estimation (if available)
    estimated_cost: Optional[float] = None
    hourly_rate: Optional[float] = None
    
    # Metadata
    generated_at: Optional[datetime] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    
    def __post_init__(self):
        """Initialize default values after dataclass creation."""
        if self.user_hours is None:
            self.user_hours = {}
        if self.generated_at is None:
            self.generated_at = datetime.now()
    
    @property
    def period_string(self) -> str:
        """Get period as string."""
        return f"{self.year}-{self.month:02d}" if self.year > 0 and self.month > 0 else "All Time"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary for storage."""
        return {
            'project_name': self.project_name,
            'project_id': self.project_id,
            'year': self.year,
            'month': self.month,
            'total_hours': self.total_hours,
            'total_users': self.total_users,
            'average_hours_per_user': self.average_hours_per_user,
            'user_hours': self.user_hours,
            'estimated_cost': self.estimated_cost,
            'hourly_rate': self.hourly_rate,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
        }


@dataclass
class UserReport:
    """Individual user report with detailed breakdown."""
    
    user_email: str
    user_name: str
    department: Optional[str] = None
    year: int = 0
    month: int = 0
    
    # Time tracking summary
    total_hours: float = 0.0
    billable_hours: float = 0.0
    non_billable_hours: float = 0.0
    
    # Overtime breakdown
    daily_overtime: float = 0.0
    weekly_overtime: float = 0.0
    monthly_overtime: float = 0.0
    
    # Absence summary
    total_absence_days: int = 0
    absence_breakdown: Dict[str, int] = None
    
    # Project summary
    projects_worked: List[str] = None
    project_hours: Dict[str, float] = None
    
    # Missing entries
    missing_days: List[date] = None
    
    # Metadata
    generated_at: Optional[datetime] = None
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    
    def __post_init__(self):
        """Initialize default values after dataclass creation."""
        if self.absence_breakdown is None:
            self.absence_breakdown = {}
        if self.projects_worked is None:
            self.projects_worked = []
        if self.project_hours is None:
            self.project_hours = {}
        if self.missing_days is None:
            self.missing_days = []
        if self.generated_at is None:
            self.generated_at = datetime.now()
    
    @property
    def period_string(self) -> str:
        """Get period as string."""
        if self.year > 0 and self.month > 0:
            return f"{self.year}-{self.month:02d}"
        return "All Time"
    
    @property
    def has_missing_entries(self) -> bool:
        """Check if user has missing time entries."""
        return len(self.missing_days) > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary for storage."""
        return {
            'user_email': self.user_email,
            'user_name': self.user_name,
            'department': self.department,
            'year': self.year,
            'month': self.month,
            'total_hours': self.total_hours,
            'billable_hours': self.billable_hours,
            'non_billable_hours': self.non_billable_hours,
            'daily_overtime': self.daily_overtime,
            'weekly_overtime': self.weekly_overtime,
            'monthly_overtime': self.monthly_overtime,
            'total_absence_days': self.total_absence_days,
            'absence_breakdown': self.absence_breakdown,
            'projects_worked': self.projects_worked,
            'project_hours': self.project_hours,
            'missing_days': [d.isoformat() for d in self.missing_days],
            'generated_at': self.generated_at.isoformat() if self.generated_at else None,
            'period_start': self.period_start.isoformat() if self.period_start else None,
            'period_end': self.period_end.isoformat() if self.period_end else None,
        }
