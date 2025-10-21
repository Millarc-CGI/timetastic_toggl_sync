"""
Toggl Track API connection and functionality tests.

Tests:
1. Connection verification
2. Get user info (me)
3. List projects
4. Get time entries for specific date range
"""

import os
import sys
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_settings
import requests
import base64


class TogglTester:
    def __init__(self):
        self.settings = load_settings()
        self.base_url = self.settings.toggl_base_url
        self.token = self.settings.toggl_api_token
        self.workspace_id = self.settings.workspace_id
        
    def _auth_header(self) -> Dict[str, str]:
        """Toggl Track uses Basic Auth: <api_token>:api_token (base64)."""
        token_bytes = f"{self.token}:api_token".encode("utf-8")
        return {
            "Authorization": "Basic " + base64.b64encode(token_bytes).decode("ascii"),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    
    def test_connection(self) -> bool:
        """Test Toggl API connection by getting user info."""
        try:
            print("🔗 Testing Toggl connection...")
            url = f"{self.base_url}/me"
            response = requests.get(url, headers=self._auth_header(), timeout=60)
            response.raise_for_status()
            user_info = response.json()
            
            print(f"✅ Connection successful!")
            print(f"   User: {user_info.get('fullname', 'Unknown')}")
            print(f"   Email: {user_info.get('email', 'Unknown')}")
            print(f"   Workspace: {user_info.get('default_workspace_id', 'Unknown')}")
            return True
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False
    
    def get_user_info(self) -> Optional[Dict[str, Any]]:
        """Get detailed user information."""
        try:
            print("\n👤 Fetching user information...")
            url = f"{self.base_url}/me"
            response = requests.get(url, headers=self._auth_header(), timeout=60)
            response.raise_for_status()
            user_info = response.json()
            
            print(f"✅ User details:")
            print(f"   Name: {user_info.get('fullname', 'Unknown')}")
            print(f"   Email: {user_info.get('email', 'Unknown')}")
            print(f"   Default Workspace ID: {user_info.get('default_workspace_id', 'Unknown')}")
            print(f"   Workspace: {user_info.get('default_workspace_name', 'Unknown')}")
            
            return user_info
        except Exception as e:
            print(f"❌ Failed to fetch user info: {e}")
            return None
    
    def get_projects(self) -> List[Dict[str, Any]]:
        """Get list of all projects in the workspace."""
        try:
            print("\n📁 Fetching projects list...")
            
            # Get workspaces first
            workspaces_url = f"{self.base_url}/workspaces"
            response = requests.get(workspaces_url, headers=self._auth_header(), timeout=60)
            response.raise_for_status()
            workspaces = response.json()
            
            if not workspaces:
                print("❌ No workspaces found")
                return []
            
            workspace_id = self.workspace_id or workspaces[0]['id']
            print(f"   Using workspace ID: {workspace_id}")
            
            # Get projects for the workspace
            projects_url = f"{self.base_url}/workspaces/{workspace_id}/projects"
            response = requests.get(projects_url, headers=self._auth_header(), timeout=60)
            response.raise_for_status()
            projects = response.json()
            
            print(f"✅ Found {len(projects)} projects:")
            for project in projects:
                if project.get('active', True):
                    print(f"   • {project.get('name', 'Unknown')} - 🟢 Active")
                    print(f"     ID: {project.get('id')}")
            
            return projects
        except Exception as e:
            print(f"❌ Failed to fetch projects: {e}")
            return []
    
    def get_time_entries_for_range(self, start_date: str, end_date: str) -> List[Dict[str, Any]]:
        """Get time entries for a specific date range."""
        try:
            print(f"\n⏰ Fetching time entries from {start_date} to {end_date}...")
            
            # Convert dates to ISO format if needed
            start_iso = start_date if 'T' in start_date else f"{start_date}T00:00:00Z"
            end_iso = end_date if 'T' in end_date else f"{end_date}T23:59:59Z"
            
            url = f"{self.base_url}/me/time_entries"
            params = {"start_date": start_iso, "end_date": end_iso}
            if self.workspace_id:
                params["workspace_id"] = self.workspace_id
                
            response = requests.get(url, headers=self._auth_header(), params=params, timeout=120)
            response.raise_for_status()
            time_entries = response.json()
            
            print(f"✅ Found {len(time_entries)} time entries:")
            
            total_duration = 0
            for entry in time_entries:
                duration = entry.get('duration', 0)
                if duration > 0:  # Only count running entries
                    total_duration += duration
                
                description = entry.get('description', 'No description')
                project_name = entry.get('project', {}).get('name', 'Unknown') if entry.get('project') else 'Unknown'
                start_time = entry.get('start', 'Unknown')
                
                # Convert duration from seconds to hours
                hours = duration / 3600 if duration > 0 else 0
                
                print(f"   • {description}")
                print(f"     Project: {project_name}")
                print(f"     Start: {start_time}")
                print(f"     Duration: {hours:.2f} hours")
                print()
            
            total_hours = total_duration / 3600
            print(f"📊 Total tracked time: {total_hours:.2f} hours")
            
            return time_entries
        except Exception as e:
            print(f"❌ Failed to fetch time entries: {e}")
            return []
    
    def get_workspaces(self) -> List[Dict[str, Any]]:
        """Get list of available workspaces."""
        try:
            print("\n🏢 Fetching workspaces...")
            
            workspaces_url = f"{self.base_url}/workspaces"
            response = requests.get(workspaces_url, headers=self._auth_header(), timeout=60)
            response.raise_for_status()
            workspaces = response.json()
            
            print(f"✅ Found {len(workspaces)} workspaces:")
            for workspace in workspaces:
                print(f"   • {workspace.get('name', 'Unknown')} - ID: {workspace.get('id')}")
            
            return workspaces
        except Exception as e:
            print(f"❌ Failed to fetch workspaces: {e}")
            return []


def main():
    """Run all Toggl tests."""
    print("🚀 Starting Toggl Track API Tests")
    print("=" * 50)
    
    tester = TogglTester()
    
    # Test 1: Connection
    if not tester.test_connection():
        print("❌ Connection test failed. Exiting.")
        return
    
    # Test 2: User info
    user_info = tester.get_user_info()
    if not user_info:
        print("❌ Failed to fetch user info. Exiting.")
        return
    
    # Test 3: Get workspaces
    workspaces = tester.get_workspaces()
    
    # Test 4: Get projects
    #projects = tester.get_projects()
    
    # Test 5: Get time entries for last month (October 1-16, 2025 as requested)
    start_date = "2025-10-15"
    end_date = "2025-10-16"
    
    # Allow override via environment variables
    start_date = os.getenv("TOGGL_TEST_START_DATE", start_date)
    end_date = os.getenv("TOGGL_TEST_END_DATE", end_date)
    
    time_entries = tester.get_time_entries_for_range(start_date, end_date)
    
    print("\n" + "=" * 50)
    print("🎉 Toggl tests completed!")
    print(f"\n💡 To test with different date range, set environment variables:")
    print(f"   export TOGGL_TEST_START_DATE=2025-10-01")
    print(f"   export TOGGL_TEST_END_DATE=2025-10-16")


if __name__ == "__main__":
    main()
