"""
Toggl Track API service.
"""

import base64
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime

from ..config import Settings
from ..models.time_entry import TimeEntry


class TogglService:
    """Service for interacting with Toggl Track API."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.toggl_base_url
        self.token = settings.toggl_api_token
        self.workspace_id = settings.workspace_id
    
    def _auth_header(self) -> Dict[str, str]:
        """Generate Toggl API authentication header."""
        token_bytes = f"{self.token}:api_token".encode("utf-8")
        return {
            "Authorization": "Basic " + base64.b64encode(token_bytes).decode("ascii"),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    
    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Make authenticated request to Toggl API and return JSON payload (object or list)."""
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        
        try:
            response = requests.get(url, headers=self._auth_header(), params=params or {}, timeout=120)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Toggl API request failed: {e}")
    
    def test_connection(self) -> bool:
        """Test connection to Toggl API."""
        try:
            self.get_user_info()
            return True
        except Exception:
            return False
    
    def get_user_info(self) -> Dict[str, Any]:
        """Get current user information."""
        return self._make_request("/me")
    
    def get_workspaces(self) -> List[Dict[str, Any]]:
        """Get list of workspaces."""
        return self._make_request("/workspaces")
    
    def get_projects(self, workspace_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get list of projects in workspace."""
        workspace = workspace_id or self.workspace_id
        if not workspace:
            raise ValueError("Workspace ID is required")
        
        return self._make_request(f"/workspaces/{workspace}/projects")
    
    def get_workspace_users(self, workspace_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get list of users in workspace."""
        workspace = workspace_id or self.workspace_id
        if not workspace:
            raise ValueError("Workspace ID is required")
        
        return self._make_request(f"/workspaces/{workspace}/users")
    
    def get_time_entries(
        self,
        start_date: str,
        end_date: str,
        workspace_id: Optional[int] = None,
        user_ids: Optional[List[int]] = None,
    ) -> List[TimeEntry]:
        """
        Get time entries for a date range across a workspace, optionally filtered by users.

        Uses Toggl Track API v9 endpoint:
          GET /workspaces/{workspace_id}/time_entries?start_date=...&end_date=...&user_ids=1,2

        Args:
            start_date: Start date in ISO 8601 UTC (e.g., "2025-10-01T00:00:00Z")
            end_date: End date in ISO 8601 UTC (e.g., "2025-10-31T23:59:59Z")
            workspace_id: Workspace ID. Defaults to settings.workspace_id
            user_ids: Optional list of Toggl user IDs to filter
        """
        workspace = workspace_id or self.workspace_id
        if not workspace:
            raise ValueError("Workspace ID is required")

        params: Dict[str, Any] = {
            "start_date": start_date,
            "end_date": end_date,
        }
        if user_ids:
            params["user_ids"] = ",".join(str(u) for u in user_ids)

        entries_data = self._make_request(f"/workspaces/{workspace}/time_entries", params)

        # Convert to TimeEntry objects
        entries: List[TimeEntry] = []
        for entry_data in entries_data or []:
            try:
                entry = TimeEntry.from_toggl_data(entry_data)
                entries.append(entry)
            except Exception as e:
                # Log error but continue with other entries
                print(f"Warning: Failed to parse time entry {entry_data.get('id', 'unknown')}: {e}")
                continue

        return entries
    
    def get_user_time_entries(
        self,
        user_id: int,
        start_date: str,
        end_date: str,
        workspace_id: Optional[int] = None
    ) -> List[TimeEntry]:
        """Get time entries for specific user."""
        workspace = workspace_id or self.workspace_id
        if not workspace:
            raise ValueError("Workspace ID is required")
        
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "user_ids": str(user_id)
        }
        
        entries_data = self._make_request(f"/workspaces/{workspace}/time_entries", params)
        
        # Convert to TimeEntry objects
        entries = []
        for entry_data in entries_data:
            try:
                entry = TimeEntry.from_toggl_data(entry_data)
                entries.append(entry)
            except Exception as e:
                print(f"Warning: Failed to parse time entry {entry_data.get('id', 'unknown')}: {e}")
                continue
        
        return entries
    
    def get_project_time_entries(
        self,
        project_id: int,
        start_date: str,
        end_date: str,
        workspace_id: Optional[int] = None
    ) -> List[TimeEntry]:
        """Get time entries for specific project."""
        workspace = workspace_id or self.workspace_id
        if not workspace:
            raise ValueError("Workspace ID is required")
        
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "project_ids": str(project_id)
        }
        
        entries_data = self._make_request(f"/workspaces/{workspace}/time_entries", params)
        
        # Convert to TimeEntry objects
        entries = []
        for entry_data in entries_data:
            try:
                entry = TimeEntry.from_toggl_data(entry_data)
                entries.append(entry)
            except Exception as e:
                print(f"Warning: Failed to parse time entry {entry_data.get('id', 'unknown')}: {e}")
                continue
        
        return entries
    
    def get_current_time_entry(self) -> Optional[TimeEntry]:
        """Get currently running time entry."""
        try:
            entry_data = self._make_request("/me/time_entries/current")
            if entry_data:
                return TimeEntry.from_toggl_data(entry_data)
            return None
        except Exception:
            return None
    
    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Find user by email address."""
        try:
            users = self.get_workspace_users()
            for user in users:
                if user.get('email', '').lower() == email.lower():
                    return user
            return None
        except Exception:
            return None
