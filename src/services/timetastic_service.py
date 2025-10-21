"""
Timetastic API service.
"""

import requests
from typing import List, Dict, Any, Optional
from datetime import datetime, date

from ..config import Settings
from ..models.absence import Absence


class TimetasticService:
    """Service for interacting with Timetastic API."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.timetastic_base_url
        self.token = settings.timetastic_api_token
    
    def _auth_header(self) -> Dict[str, str]:
        """Generate Timetastic API authentication header."""
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json"
        }
    
    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Make authenticated request to Timetastic API."""
        if not self.token:
            raise RuntimeError("TIMETASTIC_API_TOKEN is not set")
        
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        
        try:
            response = requests.get(url, headers=self._auth_header(), params=params or {}, timeout=90)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Timetastic API request failed: {e}")
    
    def test_connection(self) -> bool:
        """Test connection to Timetastic API."""
        try:
            # Try to get users as a connection test
            self._make_request("/users", {"PageSize": 1})
            return True
        except Exception:
            return False
    
    def get_users(self) -> List[Dict[str, Any]]:
        """Get list of all users in the organization."""
        users = []
        page = 1
        
        while True:
            params = {"PageNumber": page, "PageSize": 100}
            data = self._make_request("/users", params=params)
            
            # Handle different response formats
            if isinstance(data, list):
                page_users = data
            else:
                page_users = data.get("users", []) or data.get("items", [])
            
            if not page_users:
                break
            
            users.extend(page_users)
            
            # If we got fewer users than requested, we're done
            if len(page_users) < 100:
                break
            
            page += 1
        
        return users
    
    def get_user(self, user_id: int) -> Dict[str, Any]:
        """Get detailed information for a specific user."""
        return self._make_request(f"/users/{user_id}")
    
    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Find user by email address."""
        try:
            users = self.get_users()
            for user in users:
                user_email = user.get('email') or user.get('Email', '')
                if user_email.lower() == email.lower():
                    return user
            return None
        except Exception:
            return None
    
    def get_holidays(
        self,
        start_date: str,
        end_date: str,
        user_ids: Optional[List[int]] = None,
        status: str = "Approved"
    ) -> List[Absence]:
        """
        Get holidays for date range.
        
        Args:
            start_date: Start date in ISO format (e.g., "2025-10-01T00:00:00Z")
            end_date: End date in ISO format (e.g., "2025-10-16T23:59:59Z")
            user_ids: Optional list of user IDs to filter
            status: Holiday status filter (default: "Approved")
        """
        params = {
            "Start": start_date,
            "End": end_date,
            "Status": status
        }
        
        if user_ids:
            params["UsersIds"] = ",".join(str(x) for x in user_ids)
        
        # Fetch holidays with pagination
        all_holidays = []
        page = 1
        
        while True:
            params["PageNumber"] = page
            data = self._make_request("/holidays", params=params)
            
            # Handle different response formats
            if isinstance(data, list):
                holidays = data
            else:
                holidays = data.get("holidays", []) or data.get("items", [])
            
            if not holidays:
                break
            
            all_holidays.extend(holidays)
            
            # If we got fewer holidays than requested, we're done
            if len(holidays) < 100:
                break
            
            page += 1
        
        # Convert to Absence objects
        absences = []
        for holiday_data in all_holidays:
            try:
                absence = Absence.from_timetastic_data(holiday_data)
                absences.append(absence)
            except Exception as e:
                print(f"Warning: Failed to parse holiday {holiday_data.get('id', 'unknown')}: {e}")
                continue
        
        return absences
    
    def get_leave_types(self) -> List[Dict[str, Any]]:
        """Get list of available leave types."""
        data = self._make_request("/holidaytypes")
        
        # Handle different response formats
        if isinstance(data, list):
            return data
        else:
            return data.get("holidayTypes", []) or data.get("items", [])
    
    def get_user_holidays(
        self,
        user_id: int,
        start_date: str,
        end_date: str,
        status: str = "Approved"
    ) -> List[Absence]:
        """Get holidays for specific user."""
        return self.get_holidays(start_date, end_date, [user_id], status)
    
    def get_departments(self) -> List[Dict[str, Any]]:
        """Get list of departments."""
        try:
            data = self._make_request("/departments")
            
            # Handle different response formats
            if isinstance(data, list):
                return data
            else:
                return data.get("departments", []) or data.get("items", [])
        except Exception:
            return []
    
    def get_user_allowance(self, user_id: int, year: int) -> Dict[str, Any]:
        """Get user's holiday allowance for a specific year."""
        try:
            return self._make_request(f"/users/{user_id}/allowance/{year}")
        except Exception:
            return {}
    
    def search_users(self, query: str) -> List[Dict[str, Any]]:
        """Search users by name or email."""
        try:
            users = self.get_users()
            query_lower = query.lower()
            
            results = []
            for user in users:
                # Check name fields
                first_name = user.get('firstName', '') or user.get('FirstName', '')
                last_name = user.get('lastName', '') or user.get('LastName', '')
                full_name = f"{first_name} {last_name}".lower()
                
                # Check email
                email = user.get('email', '') or user.get('Email', '')
                
                if (query_lower in full_name or 
                    query_lower in email.lower() or
                    query_lower in first_name.lower() or
                    query_lower in last_name.lower()):
                    results.append(user)
            
            return results
        except Exception:
            return []
