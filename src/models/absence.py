"""
Absence model for Timetastic data.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime, date


@dataclass
class Absence:
    """Represents an absence/holiday from Timetastic."""
    
    # Timetastic-specific fields
    timetastic_id: int
    absence_type: str
    start_date: date
    end_date: date
    status: str = "Approved"
    
    # User information
    user_id: Optional[int] = None
    user_email: Optional[str] = None
    user_name: Optional[str] = None
    
    # Additional information
    notes: Optional[str] = None
    department: Optional[str] = None
    
    # Metadata
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def __post_init__(self):
        """Initialize default values after dataclass creation."""
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()
    
    @property
    def duration_days(self) -> int:
        """Calculate duration in days (inclusive)."""
        return (self.end_date - self.start_date).days + 1
    
    @property
    def is_single_day(self) -> bool:
        """Check if absence is for a single day."""
        return self.start_date == self.end_date
    
    def is_date_in_range(self, check_date: date) -> bool:
        """Check if a specific date falls within this absence period."""
        return self.start_date <= check_date <= self.end_date
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert absence to dictionary for storage."""
        return {
            'timetastic_id': self.timetastic_id,
            'absence_type': self.absence_type,
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'status': self.status,
            'user_id': self.user_id,
            'user_email': self.user_email,
            'user_name': self.user_name,
            'notes': self.notes,
            'department': self.department,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
    
    @classmethod
    def from_timetastic_data(cls, data: Dict[str, Any]) -> 'Absence':
        """Create Absence from Timetastic API response."""
        # Parse date fields
        start_date = None
        end_date = None
        created_at = None
        updated_at = None
        
        if data.get('startDate'):
            try:
                start_date = datetime.fromisoformat(data['startDate']).date()
            except ValueError:
                pass
        
        if data.get('endDate'):
            try:
                end_date = datetime.fromisoformat(data['endDate']).date()
            except ValueError:
                pass
        
        if data.get('createdAt'):
            try:
                created_at = datetime.fromisoformat(data['createdAt'].replace('Z', '+00:00'))
            except ValueError:
                pass
        
        if data.get('updatedAt'):
            try:
                updated_at = datetime.fromisoformat(data['updatedAt'].replace('Z', '+00:00'))
            except ValueError:
                pass
        
        # Extract absence type
        absence_type = "Unknown"
        type_data = data.get('type', {})
        if isinstance(type_data, dict):
            absence_type = type_data.get('name', 'Unknown')
        elif isinstance(type_data, str):
            absence_type = type_data
        
        # Extract user information
        user_id = data.get('userId') or data.get('UserId')
        user_email = None
        user_name = None
        
        user_data = data.get('user', {})
        if user_data:
            user_email = user_data.get('email')
            first_name = user_data.get('firstName', '')
            last_name = user_data.get('lastName', '')
            user_name = f"{first_name} {last_name}".strip()
        
        return cls(
            timetastic_id=data['id'],
            absence_type=absence_type,
            start_date=start_date or date.today(),
            end_date=end_date or date.today(),
            status=data.get('status', 'Approved'),
            user_id=user_id,
            user_email=user_email,
            user_name=user_name,
            notes=data.get('notes'),
            department=data.get('department'),
            created_at=created_at,
            updated_at=updated_at,
        )
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Absence':
        """Create Absence from dictionary."""
        # Parse date fields
        start_date = None
        end_date = None
        created_at = None
        updated_at = None
        
        if data.get('start_date'):
            try:
                start_date = datetime.fromisoformat(data['start_date']).date()
            except ValueError:
                pass
        
        if data.get('end_date'):
            try:
                end_date = datetime.fromisoformat(data['end_date']).date()
            except ValueError:
                pass
        
        if data.get('created_at'):
            try:
                created_at = datetime.fromisoformat(data['created_at'])
            except ValueError:
                pass
        
        if data.get('updated_at'):
            try:
                updated_at = datetime.fromisoformat(data['updated_at'])
            except ValueError:
                pass
        
        return cls(
            timetastic_id=data['timetastic_id'],
            absence_type=data.get('absence_type', 'Unknown'),
            start_date=start_date or date.today(),
            end_date=end_date or date.today(),
            status=data.get('status', 'Approved'),
            user_id=data.get('user_id'),
            user_email=data.get('user_email'),
            user_name=data.get('user_name'),
            notes=data.get('notes'),
            department=data.get('department'),
            created_at=created_at,
            updated_at=updated_at,
        )
