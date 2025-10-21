"""
Time entry model for Toggl data.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class TimeEntry:
    """Represents a time entry from Toggl Track."""
    
    # Toggl-specific fields
    toggl_id: int
    description: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_seconds: int = 0
    
    # Project and task information
    project_id: Optional[int] = None
    project_name: Optional[str] = None
    task_id: Optional[int] = None
    task_name: Optional[str] = None
    
    # User information
    user_id: Optional[int] = None
    user_email: Optional[str] = None
    
    # Tags and additional data
    tags: Optional[list] = None
    billable: bool = False
    
    # Workspace information
    workspace_id: Optional[int] = None
    
    # Metadata
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    def __post_init__(self):
        """Initialize default values after dataclass creation."""
        if self.tags is None:
            self.tags = []
        if self.created_at is None:
            self.created_at = datetime.now()
        if self.updated_at is None:
            self.updated_at = datetime.now()
    
    @property
    def duration_hours(self) -> float:
        """Get duration in hours."""
        return self.duration_seconds / 3600.0 if self.duration_seconds > 0 else 0.0
    
    @property
    def is_running(self) -> bool:
        """Check if the time entry is currently running."""
        return self.duration_seconds < 0
    
    @property
    def date(self) -> datetime:
        """Get the date of the time entry (start date)."""
        return self.start_time.date()
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert time entry to dictionary for storage."""
        return {
            'toggl_id': self.toggl_id,
            'description': self.description,
            'start_time': self.start_time.isoformat(),
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'duration_seconds': self.duration_seconds,
            'project_id': self.project_id,
            'project_name': self.project_name,
            'task_id': self.task_id,
            'task_name': self.task_name,
            'user_id': self.user_id,
            'user_email': self.user_email,
            'tags': self.tags,
            'billable': self.billable,
            'workspace_id': self.workspace_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
    
    @classmethod
    def from_toggl_data(cls, data: Dict[str, Any]) -> 'TimeEntry':
        """Create TimeEntry from Toggl API response."""
        # Parse datetime fields
        start_time = None
        end_time = None
        created_at = None
        updated_at = None
        
        if data.get('start'):
            try:
                start_time = datetime.fromisoformat(data['start'].replace('Z', '+00:00'))
            except ValueError:
                pass
        
        if data.get('stop'):
            try:
                end_time = datetime.fromisoformat(data['stop'].replace('Z', '+00:00'))
            except ValueError:
                pass
        
        if data.get('created_at'):
            try:
                created_at = datetime.fromisoformat(data['created_at'].replace('Z', '+00:00'))
            except ValueError:
                pass
        
        if data.get('updated_at'):
            try:
                updated_at = datetime.fromisoformat(data['updated_at'].replace('Z', '+00:00'))
            except ValueError:
                pass
        
        # Extract project information
        project_data = data.get('project', {})
        project_id = project_data.get('id') if project_data else None
        project_name = project_data.get('name') if project_data else None
        
        # Extract task information
        task_data = data.get('task', {})
        task_id = task_data.get('id') if task_data else None
        task_name = task_data.get('name') if task_data else None
        
        return cls(
            toggl_id=data['id'],
            description=data.get('description', ''),
            start_time=start_time or datetime.now(),
            end_time=end_time,
            duration_seconds=data.get('duration', 0),
            project_id=project_id,
            project_name=project_name,
            task_id=task_id,
            task_name=task_name,
            user_id=data.get('user_id'),
            user_email=data.get('user_email'),
            tags=data.get('tags', []),
            billable=data.get('billable', False),
            workspace_id=data.get('workspace_id'),
            created_at=created_at,
            updated_at=updated_at,
        )
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TimeEntry':
        """Create TimeEntry from dictionary."""
        # Parse datetime fields
        start_time = None
        end_time = None
        created_at = None
        updated_at = None
        
        if data.get('start_time'):
            try:
                start_time = datetime.fromisoformat(data['start_time'])
            except ValueError:
                pass
        
        if data.get('end_time'):
            try:
                end_time = datetime.fromisoformat(data['end_time'])
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
            toggl_id=data['toggl_id'],
            description=data.get('description', ''),
            start_time=start_time or datetime.now(),
            end_time=end_time,
            duration_seconds=data.get('duration_seconds', 0),
            project_id=data.get('project_id'),
            project_name=data.get('project_name'),
            task_id=data.get('task_id'),
            task_name=data.get('task_name'),
            user_id=data.get('user_id'),
            user_email=data.get('user_email'),
            tags=data.get('tags', []),
            billable=data.get('billable', False),
            workspace_id=data.get('workspace_id'),
            created_at=created_at,
            updated_at=updated_at,
        )
