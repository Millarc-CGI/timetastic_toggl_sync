"""
Timetastic API service.
"""

import json
import hashlib
from pathlib import Path
import requests
from dataclasses import replace
from typing import List, Dict, Any, Optional
from datetime import datetime, date, timedelta

from ..config import Settings
from ..models.absence import Absence


class TimetasticService:
    """Service for interacting with Timetastic API."""
    
    def __init__(self, settings: Settings, storage: Optional[Any] = None):
        self.settings = settings
        self.base_url = settings.timetastic_base_url
        self.token = settings.timetastic_api_token
        self._holidays_cache: Dict[str, List[Dict[str, Any]]] = {}
        self._public_holidays_cache: Optional[List[Absence]] = None
        self._users_cache: Optional[List[Dict[str, Any]]] = None
        self._leave_types_cache: Optional[List[Dict[str, Any]]] = None
        self._departments_cache: Optional[List[Dict[str, Any]]] = None
        self.cache_dir = Path(settings.cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._timetastic_cache_dir = self.cache_dir / "timetastic"
        self._timetastic_cache_dir.mkdir(parents=True, exist_ok=True)
        self._holidays_cache_dir = self._timetastic_cache_dir / "holidays"
        self._holidays_cache_dir.mkdir(parents=True, exist_ok=True)
        self.storage = storage  # SQLiteStorage instance for cache metadata
    
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
        if self._users_cache is not None:
            return self._users_cache
        
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
        
        self._users_cache = users
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
    ) -> List[Absence]:
        """
        Get holidays for date range.
        
        Args:
            start_date: Start date in ISO format (e.g., "2025-10-01T00:00:00Z")
            end_date: End date in ISO format (e.g., "2025-10-16T23:59:59Z")
            user_ids: Optional list of user IDs to filter
        """
        params = {
            "Start": start_date,
            "End": end_date,
        }
        cache_key = f"{start_date}|{end_date}"
        start_obj = self._parse_iso_to_date(start_date)
        end_obj = self._parse_iso_to_date(end_date)
        cacheable = self._is_cacheable_range(start_obj, end_obj)
        disk_cache_path: Optional[Path] = None
        raw_holidays: List[Dict[str, Any]] = []
        should_fetch = True
        
        # Check cache metadata if cacheable and storage is available
        if cacheable and start_obj and end_obj and self.storage:
            disk_cache_path = self._holidays_cache_path(start_obj, end_obj)
            
            # Get cache metadata for the month (use workspace_id=0 for Timetastic as it's org-wide)
            year = start_obj.year
            month = start_obj.month
            cache_metadata = self.storage.get_cache_metadata(0, year, month)
            
            if cache_metadata:
                is_fresh, has_dirty = self._is_cache_fresh(year, month, cache_metadata)
                
                # Use cache if fresh and no dirty ranges
                if is_fresh and not has_dirty:
                    disk_payload = self._load_cached_holidays(disk_cache_path)
                    if disk_payload is not None:
                        raw_holidays = disk_payload
                        self._holidays_cache[cache_key] = raw_holidays
                        should_fetch = False
                elif is_fresh and has_dirty:
                    # Cache is fresh but has dirty ranges - use stale cache but queue refresh
                    disk_payload = self._load_cached_holidays(disk_cache_path)
                    if disk_payload is not None:
                        raw_holidays = disk_payload
                        self._holidays_cache[cache_key] = raw_holidays
                        should_fetch = False
                        # Queue refresh for dirty ranges
                        dirty_ranges = cache_metadata.get('dirty_ranges', [])
                        for dr in dirty_ranges:
                            try:
                                dr_start = datetime.fromisoformat(dr['start']).date()
                                dr_end = datetime.fromisoformat(dr['end']).date()
                                self.storage.add_refresh_job(0, dr_start, dr_end, priority=3)
                            except (ValueError, KeyError):
                                pass
            else:
                # No metadata - try to load from file cache if exists
                disk_payload = self._load_cached_holidays(disk_cache_path)
                if disk_payload is not None:
                    raw_holidays = disk_payload
                    self._holidays_cache[cache_key] = raw_holidays
                    should_fetch = False
        elif cacheable and start_obj and end_obj:
            # Fallback to file cache only if no storage
            disk_cache_path = self._holidays_cache_path(start_obj, end_obj)
            disk_payload = self._load_cached_holidays(disk_cache_path)
            if disk_payload is not None:
                raw_holidays = disk_payload
                self._holidays_cache[cache_key] = raw_holidays
                should_fetch = False

        if not raw_holidays and should_fetch:
            cached = self._holidays_cache.get(cache_key)
            if cached is not None:
                raw_holidays = cached
            else:
                # Fetch holidays with pagination
                raw_holidays = []
                page = 1
                
                while True:
                    params_with_page = {**params, "PageNumber": page}
                    data = self._make_request("/holidays", params=params_with_page)
                    
                    if isinstance(data, list):
                        holidays = data
                    else:
                        holidays = data.get("holidays", []) or data.get("items", [])
                    
                    if not holidays:
                        break
                    
                    raw_holidays.extend(holidays)
                    
                    if len(holidays) < 100:
                        break
                    
                    page += 1
                
                self._holidays_cache[cache_key] = raw_holidays
                
                # Store cache and update metadata if cacheable
                if cacheable and disk_cache_path:
                    self._store_cached_holidays(disk_cache_path, raw_holidays)
                    
                    # Update cache metadata with hash and detect changes
                    if self.storage and start_obj and end_obj:
                        data_hash = self._calculate_data_hash(raw_holidays)
                        year = start_obj.year
                        month = start_obj.month
                        
                        # Check if hash changed (data was modified)
                        existing_metadata = self.storage.get_cache_metadata(0, year, month)
                        if existing_metadata and existing_metadata.get('data_hash'):
                            old_hash = existing_metadata.get('data_hash')
                            if old_hash != data_hash:
                                # Data changed - mark the entire range as dirty for next refresh
                                self.storage.mark_dirty_range(0, start_obj, end_obj)
                        
                        # Update metadata with new hash and clear dirty ranges (since we just refreshed)
                        self.storage.set_cache_metadata(
                            0,  # workspace_id=0 for Timetastic (org-wide)
                            year,
                            month,
                            data_hash=data_hash,
                            clear_dirty=True
                        )
        
        filtered_holidays = self._filter_holidays_by_users(raw_holidays, user_ids)
        
        # Convert to Absence objects
        absences = []
        for holiday_data in filtered_holidays:
            try:
                absence = Absence.from_timetastic_data(holiday_data)
                leave_type = holiday_data.get("leaveType") or holiday_data.get("type") or "Unknown"
                if isinstance(leave_type, dict):
                    leave_type = leave_type.get("name") or leave_type.get("Name") or "Unknown"
                absences.append(absence)
            except Exception as e:
                print(f"Warning: Failed to parse holiday {holiday_data.get('id', 'unknown')}: {e}")
                continue
        
        # Add public holidays - they apply to all users
        # If user_ids specified, add public holidays for those users; otherwise add for all
        if user_ids:
            # Add public holidays for each requested user
            for user_id in user_ids:
                public_holidays = self._filter_public_holidays_by_range(start_date, end_date, user_id)
                absences.extend(public_holidays)
        else:
            # No user filter - add public holidays without user_id (they apply to everyone)
            public_holidays = self._filter_public_holidays_by_range(start_date, end_date, None)
            absences.extend(public_holidays)
        
        return absences

    def _filter_holidays_by_users(
        self,
        holidays: List[Dict[str, Any]],
        user_ids: Optional[List[int]],
    ) -> List[Dict[str, Any]]:
        """Apply user filtering locally when API cannot handle the filter."""
        if not user_ids:
            return holidays
        
        requested_ids = {int(uid) for uid in user_ids}
        filtered: List[Dict[str, Any]] = []
        
        for entry in holidays:
            uid = (
                entry.get("userId")
                or entry.get("UserId")
                or (entry.get("user") or {}).get("id")
                or (entry.get("user") or {}).get("Id")
            )
            try:
                uid_int = int(uid) if uid is not None else None
            except (TypeError, ValueError):
                uid_int = None

            if uid_int in requested_ids:
                filtered.append(entry)

        return filtered

    def _holidays_cache_path(self, start: date, end: date) -> Path:
        return self._holidays_cache_dir / f"{start:%Y%m%d}_{end:%Y%m%d}.json"

    @staticmethod
    def _is_cacheable_range(start: Optional[date], end: Optional[date]) -> bool:
        """
        Cache ranges that end before the current month.
        
        Previous month can be cached but with TTL (weekly refresh).
        Older periods (>= 2 months back) can be safely cached longer.
        Current month is never cached.
        """
        if not start or not end:
            return False
        first_day_current = date.today().replace(day=1)
        return end < first_day_current
    
    def _calculate_data_hash(self, holidays: List[Dict[str, Any]]) -> str:
        """Calculate hash of holidays data for change detection."""
        if not holidays:
            return ""
        
        # Create a hash based on holiday IDs and updated_at timestamps
        hash_data = []
        for holiday in holidays:
            holiday_id = holiday.get('id') or holiday.get('Id')
            updated_at = holiday.get('updatedAt') or holiday.get('updated_at') or holiday.get('at')
            hash_data.append(f"{holiday_id}:{updated_at}")
        
        hash_data.sort()
        hash_string = "|".join(hash_data)
        return hashlib.md5(hash_string.encode('utf-8')).hexdigest()
    
    def _is_cache_fresh(
        self,
        year: int,
        month: int,
        cache_metadata: Optional[Dict[str, Any]]
    ) -> tuple[bool, bool]:
        """
        Check if cache is fresh. Returns (is_fresh, has_dirty_ranges).
        
        Cache freshness rules:
        - Previous month: fresh if < 7 days old (weekly refresh)
        - Older months: fresh if < 30 days old
        """
        if not cache_metadata or not cache_metadata.get('last_full_fetch'):
            return False, False
        
        try:
            last_fetch = datetime.fromisoformat(cache_metadata['last_full_fetch'])
            days_old = (datetime.now() - last_fetch).days
            
            # Determine TTL based on month age
            today = date.today()
            first_day_current = today.replace(day=1)
            last_day_prev_month = first_day_current - timedelta(days=1)
            first_day_prev_month = last_day_prev_month.replace(day=1)
            
            cache_month = date(year, month, 1)
            
            if cache_month >= first_day_prev_month:
                # Previous month - TTL is 7 days (weekly refresh)
                ttl_days = 7
            else:
                # Older months - TTL is 30 days
                ttl_days = 30
            
            is_fresh = days_old < ttl_days
            has_dirty = bool(cache_metadata.get('dirty_ranges'))
            
            return is_fresh, has_dirty
        except (ValueError, TypeError):
            return False, False

    def _load_cached_holidays(self, path: Path) -> Optional[List[Dict[str, Any]]]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return None
        except Exception:
            return None

    def _store_cached_holidays(self, path: Path, payload: List[Dict[str, Any]]) -> None:
        try:
            with path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle)
        except Exception:
            pass
    
    def get_leave_types(self) -> List[Dict[str, Any]]:
        """Get list of available leave types."""
        if self._leave_types_cache is not None:
            return self._leave_types_cache

        data = self._make_request("/holidaytypes")
        
        # Handle different response formats
        if isinstance(data, list):
            self._leave_types_cache = data
            return data
        else:
            items = data.get("holidayTypes", []) or data.get("items", [])
            self._leave_types_cache = items
            return items
    
    def get_user_holidays(
        self,
        user_id: int,
        start_date: str,
        end_date: str,
    ) -> List[Absence]:
        """Get holidays for specific user."""
        user_absences = self.get_holidays(start_date, end_date, [user_id])
        public_holidays = self._filter_public_holidays_by_range(start_date, end_date, user_id)
        return user_absences + public_holidays
    
    def get_departments(self) -> List[Dict[str, Any]]:
        """Get list of departments."""
        try:
            if self._departments_cache is not None:
                return self._departments_cache
            data = self._make_request("/departments")
            
            # Handle different response formats
            if isinstance(data, list):
                self._departments_cache = data
                return data
            else:
                items = data.get("departments", []) or data.get("items", [])
                self._departments_cache = items
                return items
        except Exception:
            return []
    
    def get_user_allowance(self, user_id: int, year: int) -> Dict[str, Any]:
        """Get user's holiday allowance for a specific year."""
        try:
            return self._make_request(f"/users/{user_id}/allowance/{year}")
        except Exception:
            return {}

    def get_public_holidays(self) -> List[Absence]:
        """Fetch all configured public holidays for the account."""
        if self._public_holidays_cache is not None:
            print(f"   [DEBUG] Public Holidays API: Using cached data ({len(self._public_holidays_cache)} holidays)")
            return list(self._public_holidays_cache)

        print(f"   [DEBUG] Public Holidays API: Fetching from Timetastic /publicholidays...")
        try:
            data = self._make_request("/publicholidays")
        except Exception as exc:
            print(f"Warning: Failed to fetch Timetastic public holidays: {exc}")
            return []

        if isinstance(data, list):
            records = data
        else:
            records = data.get("publicHolidays") or data.get("items") or []

        print(f"   [DEBUG] Public Holidays API: Received {len(records)} records from API")

        holidays: List[Absence] = []
        for record in records:
            try:
                holidays.append(Absence.from_public_holiday(record))
            except Exception as exc:
                print(f"Warning: Failed to parse public holiday {record.get('id', 'unknown')}: {exc}")

        print(f"   [DEBUG] Public Holidays API: Successfully parsed {len(holidays)} public holidays")
        self._public_holidays_cache = holidays
        return list(holidays)

    def _filter_public_holidays_by_range(self, start_iso: str, end_iso: str, user_id: Optional[int]) -> List[Absence]:
        """Return cached public holidays that fall within the requested date window."""
        holidays = self.get_public_holidays()
        start_date = self._parse_iso_to_date(start_iso)
        end_date = self._parse_iso_to_date(end_iso)
        
        print(f"   [DEBUG] Public Holidays Filter: Checking range {start_date} to {end_date} (user_id={user_id})")
        print(f"   [DEBUG] Public Holidays Filter: Total available holidays: {len(holidays)}")
        
        if not start_date or not end_date:
            print(f"   [DEBUG] Public Holidays Filter: Invalid date range, returning all holidays")
            return [
                replace(holiday, user_id=user_id)
                for holiday in holidays
            ]

        filtered: List[Absence] = []
        for holiday in holidays:
            if start_date <= holiday.start_date <= end_date:
                filtered.append(replace(holiday, user_id=user_id))
                print(f"   [DEBUG] Public Holidays Filter: Found {holiday.start_date} - {holiday.notes or 'No name'}")
        
        print(f"   [DEBUG] Public Holidays Filter: Found {len(filtered)} public holidays in range {start_date} to {end_date}")
        return filtered

    @staticmethod
    def _parse_iso_to_date(value: str) -> Optional[date]:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except (ValueError, AttributeError):
            return None
    
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
