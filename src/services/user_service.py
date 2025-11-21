"""
User service for managing user mappings and synchronization.
"""

from typing import List, Dict, Any, Optional, Set
from datetime import datetime

from ..config import Settings
from ..models.user import User
from .toggl_service import TogglService
from .timetastic_service import TimetasticService
from .slack_service import SlackService


class UserService:
    """Service for managing user data and mappings across services."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.toggl_service = TogglService(settings)
        self.timetastic_service = TimetasticService(settings)
        self.slack_service = SlackService(settings)
    
    def sync_users_from_services(self) -> List[User]:
        """Synchronize users from all services and create mappings."""
        print("🔄 Syncing users from all services...")
        
        # Get users from each service
        toggl_users = []
        timetastic_users = []
        slack_users = []
        
        try:
            toggl_users = self.toggl_service.get_workspace_users()
            print(f"✅ Found {len(toggl_users)} Toggl users")
        except Exception as e:
            print(f"❌ Failed to fetch Toggl users: {e}")
        
        try:
            timetastic_users = self.timetastic_service.get_users()
            print(f"✅ Found {len(timetastic_users)} Timetastic users")
        except Exception as e:
            print(f"❌ Failed to fetch Timetastic users: {e}")
        
        try:
            slack_users = self.slack_service.get_users()
            print(f"✅ Found {len(slack_users)} Slack users")
        except Exception as e:
            print(f"❌ Failed to fetch Slack users: {e}")
        
        # Create user mappings
        user_mappings = {}
        
        active_timetastic_emails = self._collect_active_timetastic_emails(timetastic_users)

        # Process each service's users
        self._process_toggl_users(toggl_users, user_mappings, active_timetastic_emails)
        self._process_timetastic_users(timetastic_users, user_mappings)
        self._process_slack_users(slack_users, user_mappings, active_timetastic_emails)
        
        # Convert to User objects
        users = []
        for email, mapping in user_mappings.items():
            department = mapping.get('department')
            department_normalized = (department or '').strip().lower()

            user = User(
                email=email,
                toggl_user_id=mapping.get('toggl_id'),
                timetastic_user_id=mapping.get('timetastic_id'),
                slack_user_id=mapping.get('slack_id'),
                full_name=mapping.get('full_name', ''),
                department=department,
                is_admin=(
                    department_normalized == 'administracja'
                    or email.lower() in self.settings.admin_emails
                ),
                is_producer=(
                    department_normalized == 'production'
                    or email.lower() in self.settings.producer_emails
                ),
                # overtime_rules removed - will be implemented in overtime_calculator.py
            )
            users.append(user)
        
        print(f"✅ Created {len(users)} user mappings")
        return users
    
    def _process_toggl_users(
        self,
        toggl_users: List[Dict[str, Any]],
        user_mappings: Dict[str, Dict[str, Any]],
        active_timetastic_emails: Set[str],
    ):
        """Process Toggl users and add to mappings."""
        for user in toggl_users:
            email = user.get('email', '').lower()
            if not email:
                continue
            if not user.get('is_active', False):
                continue
            if active_timetastic_emails and email not in active_timetastic_emails:
                continue
            
            if email not in user_mappings:
                user_mappings[email] = {}
            
            user_mappings[email]['toggl_id'] = user.get('id')
            user_mappings[email]['full_name'] = user.get('fullname', '')

    def _process_timetastic_users(self, timetastic_users: List[Dict[str, Any]], user_mappings: Dict[str, Dict[str, Any]]):
        """Process Timetastic users and add to mappings."""
        for user in timetastic_users:
            if not self._is_timetastic_user_active(user):
                continue
            email = user.get('email') or user.get('Email', '')
            if not email:
                continue
            
            email = email.lower()
            if email not in user_mappings:
                user_mappings[email] = {}
            
            user_mappings[email]['timetastic_id'] = user.get('id') or user.get('Id')
            
            # Update full name if not set or if Timetastic has better info
            first_name = user.get('firstName') or user.get('FirstName', '')
            last_name = user.get('lastName') or user.get('LastName', '')
            full_name = f"{first_name} {last_name}".strip()
            
            if full_name and (not user_mappings[email].get('full_name') or len(full_name) > len(user_mappings[email].get('full_name', ''))):
                user_mappings[email]['full_name'] = full_name
            
            # Add department info
            department = user.get('department', {})
            department_name = (
                user.get('departmentName')
                or user.get('department_name')
                or (department.get('name') if isinstance(department, dict) else None)
                or (department.get('Name') if isinstance(department, dict) else None)
            )
            if not department_name and isinstance(department, str):
                department_name = department
            if department_name:
                user_mappings[email]['department'] = department_name

    def _process_slack_users(
        self,
        slack_users: List[Dict[str, Any]],
        user_mappings: Dict[str, Dict[str, Any]],
        active_timetastic_emails: Set[str],
    ):
        """Process Slack users and add to mappings."""
        for user in slack_users:
            profile = user.get('profile', {})
            email = profile.get('email', '').lower()
            if not email or user.get('deleted', False) or user.get('is_bot', False):
                continue
            if active_timetastic_emails and email not in active_timetastic_emails:
                continue
            
            if email not in user_mappings:
                user_mappings[email] = {}
            
            user_mappings[email]['slack_id'] = user.get('id')
            
            # Update full name if not set or if Slack has better info
            real_name = profile.get('real_name') or profile.get('real_name_normalized', '')
            display_name = profile.get('display_name') or profile.get('display_name_normalized', '')
            full_name = real_name or display_name
            
            if full_name and (not user_mappings[email].get('full_name') or len(full_name) > len(user_mappings[email].get('full_name', ''))):
                user_mappings[email]['full_name'] = full_name
            elif not user_mappings[email].get('full_name') and display_name:
                user_mappings[email]['full_name'] = display_name

    def _collect_active_timetastic_emails(self, timetastic_users: List[Dict[str, Any]]) -> Set[str]:
        emails: Set[str] = set()
        for user in timetastic_users:
            if not self._is_timetastic_user_active(user):
                continue
            email = (user.get('email') or user.get('Email', '')).strip().lower()
            if email:
                emails.add(email)
        return emails

    def _is_timetastic_user_active(self, user: Dict[str, Any]) -> bool:
        for key in ('isActive', 'IsActive', 'active', 'Active', 'is_active'):
            if key in user:
                return bool(user.get(key))
        return True
    
    def get_user_by_email(self, email: str, users: Optional[List[User]] = None) -> Optional[User]:
        """Get user by email address."""
        if users is None:
            # This would typically come from storage, but for now we'll sync fresh
            users = self.sync_users_from_services()
        
        email_lower = email.lower()
        for user in users:
            if user.email.lower() == email_lower:
                return user
        return None
    
    def get_all_users(self) -> List[User]:
        """Get all users (would typically come from storage)."""
        return self.sync_users_from_services()
    
    def get_admin_users(self, users: Optional[List[User]] = None) -> List[User]:
        """Get all admin users."""
        if users is None:
            users = self.get_all_users()
        
        return [user for user in users if user.is_admin]
    
    def get_producer_users(self, users: Optional[List[User]] = None) -> List[User]:
        """Get all producer users."""
        if users is None:
            users = self.get_all_users()
        
        return [user for user in users if user.is_producer]
    
    def get_regular_users(self, users: Optional[List[User]] = None) -> List[User]:
        """Get all regular users (not admin or producer)."""
        if users is None:
            users = self.get_all_users()
        
        return [user for user in users if not user.is_admin and not user.is_producer]
    
    def get_mapped_users(self, users: Optional[List[User]] = None) -> List[User]:
        """Get users that are mapped to at least one service."""
        if users is None:
            users = self.get_all_users()
        
        return [user for user in users if user.is_mapped]
    
    def get_unmapped_users(self, users: Optional[List[User]] = None) -> List[User]:
        """Get users that are not mapped to any service."""
        if users is None:
            users = self.get_all_users()
        
        return [user for user in users if not user.is_mapped]
    
    def update_user_mapping(self, email: str, **updates) -> bool:
        """Update user mapping information."""
        # This would typically update the storage layer
        # For now, we'll just return True as a placeholder
        print(f"📝 Updating user mapping for {email}: {updates}")
        return True
    
    def validate_user_mappings(self, users: Optional[List[User]] = None) -> Dict[str, List[str]]:
        """Validate user mappings and return issues."""
        if users is None:
            users = self.get_all_users()
        
        issues = {
            'unmapped': [],
            'incomplete': [],
            'duplicates': []
        }
        
        seen_emails = set()
        
        for user in users:
            # Check for duplicates
            if user.email.lower() in seen_emails:
                issues['duplicates'].append(user.email)
            seen_emails.add(user.email.lower())
            
            # Check if completely unmapped
            if not user.is_mapped:
                issues['unmapped'].append(user.email)
            
            # Check for incomplete mappings (missing some services)
            missing_services = []
            if not user.toggl_user_id:
                missing_services.append('Toggl')
            if not user.timetastic_user_id:
                missing_services.append('Timetastic')
            if not user.slack_user_id:
                missing_services.append('Slack')
            
            if missing_services and user.is_mapped:
                issues['incomplete'].append(f"{user.email} (missing: {', '.join(missing_services)})")
        
        return issues
    
    def get_user_statistics(self, users: Optional[List[User]] = None) -> Dict[str, Any]:
        """Get statistics about user mappings."""
        if users is None:
            users = self.get_all_users()
        
        total_users = len(users)
        mapped_users = len(self.get_mapped_users(users))
        unmapped_users = total_users - mapped_users
        
        admin_count = len(self.get_admin_users(users))
        producer_count = len(self.get_producer_users(users))
        regular_count = total_users - admin_count - producer_count
        
        # Service-specific statistics
        toggl_mapped = sum(1 for u in users if u.toggl_user_id is not None)
        timetastic_mapped = sum(1 for u in users if u.timetastic_user_id is not None)
        slack_mapped = sum(1 for u in users if u.slack_user_id is not None)
        
        return {
            'total_users': total_users,
            'mapped_users': mapped_users,
            'unmapped_users': unmapped_users,
            'admin_users': admin_count,
            'producer_users': producer_count,
            'regular_users': regular_count,
            'toggl_mapped': toggl_mapped,
            'timetastic_mapped': timetastic_mapped,
            'slack_mapped': slack_mapped,
            'mapping_percentage': (mapped_users / total_users * 100) if total_users > 0 else 0
        }
