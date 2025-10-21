"""
Timetastic API connection and functionality tests.

Tests:
1. Connection verification
2. Get user information
3. Get holidays for specific date range
"""

import os
import sys
from typing import Dict, List, Any, Optional

# Add parent directory to path to import config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import load_settings
import requests


class TimetasticTester:
    def __init__(self):
        self.settings = load_settings()
        self.base_url = self.settings.timetastic_base_url
        self.token = self.settings.timetastic_api_token
        
    def _auth_header(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
    
    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Make authenticated GET request to Timetastic API."""
        import requests
        if not self.token:
            raise RuntimeError("TIMETASTIC_API_TOKEN is not set")
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        r = requests.get(url, headers=self._auth_header(), params=params or {}, timeout=90)
        r.raise_for_status()
        return r.json()
    
    def test_connection(self) -> bool:
        """Test Timetastic API connection by making a simple request."""
        try:
            print("🔗 Testing Timetastic connection...")
            
            # Try to get users list as a connection test
            users = self._get("/users", {"PageSize": 1})
            print(f"✅ Connection successful!")
            return True
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False
    
    def get_users(self) -> List[Dict[str, Any]]:
        """Get list of all users in the organization."""
        try:
            print("\n👥 Fetching users list...")
            
            users = []
            page = 1
            
            while True:
                params = {"PageNumber": page, "PageSize": 100}
                data = self._get("/users", params=params)
                
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
            
            print(f"✅ Found {len(users)} users:")
            for user in users:
                # Handle different field names
                first_name = user.get('firstName') or user.get('FirstName') or user.get('first_name', '')
                last_name = user.get('lastName') or user.get('LastName') or user.get('last_name', '')
                email = user.get('email') or user.get('Email', '')
                user_id = user.get('id') or user.get('Id', '')
                department = user.get('department', {})
                
                # Handle department as object or string
                dept_name = 'Unknown'
                if isinstance(department, dict):
                    dept_name = department.get('name') or department.get('Name', 'Unknown')
                elif isinstance(department, str):
                    dept_name = department
                
                full_name = f"{first_name} {last_name}".strip()
                if not full_name:
                    full_name = 'Unknown'
                
                print(f"   • {full_name} ({email}) - ID: {user_id}")
                print(f"     Department: {dept_name}")
            
            return users
        except Exception as e:
            print(f"❌ Failed to fetch users: {e}")
            return []
    
    def get_user_details(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed information for a specific user."""
        try:
            print(f"\n👤 Fetching details for user ID {user_id}...")
            
            url = f"{self.base_url}/users/{user_id}"
            response = requests.get(url, headers=self._auth_header(), timeout=90)
            response.raise_for_status()
            data = response.json()
            
            # Extract user details with case-insensitive field handling
            first_name = data.get('firstName') or data.get('FirstName') or data.get('first_name', '')
            last_name = data.get('lastName') or data.get('LastName') or data.get('last_name', '')
            email = data.get('email') or data.get('Email', 'Unknown')
            department = data.get('department', {})
            current_year_allowance = data.get('currentYearAllowance') or data.get('CurrentYearAllowance', 'Unknown')
            allowance_remaining = data.get('allowanceRemaining') or data.get('AllowanceRemaining', 'Unknown')
            
            # Handle department as object or string
            dept_name = 'Unknown'
            if isinstance(department, dict):
                dept_name = department.get('name') or department.get('Name', 'Unknown')
            elif isinstance(department, str):
                dept_name = department
            
            user_info = {
                "firstName": first_name,
                "lastName": last_name,
                "email": email,
                "department": dept_name,
                "currentYearAllowance": current_year_allowance,
                "allowanceRemaining": allowance_remaining,
                "raw": data
            }
            
            print(f"✅ User details:")
            print(f"   Name: {first_name} {last_name}")
            print(f"   Email: {email}")
            print(f"   Department: {dept_name}")
            print(f"   Current Year Allowance: {current_year_allowance}")
            print(f"   Allowance Remaining: {allowance_remaining}")
            
            return user_info
        except Exception as e:
            print(f"❌ Failed to fetch user details: {e}")
            return None
    
    def get_holidays_for_range(self, start_date: str, end_date: str, user_ids: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        """Get holidays for a specific date range."""
        try:
            print(f"\n🏖️ Fetching holidays from {start_date} to {end_date}...")
            
            # Convert dates to ISO format if needed
            start_iso = start_date if 'T' in start_date else f"{start_date}T00:00:00Z"
            end_iso = end_date if 'T' in end_date else f"{end_date}T23:59:59Z"
            
            # Build parameters for API request
            params = {
                "Start": start_iso,
                "End": end_iso,
                "Status": "Approved"
            }
            if user_ids:
                params["UsersIds"] = ",".join(str(x) for x in user_ids)
            
            # Fetch holidays with pagination
            all_holidays = []
            page = 1
            
            while True:
                params["PageNumber"] = page
                url = f"{self.base_url}/holidays"
                response = requests.get(url, headers=self._auth_header(), params=params, timeout=90)
                response.raise_for_status()
                data = response.json()
                
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
            
            print(f"✅ Found {len(all_holidays)} holidays:")
            
            # Simple cache for user details to avoid repeated API calls
            user_cache = {}
            
            for holiday in all_holidays:
                # Extract holiday details
                holiday_type = holiday.get('type', {}).get('name', 'Unknown') if holiday.get('type') else 'Unknown'
                start_date_holiday = holiday.get('startDate', 'Unknown')
                end_date_holiday = holiday.get('endDate', 'Unknown')
                status = holiday.get('status', 'Unknown')
                
                # Get user ID from holiday
                user_id = holiday.get('userId') or holiday.get('UserId') or holiday.get('user_id')
                
                # Get user details (with caching)
                user_name = 'Unknown'
                user_email = 'Unknown'
                if user_id:
                    if user_id not in user_cache:
                        try:
                            user_details = self.get_user_details(user_id)
                            if user_details:
                                user_cache[user_id] = {
                                    'name': f"{user_details.get('firstName', '')} {user_details.get('lastName', '')}".strip(),
                                    'email': user_details.get('email', 'Unknown')
                                }
                            else:
                                user_cache[user_id] = {'name': 'Unknown', 'email': 'Unknown'}
                        except:
                            user_cache[user_id] = {'name': 'Unknown', 'email': 'Unknown'}
                    
                    cached_user = user_cache[user_id]
                    user_name = cached_user['name']
                    user_email = cached_user['email']
                
                print(f"   • {holiday_type} - {user_name} ({user_email})")
                print(f"     Period: {start_date_holiday} to {end_date_holiday}")
                print(f"     Status: {status}")
                print()
            
            # Summary by type
            type_counts = {}
            for holiday in all_holidays:
                holiday_type = holiday.get('type', {}).get('name', 'Unknown') if holiday.get('type') else 'Unknown'
                type_counts[holiday_type] = type_counts.get(holiday_type, 0) + 1
            
            if type_counts:
                print("📊 Summary by holiday type:")
                for holiday_type, count in type_counts.items():
                    print(f"   • {holiday_type}: {count} entries")
            
            return all_holidays
        except Exception as e:
            print(f"❌ Failed to fetch holidays: {e}")
            return []

    # there is no holiday types request, but LeaveTypes. TO DO edit this part
    def get_holiday_types(self) -> List[Dict[str, Any]]:
        """Get list of available holiday types."""
        try:
            print("\n📋 Fetching holiday types...")
            
            types_data = self._get("/holidaytypes")
            
            # Handle different response formats
            if isinstance(types_data, list):
                holiday_types = types_data
            else:
                holiday_types = types_data.get("holidayTypes", []) or types_data.get("items", [])
            
            print(f"✅ Found {len(holiday_types)} holiday types:")
            for holiday_type in holiday_types:
                name = holiday_type.get('name') or holiday_type.get('Name', 'Unknown')
                type_id = holiday_type.get('id') or holiday_type.get('Id', 'Unknown')
                print(f"   • {name} - ID: {type_id}")
            
            return holiday_types
        except Exception as e:
            print(f"❌ Failed to fetch holiday types: {e}")
            return []


def main():
    """Run all Timetastic tests."""
    print("🚀 Starting Timetastic API Tests")
    print("=" * 50)
    
    tester = TimetasticTester()
    
    # Test 1: Connection
    if not tester.test_connection():
        print("❌ Connection test failed. Exiting.")
        return
    
    # Test 2: Get users
    users = tester.get_users()
    if not users:
        print("❌ Failed to fetch users. Exiting.")
        return
    
    # Test 3: Get holiday types
    holiday_types = tester.get_holiday_types()
    
    # Test 4: Get holidays for specified date range (October 1-16, 2025 as requested)
    start_date = "2025-10-01"
    end_date = "2025-10-16"
    
    # Allow override via environment variables
    start_date = os.getenv("TIMETASTIC_TEST_START_DATE", start_date)
    end_date = os.getenv("TIMETASTIC_TEST_END_DATE", end_date)
    
    # Test for specific user if provided
    test_user_id = os.getenv("TIMETASTIC_TEST_USER_ID")
    user_ids = None
    if test_user_id:
        try:
            user_ids = [int(test_user_id)]
            print(f"\n🎯 Testing for specific user ID: {test_user_id}")
            user_details = tester.get_user_details(user_ids[0])
        except ValueError:
            print(f"❌ Invalid user ID format: {test_user_id}")
            user_ids = None
    
    #holidays = tester.get_holidays_for_range(start_date, end_date, user_ids)
    
    print("\n" + "=" * 50)
    print("🎉 Timetastic tests completed!")
    print(f"\n💡 To test with different parameters, set environment variables:")
    print(f"   export TIMETASTIC_TEST_START_DATE=2025-10-01")
    print(f"   export TIMETASTIC_TEST_END_DATE=2025-10-16")
    print(f"   export TIMETASTIC_TEST_USER_ID={user_ids[0]}")


if __name__ == "__main__":
    main()
