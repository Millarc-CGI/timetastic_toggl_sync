"""
Slack API service for notifications and messaging.
"""

try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
except ImportError:
    import sys
    print("Error: slack_sdk not installed. Install with: pip install slack_sdk")
    sys.exit(1)
import os
from typing import List, Dict, Any, Optional
from datetime import datetime, date
from pathlib import Path

from ..config import Settings


class SlackService:
    """Service for interacting with Slack API."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = WebClient(token=settings.slack_bot_token)
        self.bot_name = settings.slack_default_sender_name
        self.fallback_channel = settings.slack_dm_fallback_channel
    
    def test_connection(self) -> bool:
        """Test connection to Slack API."""
        try:
            response = self.client.auth_test()
            return response.get('ok', False)
        except SlackApiError:
            return False
    
    def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user information by Slack user ID."""
        try:
            response = self.client.users_info(user=user_id)
            return response.get('user')
        except SlackApiError:
            return None
    
    def get_users(self) -> List[Dict[str, Any]]:
        """Get list of all users in the workspace."""
        try:
            response = self.client.users_list()
            return response.get('members', [])
        except SlackApiError:
            return []
    
    def find_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Find user by email address."""
        try:
            users = self.get_users()
            for user in users:
                profile = user.get('profile', {})
                if profile.get('email', '').lower() == email.lower():
                    return user
            return None
        except Exception:
            return None
    
    def send_dm(self, user_id: str, message: str, blocks: Optional[List[Dict[str, Any]]] = None) -> bool:
        """Send direct message to user."""
        try:
            response = self.client.chat_postMessage(
                channel=user_id,
                text=message,
                username=self.bot_name,
                blocks=blocks
            )
            return response.get('ok', False)
        except SlackApiError as e:
            print(f"Failed to send DM to {user_id}: {e}")
            return False
    
    def send_channel_message(self, channel: str, message: str, blocks: Optional[List[Dict[str, Any]]] = None) -> bool:
        """Send message to channel."""
        try:
            response = self.client.chat_postMessage(
                channel=channel,
                text=message,
                username=self.bot_name,
                blocks=blocks
            )
            return response.get('ok', False)
        except SlackApiError as e:
            print(f"Failed to send message to {channel}: {e}")
            return False
    
    def send_missing_entries_reminder(
        self, 
        user_email: str, 
        missing_days: List[date],
        days_to_check: int = 7
    ) -> bool:
        """Send reminder about missing time entries."""
        user = self.find_user_by_email(user_email)
        if not user:
            print(f"Slack user not found for email: {user_email}")
            return False
        
        user_id = user['id']
        display_name = user.get('profile', {}).get('display_name', user_email)
        
        if not missing_days:
            return True  # No missing entries
        
        # Create message
        missing_dates_str = "\n".join([f"• {day.strftime('%Y-%m-%d (%A)')}" for day in missing_days])
        
        message = f"""⏰ *Missing Time Entries Reminder*

Hi {display_name}! 

I noticed you haven't logged time entries for the following days in the last {days_to_check} days:

{missing_dates_str}

Please log your time entries in Toggl Track to ensure accurate reporting.

Need help? Contact your administrator or check the Toggl Track documentation.

---
*This is an automated message from {self.bot_name}*"""
        
        return self.send_dm(user_id, message)
    
    def send_monthly_report(self, user_email: str, report_data: Dict[str, Any]) -> bool:
        """Send monthly/weekly report to user."""
        user = self.find_user_by_email(user_email)
        if not user:
            print(f"Slack user not found for email: {user_email}")
            return False
        
        user_id = user['id']
        display_name = user.get('profile', {}).get('display_name', user_email)
        
        # Create message
        period = report_data.get('period_label') or report_data.get('period') or 'Unknown'
        report_type = report_data.get('report_type', 'monthly').title()
        total_hours = report_data.get('total_hours', 0)
        weekly_ot = report_data.get('weekly_overtime', 0)
        monthly_ot = report_data.get('monthly_overtime', 0)
        missing_days = report_data.get('missing_days', [])
        
        message = f"""📊 *{report_type} Time Report - {period}*

Hi {display_name}!

Here's your time tracking summary for {period}:

⏰ *Hours Worked*
• Total Hours: {total_hours:.1f}h
"""
        
        if weekly_ot or monthly_ot:
            message += "\n⏱️ *Overtime*\n"
            if weekly_ot:
                message += f"• Weekly Overtime: {weekly_ot:.1f}h\n"
            if monthly_ot:
                message += f"• Monthly Overtime: {monthly_ot:.1f}h\n"
        
        projects = report_data.get('projects_worked', [])
        if projects:
            message += "\n📁 *Projects*\n"
            for project in projects:
                message += f"• {project}\n"
        
        if missing_days:
            message += "\n⚠️ *Missing Entries*\n"
            for day in missing_days[:5]:
                message += f"• {day}\n"
            if len(missing_days) > 5:
                message += f"• ... and {len(missing_days) - 5} more\n"
        
        message += f"\n---\n*Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n*This is an automated message from {self.bot_name}*"
        
        return self.send_dm(user_id, message)
    
    def send_admin_notification(
        self, 
        message: str, 
        include_admins: Optional[List[str]] = None
    ) -> bool:
        """Send notification to admins."""
        if not include_admins:
            # Get admin emails from config
            admin_emails = self.settings.admin_emails
        else:
            admin_emails = include_admins
        
        if not admin_emails:
            return False
        
        success = True
        for email in admin_emails:
            user = self.find_user_by_email(email)
            if user:
                user_id = user['id']
                if not self.send_dm(user_id, f"🔔 *Admin Notification*\n\n{message}"):
                    success = False
            else:
                print(f"Admin user not found in Slack: {email}")
                success = False
        
        return success
    
    def send_producer_notification(
        self, 
        message: str, 
        include_producers: Optional[List[str]] = None
    ) -> bool:
        """Send notification to producers."""
        if not include_producers:
            # Get producer emails from config
            producer_emails = self.settings.producer_emails
        else:
            producer_emails = include_producers
        
        if not producer_emails:
            return False
        
        success = True
        for email in producer_emails:
            user = self.find_user_by_email(email)
            if user:
                user_id = user['id']
                if not self.send_dm(user_id, f"📈 *Producer Update*\n\n{message}"):
                    success = False
            else:
                print(f"Producer user not found in Slack: {email}")
                success = False
        
        return success
    
    def send_sync_completion_notification(
        self, 
        sync_stats: Dict[str, Any],
        errors: Optional[List[str]] = None
    ) -> bool:
        """Send notification about sync completion."""
        message = f"""🔄 *Sync Completed*

*Statistics:*
• Toggl entries processed: {sync_stats.get('toggl_entries', 0)}
• Timetastic absences processed: {sync_stats.get('timetastic_absences', 0)}
• Users synchronized: {sync_stats.get('users_synced', 0)}
• Reports generated: {sync_stats.get('reports_generated', 0)}

"""
        
        if errors:
            message += f"⚠️ *Errors encountered:* {len(errors)}\n"
            for error in errors[:3]:  # Show first 3 errors
                message += f"• {error}\n"
            if len(errors) > 3:
                message += f"• ... and {len(errors) - 3} more errors\n"
        
        message += f"\n*Completed at:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        
        return self.send_admin_notification(message)
    
    def send_test_message(self, user_id: str, custom_message: Optional[str] = None) -> bool:
        """Send test message to verify Slack integration."""
        user_info = self.get_user_info(user_id)
        if not user_info:
            return False
        
        display_name = user_info.get('profile', {}).get('display_name', 'Unknown')
        
        message = custom_message or f"""🧪 *Test Message*

Hello {display_name}! This is a test message from {self.bot_name}.

If you're receiving this message, the Slack integration is working correctly.

*Test completed at:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        
        return self.send_dm(user_id, message)
    
    def send_file_dm(
        self, 
        user_id: str, 
        file_path: str, 
        message: str,
        title: Optional[str] = None
    ) -> bool:
        """Send file as direct message to user."""
        # Check if file exists
        if not os.path.exists(file_path):
            print(f"❌ File not found: {file_path}")
            return False
        
        try:
            # Open DM conversation to get channel ID
            conv_response = self.client.conversations_open(users=user_id)
            if not conv_response.get('ok'):
                print(f"❌ Failed to open DM conversation with {user_id}: {conv_response.get('error')}")
                return False
            
            channel_id = conv_response['channel']['id']
            
            # Upload file using channel ID
            with open(file_path, 'rb') as file_content:
                response = self.client.files_upload_v2(
                    channel=channel_id,
                    file=file_content,
                    filename=os.path.basename(file_path),
                    title=title or os.path.basename(file_path),
                    initial_comment=message
                )
                return response.get('ok', False)
        except SlackApiError as e:
            print(f"❌ Failed to send file to {user_id}: {e}")
            return False
        except Exception as e:
            print(f"❌ Error sending file to {user_id}: {e}")
            return False
    
    def send_admin_report(
        self,
        admin_email: str,
        file_path: str,
        year: int,
        month: int
    ) -> bool:
        """Send admin report file to admin user."""
        # Check if file exists
        if not os.path.exists(file_path):
            print(f"❌ Admin report file not found: {file_path}")
            return False
        
        # Find user by email
        user = self.find_user_by_email(admin_email)
        if not user:
            print(f"⚠️ Admin user not found in Slack for email: {admin_email}")
            return False
        
        user_id = user['id']
        user_name = user.get('real_name') or user.get('name', 'Admin')
        
        message = f"📊 Monthly user report ({year}-{month:02d}) is ready. You can download it below."
        
        print(f"📤 Sending admin report to {user_name} ({admin_email}) - Slack ID: {user_id}")
        
        return self.send_file_dm(
            user_id=user_id,
            file_path=file_path,
            message=message,
            title=f"Admin Report {year}-{month:02d}"
        )
