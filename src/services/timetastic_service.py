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
    
    def get_users(self, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Get list of all users in the organization with caching (TTL 30 days)."""
        cache_path = self._users_cache_path()
        
        # Check cache metadata if storage is available and not forcing refresh
        if not force_refresh and self.storage:
            # Use workspace_id=-1, year=0, month=0 for users (not workspace/month-specific, different from public holidays)
            cache_metadata = self.storage.get_cache_metadata(-1, 0, 0)
            
            if cache_metadata:
                is_fresh, has_dirty = self._is_users_cache_fresh(cache_metadata)
                
                # Use cache if fresh and no dirty ranges
                if is_fresh and not has_dirty:
                    cached_users = self._load_cached_users(cache_path)
                    if cached_users is not None:
                        self._users_cache = cached_users
                        print(f"   [DEBUG TimetasticCache] Using fresh users cache: {len(cached_users)} users")
                        return cached_users
                elif is_fresh and has_dirty:
                    # Cache is fresh but has dirty ranges - use stale cache but queue refresh
                    cached_users = self._load_cached_users(cache_path)
                    if cached_users is not None:
                        self._users_cache = cached_users
                        print(f"   [DEBUG TimetasticCache] Using stale users cache (has dirty ranges): {len(cached_users)} users")
                        return cached_users
            else:
                # No metadata - try to load from file cache if exists
                cached_users = self._load_cached_users(cache_path)
                if cached_users is not None:
                    self._users_cache = cached_users
                    print(f"   [DEBUG TimetasticCache] Using file users cache (no metadata): {len(cached_users)} users")
                    return cached_users
        elif not force_refresh:
            # Fallback to file cache only if no storage
            cached_users = self._load_cached_users(cache_path)
            if cached_users is not None:
                self._users_cache = cached_users
                print(f"   [DEBUG TimetasticCache] Using file users cache (no storage): {len(cached_users)} users")
                return cached_users
        
        # Check in-memory cache
        if self._users_cache is not None:
            return self._users_cache
        
        # Fetch from API
        print(f"   [DEBUG TimetasticCache] Fetching users from API...")
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
        
        print(f"   [DEBUG TimetasticCache] Fetched {len(users)} users from API")
        self._users_cache = users
        
        # Store cache and update metadata
        if users and cache_path:
            self._store_cached_users(cache_path, users)
            
            # Update cache metadata
            if self.storage:
                data_hash = self._calculate_users_hash(users)
                
                # Check if hash changed (data was modified)
                existing_metadata = self.storage.get_cache_metadata(-1, 0, 0)
                if existing_metadata and existing_metadata.get('data_hash'):
                    old_hash = existing_metadata.get('data_hash')
                    if old_hash != data_hash:
                        # Data changed - mark as dirty for next refresh
                        pass
                
                # Update metadata with new hash
                self.storage.set_cache_metadata(
                    -1,  # workspace_id=-1 for users (org-wide, different from public holidays which use 0)
                    0,  # year=0 for users (not year-specific)
                    0,  # month=0 for users (not month-specific)
                    data_hash=data_hash,
                    clear_dirty=True
                )
        
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
        force_refresh: bool = False,
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
        cache_info = {"used_cache": False, "cache_type": None}
        
        # Check cache metadata if cacheable and storage is available
        if cacheable and start_obj and end_obj and self.storage:
            disk_cache_path = self._holidays_cache_path(start_obj, end_obj)
            
            # Get cache metadata for the month (use workspace_id=0 for Timetastic as it's org-wide)
            year = start_obj.year
            month = start_obj.month
            cache_metadata = self.storage.get_cache_metadata(0, year, month)
            
            if cache_metadata:
                is_fresh, has_dirty = self._is_cache_fresh(year, month, cache_metadata)
                
                # Use cache if fresh and no dirty ranges AND not forcing refresh
                if is_fresh and not has_dirty and not force_refresh:
                    disk_payload = self._load_cached_holidays(disk_cache_path)
                    if disk_payload is not None:
                        raw_holidays = disk_payload
                        self._holidays_cache[cache_key] = raw_holidays
                        should_fetch = False
                elif is_fresh and has_dirty and not force_refresh:
                    # Cache is fresh but has dirty ranges - use stale cache but queue refresh
                    disk_payload = self._load_cached_holidays(disk_cache_path)
                    if disk_payload is not None:
                        raw_holidays = disk_payload
                        self._holidays_cache[cache_key] = raw_holidays
                        should_fetch = False
                        print(f"   [DEBUG TimetasticCache] Using stale cache (has dirty ranges): {len(raw_holidays)} holidays from file cache ({start_obj} to {end_obj})")
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
                    print(f"   [DEBUG TimetasticCache] Using file cache (no metadata): {len(raw_holidays)} holidays ({start_obj} to {end_obj})")
        elif cacheable and start_obj and end_obj:
            # Fallback to file cache only if no storage
            disk_cache_path = self._holidays_cache_path(start_obj, end_obj)
            disk_payload = self._load_cached_holidays(disk_cache_path)
            if disk_payload is not None:
                raw_holidays = disk_payload
                self._holidays_cache[cache_key] = raw_holidays
                should_fetch = False
                print(f"   [DEBUG TimetasticCache] Using file cache (no storage): {len(raw_holidays)} holidays ({start_obj} to {end_obj})")

        if not raw_holidays and should_fetch:
            cached = self._holidays_cache.get(cache_key)
            if cached is not None:
                raw_holidays = cached
                print(f"   [DEBUG TimetasticCache] Using in-memory cache")
            else:
                # Fetch holidays with pagination
                print(f"   [DEBUG TimetasticCache] Fetching from API ({start_obj} to {end_obj})...")
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
        public_holidays_count = 0
        if user_ids:
            # Add public holidays for each requested user
            for user_id in user_ids:
                public_holidays = self._filter_public_holidays_by_range(start_date, end_date, user_id)
                # Deduplicate public holidays
                seen_keys = set()
                for ph in public_holidays:
                    key = (ph.start_date, ph.notes or "")
                    if key not in seen_keys:
                        seen_keys.add(key)
                        absences.append(ph)
                public_holidays_count += len(seen_keys)
        else:
            # No user filter - add public holidays without user_id (they apply to everyone)
            public_holidays = self._filter_public_holidays_by_range(start_date, end_date, None)
            absences.extend(public_holidays)
            public_holidays_count = len(public_holidays)
        
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
    
    def _public_holidays_cache_path(self) -> Path:
        """Get cache path for public holidays."""
        return self._timetastic_cache_dir / "public_holidays.json"
    
    def _users_cache_path(self) -> Path:
        """Get cache path for users."""
        return self._timetastic_cache_dir / "users.json"

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
    
    def _calculate_public_holidays_hash(self, holidays: List[Dict[str, Any]]) -> str:
        """Calculate hash of public holidays data for change detection."""
        if not holidays:
            return ""
        
        # Create a hash based on public holiday IDs and updated_at timestamps
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
    
    def _is_public_holidays_cache_fresh(self, cache_metadata: Optional[Dict[str, Any]]) -> tuple[bool, bool]:
        """
        Check if public holidays cache is fresh. Returns (is_fresh, has_dirty_ranges).
        
        Public holidays cache TTL: 90 days
        """
        if not cache_metadata or not cache_metadata.get('last_full_fetch'):
            return False, False
        
        try:
            last_fetch = datetime.fromisoformat(cache_metadata['last_full_fetch'])
            days_old = (datetime.now() - last_fetch).days
            
            # Public holidays cache TTL is 90 days
            ttl_days = 90
            
            is_fresh = days_old < ttl_days
            has_dirty = bool(cache_metadata.get('dirty_ranges'))
            
            return is_fresh, has_dirty
        except (ValueError, TypeError):
            return False, False
    
    def _is_users_cache_fresh(self, cache_metadata: Optional[Dict[str, Any]]) -> tuple[bool, bool]:
        """
        Check if users cache is fresh. Returns (is_fresh, has_dirty_ranges).
        
        Users cache TTL: 30 days
        """
        if not cache_metadata or not cache_metadata.get('last_full_fetch'):
            return False, False
        
        try:
            last_fetch = datetime.fromisoformat(cache_metadata['last_full_fetch'])
            days_old = (datetime.now() - last_fetch).days
            
            # Users cache TTL is 30 days
            ttl_days = 30
            
            is_fresh = days_old < ttl_days
            has_dirty = bool(cache_metadata.get('dirty_ranges'))
            
            return is_fresh, has_dirty
        except (ValueError, TypeError):
            return False, False
    
    def _calculate_users_hash(self, users: List[Dict[str, Any]]) -> str:
        """Calculate hash of users data for change detection."""
        if not users:
            return ""
        
        # Create a hash based on user IDs and updated_at timestamps
        hash_data = []
        for user in users:
            user_id = user.get('id') or user.get('Id')
            updated_at = user.get('updatedAt') or user.get('updated_at') or user.get('at')
            hash_data.append(f"{user_id}:{updated_at}")
        
        hash_data.sort()
        hash_string = "|".join(hash_data)
        return hashlib.md5(hash_string.encode('utf-8')).hexdigest()
    
    def _load_cached_users(self, path: Path) -> Optional[List[Dict[str, Any]]]:
        """Load cached users from file."""
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return None
        except Exception:
            return None
    
    def _store_cached_users(self, path: Path, users: List[Dict[str, Any]]) -> None:
        """Store users cache to file."""
        try:
            with path.open("w", encoding="utf-8") as handle:
                json.dump(users, handle)
        except Exception:
            pass

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
    
    def _load_cached_public_holidays(self, path: Path) -> Optional[List[Dict[str, Any]]]:
        """Load cached public holidays from file."""
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return None
        except Exception:
            return None
    
    def _store_cached_public_holidays(self, path: Path, payload: List[Dict[str, Any]]) -> None:
        """Store public holidays cache to file."""
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
        # Debug: Show call stack to identify caller
        import traceback
        call_stack = traceback.extract_stack()
        caller_info = call_stack[-2] if len(call_stack) > 1 else None
        caller_name = caller_info.name if caller_info else "unknown"
        caller_file = Path(caller_info.filename).name if caller_info else "unknown"
        print(f"   [DEBUG get_user_holidays] Called from {caller_file}:{caller_name}() | user_id={user_id} | range={start_date} to {end_date}")
        
        print(f"   [DEBUG get_user_holidays] Fetching user_absences via get_holidays(user_ids=[{user_id}])...")
        user_absences = self.get_holidays(start_date, end_date, [user_id])
        print(f"   [DEBUG get_user_holidays] Got {len(user_absences)} user_absences")
        
        print(f"   [DEBUG get_user_holidays] Fetching public_holidays via _filter_public_holidays_by_range(user_id={user_id})...")
        public_holidays = self._filter_public_holidays_by_range(start_date, end_date, user_id)
        print(f"   [DEBUG get_user_holidays] Got {len(public_holidays)} public_holidays")
        
        result = user_absences + public_holidays
        print(f"   [DEBUG get_user_holidays] Returning {len(result)} total absences ({len(user_absences)} user + {len(public_holidays)} public)")
        return result
    
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
        """Fetch all configured public holidays for the account with caching (TTL 90 days)."""
        cache_path = self._public_holidays_cache_path()
        
        # Check cache metadata if storage is available
        if self.storage:
            # Use workspace_id=0, year=0, month=0 for public holidays (not workspace/month-specific)
            cache_metadata = self.storage.get_cache_metadata(0, 0, 0)
            
            if cache_metadata:
                is_fresh, has_dirty = self._is_public_holidays_cache_fresh(cache_metadata)
                
                # Use cache if fresh and no dirty ranges
                if is_fresh and not has_dirty:
                    cached_data = self._load_cached_public_holidays(cache_path)
                    if cached_data is not None:
                        # Convert cached JSON to Absence objects
                        holidays = []
                        for record in cached_data:
                            try:
                                holidays.append(Absence.from_public_holiday(record))
                            except Exception as exc:
                                print(f"Warning: Failed to parse cached public holiday {record.get('id', 'unknown')}: {exc}")
                        
                        if holidays:
                            self._public_holidays_cache = holidays
                            return list(holidays)
                elif is_fresh and has_dirty:
                    # Cache is fresh but has dirty ranges - use stale cache but queue refresh
                    cached_data = self._load_cached_public_holidays(cache_path)
                    if cached_data is not None:
                        holidays = []
                        for record in cached_data:
                            try:
                                holidays.append(Absence.from_public_holiday(record))
                            except Exception as exc:
                                print(f"Warning: Failed to parse cached public holiday {record.get('id', 'unknown')}: {exc}")
                        
                        if holidays:
                            self._public_holidays_cache = holidays
                            return list(holidays)
            else:
                # No metadata - try to load from file cache if exists
                cached_data = self._load_cached_public_holidays(cache_path)
                if cached_data is not None:
                    holidays = []
                    for record in cached_data:
                        try:
                            holidays.append(Absence.from_public_holiday(record))
                        except Exception as exc:
                            print(f"Warning: Failed to parse cached public holiday {record.get('id', 'unknown')}: {exc}")
                    
                    if holidays:
                        self._public_holidays_cache = holidays
                        return list(holidays)
        else:
            # Fallback to file cache only if no storage
            cached_data = self._load_cached_public_holidays(cache_path)
            if cached_data is not None:
                holidays = []
                for record in cached_data:
                    try:
                        holidays.append(Absence.from_public_holiday(record))
                    except Exception as exc:
                        print(f"Warning: Failed to parse cached public holiday {record.get('id', 'unknown')}: {exc}")
                
                if holidays:
                    self._public_holidays_cache = holidays
                    return list(holidays)
        
        # Check in-memory cache
        if self._public_holidays_cache is not None:
            return list(self._public_holidays_cache)

        # Fetch from API
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
        
        # Store cache and update metadata
        if records and cache_path:
            self._store_cached_public_holidays(cache_path, records)
            
            # Update cache metadata
            if self.storage:
                data_hash = self._calculate_public_holidays_hash(records)
                
                # Check if hash changed (data was modified)
                existing_metadata = self.storage.get_cache_metadata(0, 0, 0)
                if existing_metadata and existing_metadata.get('data_hash'):
                    old_hash = existing_metadata.get('data_hash')
                    if old_hash != data_hash:
                        # Data changed - mark as dirty for next refresh
                        pass
                
                # Update metadata with new hash
                self.storage.set_cache_metadata(
                    0,  # workspace_id=0 for public holidays (org-wide)
                    0,  # year=0 for public holidays (not year-specific)
                    0,  # month=0 for public holidays (not month-specific)
                    data_hash=data_hash,
                    clear_dirty=True
                )
        
        self._public_holidays_cache = holidays
        return list(holidays)

    def _filter_public_holidays_by_range(self, start_iso: str, end_iso: str, user_id: Optional[int]) -> List[Absence]:
        """Return cached public holidays that fall within the requested date window."""
        holidays = self.get_public_holidays()
        start_date = self._parse_iso_to_date(start_iso)
        end_date = self._parse_iso_to_date(end_iso)
        
        if not start_date or not end_date:
            return [
                replace(holiday, user_id=user_id)
                for holiday in holidays
            ]

        filtered: List[Absence] = []
        for holiday in holidays:
            if start_date <= holiday.start_date <= end_date:
                filtered.append(replace(holiday, user_id=user_id))
        
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
