"""
Slack API connection and functionality tests.

Tests:
1. Connection verification
2. List all users
3. Send test message to specific user
"""

import os
import sys
from typing import Dict, List, Any, Optional

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_settings

try:
    from slack_sdk import WebClient
    from slack_sdk.errors import SlackApiError
except ImportError:
    print("Error: slack_sdk not installed. Install with: pip install slack_sdk")
    sys.exit(1)


class SlackTester:
    def __init__(self):
        self.settings = load_settings()
        self.client = WebClient(token=self.settings.slack_bot_token)
        
    def test_connection(self) -> bool:
        """Test Slack API connection by getting bot info."""
        try:
            print("🔗 Testing Slack connection...")
            response = self.client.auth_test()
            print(f"✅ Connection successful!")
            print(f"   Bot: {response['user']}")
            print(f"   Team: {response['team']}")
            print(f"   URL: {response['url']}")
            return True
        except SlackApiError as e:
            print(f"❌ Connection failed: {e.response['error']}")
            return False
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return False
    
    def list_users(self) -> List[Dict[str, Any]]:
        """Get list of all users in the workspace."""
        try:
            print("\n👥 Fetching user list...")
            response = self.client.users_list()
            users = response['members']
            
            print(f"✅ Found {len(users)} users:")
            for user in users:
                if not user.get('deleted', False) and not user.get('is_bot', False):
                    profile = user.get('profile', {})
                    print(f"   • {profile.get('display_name', profile.get('real_name', 'Unknown'))} "
                          f"({profile.get('email', 'no email')}) - ID: {user['id']}")
            
            return users
        except SlackApiError as e:
            print(f"❌ Failed to fetch users: {e.response['error']}")
            return []
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return []
    
    def send_test_message(self, user_id: str, message: str = "Test message from Timetastic-Toggl sync bot \nHELLO, {user_name}! THIS IS A TEST MESSAGE!") -> bool:
        """Send a test message to a specific user."""
        try:
            print(f"\n📤 Sending test message to user {user_id}...")
            user_name = self.client.users_info(user=user_id)['user']['profile']['display_name']
            response = self.client.chat_postMessage(
                channel=user_id,
                text=message.format(user_name=user_name),
                username=self.settings.slack_default_sender_name
            )
            
            if response['ok']:
                print(f"✅ Message sent successfully!")
                print(f"   Message: {message}")
                print(f"   Timestamp: {response['ts']}")
                return True
            else:
                print(f"❌ Failed to send message: {response}")
                return False
                
        except SlackApiError as e:
            print(f"❌ Failed to send message: {e.response['error']}")
            return False
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            return False
    
    def find_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Find user by email address."""
        try:
            users = self.list_users()
            for user in users:
                profile = user.get('profile', {})
                if profile.get('email', '').lower() == email.lower():
                    return user
            return None
        except Exception as e:
            print(f"❌ Error finding user: {e}")
            return None


def main():
    """Run all Slack tests."""
    print("🚀 Starting Slack API Tests")
    print("=" * 50)
    
    tester = SlackTester()
    
    # Test 1: Connection
    if not tester.test_connection():
        print("❌ Connection test failed. Exiting.")
        return
    
    # Test 2: List users
    '''
    users = tester.list_users()
    if not users:
        print("❌ Failed to fetch users. Exiting.")
        return
    '''
    # Test 3: Send test message (if user ID provided)
    test_user_id = os.getenv("SLACK_TEST_USER_ID", "U03QS4ZG16U") # Valhanna's ID
    #test_user_id = os.getenv("SLACK_TEST_USER_ID", "U040ZH26KH6") # Dominik's ID

    if test_user_id:
        tester.send_test_message(test_user_id)
    else:
        print("\n💡 To test message sending, set SLACK_TEST_USER_ID environment variable")
        print("   Example: export SLACK_TEST_USER_ID=U1234567890")
        
        # Try to find a user by email if provided
        test_email = os.getenv("SLACK_TEST_EMAIL", "")
        if test_email:
            print(f"\n🔍 Looking for user with email: {test_email}")
            user = tester.find_user_by_email(test_email)
            if user:
                print(f"✅ Found user: {user.get('profile', {}).get('display_name', 'Unknown')}")
                tester.send_test_message(user['id'])
            else:
                print(f"❌ User with email {test_email} not found")
    
    print("\n" + "=" * 50)
    print("🎉 Slack tests completed!")


if __name__ == "__main__":
    main()
