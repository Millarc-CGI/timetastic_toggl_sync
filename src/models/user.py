"""
User model for mapping users across Toggl, Timetastic, and Slack.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class User:
    """Represents a user across all integrated services."""
    
    # Primary identifier
    email: str
    
    # Service-specific IDs
    toggl_user_id: Optional[int] = None
    timetastic_user_id: Optional[int] = None
    slack_user_id: Optional[str] = None
    
    # User information
    full_name: str = ""
    department: Optional[str] = None
    
    # Custom settings (overtime rules will be implemented in overtime_calculator.py)
    
    # Access control
    is_admin: bool = False
    is_producer: bool = False
    
    # Metadata
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_sync_at: Optional[datetime] = None
    
    def __post_init__(self):
        """Initialize default values after dataclass creation."""
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()
    
    @property
    def display_name(self) -> str:
        """Get display name, falling back to email if full_name is empty."""
        return self.full_name if self.full_name else self.email
    
    @property
    def is_mapped(self) -> bool:
        """Check if user is mapped to at least one service."""
        return any([
            self.toggl_user_id is not None,
            self.timetastic_user_id is not None,
            self.slack_user_id is not None
        ])
    
    def update_timestamp(self):
        """Update the updated_at timestamp."""
        self.updated_at = datetime.now()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert user to dictionary for storage."""
        return {
            'email': self.email,
            'toggl_user_id': self.toggl_user_id,
            'timetastic_user_id': self.timetastic_user_id,
            'slack_user_id': self.slack_user_id,
            'full_name': self.full_name,
            'department': self.department,
            # overtime_rules removed - will be implemented in overtime_calculator.py
            'is_admin': self.is_admin,
            'is_producer': self.is_producer,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'last_sync_at': self.last_sync_at.isoformat() if self.last_sync_at else None,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'User':
        """Create user from dictionary."""
        # Parse datetime fields
        created_at = None
        updated_at = None
        last_sync_at = None
        
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
                
        if data.get('last_sync_at'):
            try:
                last_sync_at = datetime.fromisoformat(data['last_sync_at'])
            except ValueError:
                pass
        
        return cls(
            email=data['email'],
            toggl_user_id=data.get('toggl_user_id'),
            timetastic_user_id=data.get('timetastic_user_id'),
            slack_user_id=data.get('slack_user_id'),
            full_name=data.get('full_name', ''),
            department=data.get('department'),
            # overtime_rules removed
            is_admin=data.get('is_admin', False),
            is_producer=data.get('is_producer', False),
            created_at=created_at,
            updated_at=updated_at,
            last_sync_at=last_sync_at,
        )
