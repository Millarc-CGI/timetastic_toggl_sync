"""
Permission management for role-based access control.
"""

from typing import List, Dict, Any, Optional, Set
from pathlib import Path
from datetime import datetime

from ..config import Settings
from ..models.user import User


class PermissionManager:
    """Manages role-based access control and permissions."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.admin_emails = settings.admin_emails
        self.producer_emails = settings.producer_emails
    
    def is_admin(self, email: str) -> bool:
        """Check if email is in admin list."""
        return email.strip().lower() in self.admin_emails
    
    def is_producer(self, email: str) -> bool:
        """Check if email is in producer list."""
        return email.strip().lower() in self.producer_emails
    
    def is_regular_user(self, email: str) -> bool:
        """Check if email is a regular user (not admin or producer)."""
        email_lower = email.strip().lower()
        return not (self.is_admin(email) or self.is_producer(email))
    
    def get_user_role(self, email: str) -> str:
        """Get user role based on email."""
        if self.is_admin(email):
            return "admin"
        elif self.is_producer(email):
            return "producer"
        else:
            return "user"
    
    def can_access_admin_reports(self, email: str) -> bool:
        """Check if user can access admin reports."""
        return self.is_admin(email)
    
    def can_access_producer_reports(self, email: str) -> bool:
        """Check if user can access producer reports."""
        return self.is_admin(email) or self.is_producer(email)
    
    def can_access_user_reports(self, email: str) -> bool:
        """Check if user can access user reports."""
        return True  # All users can access their own reports
    
    def can_access_specific_user_report(self, requester_email: str, target_email: str) -> bool:
        """Check if requester can access specific user's report."""
        # Users can access their own reports
        if requester_email.strip().lower() == target_email.strip().lower():
            return True
        
        # Admins can access all user reports
        if self.is_admin(requester_email):
            return True
        
        # Producers can access user reports (for project tracking)
        if self.is_producer(requester_email):
            return True
        
        return False
    
    def get_report_path_for_role(self, role: str, year: int, month: int, file_type: str = "csv") -> Path:
        """Get file path for role-based report."""
        if role == "admin":
            return Path(f"admin_{year:04d}-{month:02d}.{file_type}")
        elif role == "producer":
            return Path(f"producer_{year:04d}-{month:02d}.{file_type}")
        elif role == "user":
            return Path(f"user_{year:04d}-{month:02d}.{file_type}")
        else:
            raise ValueError(f"Invalid role: {role}")
    
    def get_user_report_path(self, email: str, year: int, month: int, file_type: str = "csv") -> Path:
        """Get file path for user-specific report."""
        # Sanitize email for filename
        safe_email = email.replace('@', '_at_').replace('.', '_')
        return Path(f"user_{safe_email}_{year:04d}-{month:02d}.{file_type}")
    
    def can_access_file(self, requester_email: str, file_path: Path) -> bool:
        """Check if user can access a specific file."""
        filename = file_path.name.lower()
        
        # Admin files - only admins can access
        if filename.startswith("admin_"):
            return self.is_admin(requester_email)
        
        # Producer files - admins and producers can access
        if filename.startswith("producer_"):
            return self.can_access_producer_reports(requester_email)
        
        # User files - check if it's their own file or if they have permission
        if filename.startswith("user_"):
            # Extract email from filename
            try:
                # Format: user_email_at_domain_com_YYYY-MM.csv
                parts = filename.split('_')
                if len(parts) >= 4:
                    email_part = '_'.join(parts[1:-2])  # Everything between 'user' and date
                    # Convert back to email format
                    target_email = email_part.replace('_at_', '@').replace('_', '.')
                    
                    return self.can_access_specific_user_report(requester_email, target_email)
            except Exception:
                pass
        
        # Default: deny access
        return False
    
    def get_accessible_reports(self, email: str, year: int, month: int) -> Dict[str, List[Path]]:
        """Get list of accessible reports for a user."""
        accessible = {
            'admin': [],
            'producer': [],
            'user': [],
            'own': []
        }
        
        # Admin reports
        if self.can_access_admin_reports(email):
            accessible['admin'].append(self.get_report_path_for_role("admin", year, month))
        
        # Producer reports
        if self.can_access_producer_reports(email):
            accessible['producer'].append(self.get_report_path_for_role("producer", year, month))
        
        # User's own report
        accessible['own'].append(self.get_user_report_path(email, year, month))
        
        return accessible
    
    def filter_users_by_access(self, requester_email: str, users: List[User]) -> List[User]:
        """Filter users based on requester's access level."""
        if self.is_admin(requester_email):
            # Admins can see all users
            return users
        elif self.is_producer(requester_email):
            # Producers can see all users (for project tracking)
            return users
        else:
            # Regular users can only see themselves
            return [user for user in users if user.email.lower() == requester_email.lower()]
    
    def get_permission_summary(self, email: str) -> Dict[str, Any]:
        """Get summary of permissions for a user."""
        role = self.get_user_role(email)
        
        return {
            'email': email,
            'role': role,
            'permissions': {
                'can_access_admin_reports': self.can_access_admin_reports(email),
                'can_access_producer_reports': self.can_access_producer_reports(email),
                'can_access_user_reports': self.can_access_user_reports(email),
                'can_access_all_users': self.is_admin(email) or self.is_producer(email),
                'can_modify_settings': self.is_admin(email),
                'can_send_notifications': self.is_admin(email) or self.is_producer(email)
            },
            'restrictions': {
                'can_only_access_own_data': self.is_regular_user(email),
                'cannot_modify_user_mappings': self.is_regular_user(email),
                'cannot_access_financial_data': self.is_regular_user(email)
            }
        }
    
    def validate_access_request(self, requester_email: str, action: str, resource: str) -> Dict[str, Any]:
        """Validate access request and return result."""
        
        role = self.get_user_role(requester_email)
        
        # Define access rules
        access_rules = {
            'admin': {
                'read_admin_reports': True,
                'read_producer_reports': True,
                'read_user_reports': True,
                'read_all_users': True,
                'modify_settings': True,
                'send_notifications': True,
                'access_financial_data': True
            },
            'producer': {
                'read_admin_reports': False,
                'read_producer_reports': True,
                'read_user_reports': True,
                'read_all_users': True,
                'modify_settings': False,
                'send_notifications': True,
                'access_financial_data': False
            },
            'user': {
                'read_admin_reports': False,
                'read_producer_reports': False,
                'read_user_reports': True,
                'read_all_users': False,
                'modify_settings': False,
                'send_notifications': False,
                'access_financial_data': False
            }
        }
        
        # Check if action is allowed for role
        role_rules = access_rules.get(role, {})
        allowed = role_rules.get(action, False)
        
        return {
            'allowed': allowed,
            'requester_email': requester_email,
            'role': role,
            'action': action,
            'resource': resource,
            'reason': f"{'Granted' if allowed else 'Denied'} access for {role} role"
        }
    
    def create_access_log_entry(self, requester_email: str, action: str, resource: str, success: bool) -> Dict[str, Any]:
        """Create access log entry."""
        return {
            'timestamp': datetime.now().isoformat(),
            'requester_email': requester_email,
            'role': self.get_user_role(requester_email),
            'action': action,
            'resource': resource,
            'success': success,
            'ip_address': None,  # Would be populated by web interface
            'user_agent': None   # Would be populated by web interface
        }
    
    def get_role_hierarchy(self) -> Dict[str, int]:
        """Get role hierarchy (higher number = more permissions)."""
        return {
            'user': 1,
            'producer': 2,
            'admin': 3
        }
    
    def can_escalate_permissions(self, requester_email: str, target_email: str) -> bool:
        """Check if requester can escalate permissions for target user."""
        requester_role = self.get_user_role(requester_email)
        target_role = self.get_user_role(target_email)
        
        hierarchy = self.get_role_hierarchy()
        
        # Can only escalate if requester has higher role
        return hierarchy.get(requester_role, 0) > hierarchy.get(target_role, 0)
    
    def get_available_actions(self, email: str) -> List[str]:
        """Get list of available actions for a user."""
        role = self.get_user_role(email)
        
        actions = []
        
        if self.is_admin(email):
            actions.extend([
                'read_admin_reports',
                'read_producer_reports', 
                'read_user_reports',
                'read_all_users',
                'modify_settings',
                'send_notifications',
                'access_financial_data',
                'manage_users',
                'view_system_logs'
            ])
        elif self.is_producer(email):
            actions.extend([
                'read_producer_reports',
                'read_user_reports',
                'read_all_users',
                'send_notifications'
            ])
        else:
            actions.extend([
                'read_user_reports'
            ])
        
        return actions
    
    def audit_user_access(self, email: str) -> Dict[str, Any]:
        """Audit user access and return detailed information."""
        return {
            'email': email,
            'role': self.get_user_role(email),
            'permissions': self.get_permission_summary(email),
            'available_actions': self.get_available_actions(email),
            'can_escalate': self.can_escalate_permissions(email, email),  # Self-escalation
            'hierarchy_level': self.get_role_hierarchy().get(self.get_user_role(email), 0),
            'audit_timestamp': datetime.now().isoformat()
        }
