"""
Toggl Track API service.
"""

import base64
import json
import hashlib
from pathlib import Path
import requests
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date, timedelta

from ..config import Settings
from ..models.time_entry import TimeEntry
from ..models.project import Project
from ..logic.date_ranges import last_week_range, last_month_range, current_week_range, current_month_to_date_range


class TogglService:
    """Service for interacting with Toggl Track API."""
    
    def __init__(self, settings: Settings, storage: Optional[Any] = None):
        self.settings = settings
        self.base_url = settings.toggl_base_url
        self.reports_base_url = settings.toggl_reports_base_url
        self.token = settings.toggl_api_token
        self.workspace_id = settings.workspace_id
        self._project_cache: Dict[str, Dict[int, str]] = {}
        self._task_cache: Dict[str, Dict[int, Dict[int, str]]] = {}
        self.cache_dir = Path(settings.cache_dir).expanduser()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._toggl_cache_dir = self.cache_dir / "toggl"
        self._toggl_cache_dir.mkdir(parents=True, exist_ok=True)
        self.storage = storage  # SQLiteStorage instance for cache metadata
    
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

    def _post_reports(self, endpoint: str, json_body: Dict[str, Any]) -> Any:
        """POST to Toggl Reports API (v3)."""
        url = f"{self.reports_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        
        try:
            response = requests.post(url, headers=self._auth_header(), json=json_body, timeout=120)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Toggl Reports API request failed: {e}")
    
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

    @staticmethod
    def _normalize_projects_payload(payload: Any) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """
        Toggl v9 may return a JSON array or an object with ``items`` and optional ``total_count``.
        Returns (project_dicts, total_count_if_present).
        """
        if payload is None:
            return [], None
        if isinstance(payload, list):
            return [p for p in payload if isinstance(p, dict)], None
        if isinstance(payload, dict):
            total_raw = payload.get("total_count")
            total: Optional[int] = None
            if isinstance(total_raw, int):
                total = total_raw
            items = payload.get("items")
            if isinstance(items, list):
                return [p for p in items if isinstance(p, dict)], total
        return [], None

    def _fetch_all_workspace_projects(self, workspace: int) -> List[Dict[str, Any]]:
        """
        Fetch all projects for a workspace: paginated GET, active + inactive (``active=both``),
        up to 200 per page per Toggl API limits.
        """
        all_items: List[Dict[str, Any]] = []
        seen_ids: set[int] = set()
        page = 1
        per_page = 200
        max_pages = 500
        reported_total: Optional[int] = None

        while page <= max_pages:
            params: Dict[str, Any] = {
                "active": "both",
                "page": page,
                "per_page": per_page,
            }
            payload = self._make_request(f"/workspaces/{workspace}/projects", params=params)
            batch, page_total = self._normalize_projects_payload(payload)
            if page_total is not None:
                reported_total = page_total

            if not batch:
                break

            added = 0
            for p in batch:
                pid = p.get("id")
                if pid is None:
                    continue
                try:
                    pid_int = int(pid)
                except (TypeError, ValueError):
                    continue
                if pid_int in seen_ids:
                    continue
                seen_ids.add(pid_int)
                all_items.append(p)
                added += 1

            # Same page repeated (some API quirks) — avoid infinite pagination
            if added == 0:
                break
            if len(batch) < per_page:
                break
            if reported_total is not None and len(all_items) >= reported_total:
                break
            page += 1

        return all_items
    
    def get_projects(self, workspace_id: Optional[int] = None, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Get list of projects in workspace with caching (TTL 30 days)."""
        workspace = workspace_id or self.workspace_id
        if not workspace:
            raise ValueError("Workspace ID is required")
        
        workspace_key = str(workspace)
        cache_path = self._projects_cache_path(workspace)
        
        # Check cache metadata if storage is available and not forcing refresh
        if not force_refresh and self.storage:
            # Use workspace_id as cache key, year=0, month=0 for projects (not month-specific)
            cache_metadata = self.storage.get_cache_metadata(int(workspace), 0, 0)
            
            if cache_metadata:
                is_fresh, has_dirty = self._is_projects_cache_fresh(cache_metadata)
                
                # Use cache if fresh and no dirty ranges
                if is_fresh and not has_dirty:
                    cached_projects = self._load_cached_projects(cache_path)
                    if cached_projects is not None:
                        return cached_projects
                elif is_fresh and has_dirty:
                    # Cache is fresh but has dirty ranges - use stale cache but queue refresh
                    cached_projects = self._load_cached_projects(cache_path)
                    if cached_projects is not None:
                        return cached_projects
            else:
                # No metadata - try to load from file cache if exists
                cached_projects = self._load_cached_projects(cache_path)
                if cached_projects is not None:
                    return cached_projects
        elif not force_refresh:
            # Fallback to file cache only if no storage
            cached_projects = self._load_cached_projects(cache_path)
            if cached_projects is not None:
                return cached_projects
        
        # Fetch from API (paginated; active + inactive — callers filter if needed)
        projects = self._fetch_all_workspace_projects(int(workspace))
        
        # Store cache and update metadata
        if projects and cache_path:
            self._store_cached_projects(cache_path, projects)
            
            # Update cache metadata
            if self.storage:
                data_hash = self._calculate_projects_hash(projects)
                
                # Check if hash changed (data was modified)
                existing_metadata = self.storage.get_cache_metadata(int(workspace), 0, 0)
                if existing_metadata and existing_metadata.get('data_hash'):
                    old_hash = existing_metadata.get('data_hash')
                    if old_hash != data_hash:
                        # Data changed - mark as dirty for next refresh
                        # For projects, we don't use date ranges, so we just update the hash
                        pass
                
                # Update metadata with new hash
                self.storage.set_cache_metadata(
                    int(workspace),
                    0,  # year=0 for projects (not month-specific)
                    0,  # month=0 for projects (not month-specific)
                    data_hash=data_hash,
                    clear_dirty=True
                )
        
        return projects

    def get_workspace_users(self, workspace_id: Optional[int] = None, force_refresh: bool = False) -> List[Dict[str, Any]]:
        """Get list of users in workspace with caching (TTL 30 days)."""
        workspace = workspace_id or self.workspace_id
        if not workspace:
            raise ValueError("Workspace ID is required")
        
        workspace_key = str(workspace)
        cache_path = self._users_cache_path(workspace)
        
        # Check cache metadata if storage is available and not forcing refresh
        if not force_refresh and self.storage:
            # Use workspace_id=-workspace-1 for users (different from projects which use workspace_id)
            # This ensures users and projects don't share the same cache metadata entry
            cache_metadata = self.storage.get_cache_metadata(-int(workspace) - 1, 0, 0)
            
            if cache_metadata:
                is_fresh, has_dirty = self._is_users_cache_fresh(cache_metadata)
                
                # Use cache if fresh and no dirty ranges
                if is_fresh and not has_dirty:
                    cached_users = self._load_cached_users(cache_path)
                    if cached_users is not None:
                        print(f"   [DEBUG TogglCache] Using fresh users cache: {len(cached_users)} users")
                        return cached_users
                elif is_fresh and has_dirty:
                    # Cache is fresh but has dirty ranges - use stale cache but queue refresh
                    cached_users = self._load_cached_users(cache_path)
                    if cached_users is not None:
                        print(f"   [DEBUG TogglCache] Using stale users cache (has dirty ranges): {len(cached_users)} users")
                        return cached_users
            else:
                # No metadata - try to load from file cache if exists
                cached_users = self._load_cached_users(cache_path)
                if cached_users is not None:
                    print(f"   [DEBUG TogglCache] Using file users cache (no metadata): {len(cached_users)} users")
                    return cached_users
        elif not force_refresh:
            # Fallback to file cache only if no storage
            cached_users = self._load_cached_users(cache_path)
            if cached_users is not None:
                print(f"   [DEBUG TogglCache] Using file users cache (no storage): {len(cached_users)} users")
                return cached_users
        
        # Fetch from API
        print(f"   [DEBUG TogglCache] Fetching users from API...")
        users = self._make_request(f"/workspaces/{workspace}/users")
        print(f"   [DEBUG TogglCache] Fetched {len(users)} users from API")
        
        # Store cache and update metadata
        if users and cache_path:
            self._store_cached_users(cache_path, users)
            
            # Update cache metadata
            if self.storage:
                data_hash = self._calculate_users_hash(users)
                
                # Check if hash changed (data was modified)
                existing_metadata = self.storage.get_cache_metadata(-int(workspace) - 1, 0, 0)
                if existing_metadata and existing_metadata.get('data_hash'):
                    old_hash = existing_metadata.get('data_hash')
                    if old_hash != data_hash:
                        # Data changed - mark as dirty for next refresh
                        pass
                
                # Update metadata with new hash
                self.storage.set_cache_metadata(
                    -int(workspace) - 1,  # workspace_id=-workspace-1 for users (different from projects)
                    0,  # year=0 for users (not month-specific)
                    0,  # month=0 for users (not month-specific)
                    data_hash=data_hash,
                    clear_dirty=True
                )
        
        return users

    def get_project_tasks(self, project_id: int, workspace_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get list of tasks for a project."""
        workspace = workspace_id or self.workspace_id
        if not workspace:
            raise ValueError("Workspace ID is required")

        return self._make_request(f"/workspaces/{workspace}/projects/{project_id}/tasks")

    def _lookup_project_name(self, workspace: Optional[int], project_id: Optional[int]) -> Optional[str]:
        """Resolve project name using a per-workspace cache. Projects should be pre-loaded."""
        if workspace is None or project_id is None:
            return None
        try:
            project_id_int = int(project_id)
        except (TypeError, ValueError):
            return None

        workspace_key = str(workspace)
        cache = self._project_cache.get(workspace_key, {})
        
        # Check cache first - projects should be pre-loaded
        if project_id_int in cache:
            return cache[project_id_int]
        
        # Fallback: if cache is empty (shouldn't happen if pre-loading worked), try to load
        # This is a safety net in case pre-loading failed
        if not cache:
            try:
                workspace_param = int(workspace)
                projects = self.get_projects(workspace_param)
                cache = self._project_cache.setdefault(workspace_key, {})
                for project in projects or []:
                    pid = project.get("id")
                    name = project.get("name")
                    try:
                        pid_int = int(pid)
                    except (TypeError, ValueError):
                        continue
                    cache[pid_int] = name
                return cache.get(project_id_int)
            except Exception:
                return None
        
        return None  # Project not found in cache

    def _lookup_task_name(
        self,
        workspace: Optional[int],
        project_id: Optional[int],
        task_id: Optional[int],
    ) -> Optional[str]:
        """Resolve task name using a project-scoped cache. Tasks should be pre-loaded."""
        if workspace is None or project_id is None or task_id is None:
            return None
        try:
            workspace_key = str(int(workspace))
            project_id_int = int(project_id)
            task_id_int = int(task_id)
        except (TypeError, ValueError):
            return None

        project_cache = self._task_cache.get(workspace_key, {})
        task_cache = project_cache.get(project_id_int, {})
        
        # Check cache first - tasks should be pre-loaded
        if task_id_int in task_cache:
            return task_cache[task_id_int]
        
        # Fallback: if cache is empty (shouldn't happen if pre-loading worked), try to load
        # This is a safety net in case pre-loading failed
        if not task_cache:
            try:
                tasks = self.get_project_tasks(project_id_int, int(workspace))
                project_cache = self._task_cache.setdefault(workspace_key, {})
                task_cache = project_cache.setdefault(project_id_int, {})
                for task in tasks or []:
                    tid = task.get("id")
                    name = task.get("name")
                    try:
                        tid_int = int(tid)
                    except (TypeError, ValueError):
                        continue
                    task_cache[tid_int] = name
                return task_cache.get(task_id_int)
            except Exception:
                return None
        
        return None  # Task not found in cache
    
    def get_time_entries(
        self,
        start_date: str,
        end_date: str,
        workspace_id: Optional[int] = None,
        user_ids: Optional[List[int]] = None,
        force_refresh: bool = False,
    ) -> List[TimeEntry]:
        """
        Get time entries for a date range across a workspace, optionally filtered by users.

        Args:
            start_date: Start date in ISO 8601 UTC (e.g., "2025-10-01T00:00:00Z")
            end_date: End date in ISO 8601 UTC (e.g., "2025-10-31T23:59:59Z")
            workspace_id: Workspace ID. Defaults to settings.workspace_id
            user_ids: Optional list of Toggl user IDs to filter
        """
        workspace = workspace_id or self.workspace_id
        
        # Pre-load projects ONCE at the very start - they change rarely (monthly)
        if workspace:
            workspace_key = str(workspace)
            if workspace_key not in self._project_cache or not self._project_cache[workspace_key]:
                try:
                    projects = self.get_projects(workspace)
                    cache = self._project_cache.setdefault(workspace_key, {})
                    for project in projects or []:
                        pid = project.get("id")
                        name = project.get("name")
                        try:
                            pid_int = int(pid)
                        except (TypeError, ValueError):
                            continue
                        cache[pid_int] = name
                except Exception:
                    pass  # If loading fails, _lookup_project_name will handle it as fallback
        
        start_day = self._parse_iso_to_date(start_date)
        end_day = self._parse_iso_to_date(end_date)
        cacheable = self._is_cacheable_range(start_day, end_day)
        cache_path: Optional[Path] = None
        normalized_entries: Optional[List[Dict[str, Any]]] = None
        should_fetch = True
        
        # Check cache metadata if cacheable and storage is available
        if cacheable and start_day and end_day and self.storage and workspace:
            cache_path = self._cache_file_path(workspace, start_day, end_day)
            
            # Get cache metadata for the month
            year = start_day.year
            month = start_day.month
            cache_metadata = self.storage.get_cache_metadata(int(workspace), year, month)
            
            if cache_metadata:
                is_fresh, has_dirty = self._is_cache_fresh(int(workspace), year, month, cache_metadata)
                
                # Use cache if fresh and no dirty ranges AND not forcing refresh
                if is_fresh and not has_dirty and not force_refresh:
                    cached_payload = self._load_cached_entries(cache_path)
                    if cached_payload is not None:
                        normalized_entries = cached_payload
                        should_fetch = False
                elif is_fresh and has_dirty and not force_refresh:
                    # Cache is fresh but has dirty ranges - use stale cache but queue refresh
                    cached_payload = self._load_cached_entries(cache_path)
                    if cached_payload is not None:
                        normalized_entries = cached_payload
                        should_fetch = False
                        # Queue refresh for dirty ranges
                        dirty_ranges = cache_metadata.get('dirty_ranges', [])
                        for dr in dirty_ranges:
                            try:
                                dr_start = datetime.fromisoformat(dr['start']).date()
                                dr_end = datetime.fromisoformat(dr['end']).date()
                                self.storage.add_refresh_job(int(workspace), dr_start, dr_end, priority=3)
                            except (ValueError, KeyError):
                                pass
            else:
                # No metadata - try to load from file cache if exists
                cached_payload = self._load_cached_entries(cache_path)
                if cached_payload is not None:
                    normalized_entries = cached_payload
                    should_fetch = False

        raw_entries: Any = []
        if normalized_entries is None or should_fetch:
            entries_data: Any = []
            if workspace:
                # Prefer Reports API v3 for workspace-wide queries
                def _date_only(value: Optional[str]) -> Optional[str]:
                    if not value:
                        return value
                    return value.split("T")[0]

                request_bodies: List[Dict[str, Any]] = [
                    {
                        "start_date": _date_only(start_date),
                        "end_date": _date_only(end_date),
                        "page_size": 1000,
                    },
                    {
                        "start_time": start_date,
                        "end_time": end_date,
                        "page_size": 1000,
                    },
                ]

                data: Any = None
                last_error: Optional[Exception] = None
                for body in request_bodies:
                    try:
                        data = self._post_reports(f"/workspace/{workspace}/search/time_entries", body)
                        if data is not None:
                            break
                    except Exception as exc:
                        last_error = exc

                if data is None:
                    raise last_error if last_error else Exception("Failed to fetch data from Toggl Reports API")

                if isinstance(data, dict):
                    entries_data = data.get("time_entries") or data.get("data") or []
                else:
                    entries_data = data or []
            else:
                params = {"start_date": start_date, "end_date": end_date}
                entries_data = self._make_request("/me/time_entries", params)

            raw_entries = entries_data or []
        else:
            raw_entries = normalized_entries

        # Normalize ALL entries first (before filtering) so cache contains all users' data
        if normalized_entries is None:
            normalized_entries = []

            def _append_normalized(entry: Dict[str, Any]) -> None:
                if "duration" not in entry and "seconds" in entry:
                    entry.setdefault("duration", entry.get("seconds"))
                if "id" not in entry and "time_entry_id" in entry:
                    entry["id"] = entry["time_entry_id"]
                if "id" not in entry:
                    return
                normalized_entries.append(entry)

            for entry_data in raw_entries:
                if not isinstance(entry_data, dict):
                    continue

                if "time_entry" in entry_data:
                    time_entry_data = entry_data.get("time_entry") or {}
                    base = dict(time_entry_data)
                    project_info = entry_data.get("project")
                    if isinstance(project_info, dict):
                        base.setdefault("project_id", project_info.get("id"))
                        base.setdefault("project_name", project_info.get("name"))
                    task_info = entry_data.get("task")
                    if isinstance(task_info, dict):
                        base.setdefault("task_id", task_info.get("id"))
                        base.setdefault("task_name", task_info.get("name"))
                    user_info = entry_data.get("user")
                    if isinstance(user_info, dict):
                        base.setdefault("user_id", user_info.get("id"))
                        base.setdefault("user_email", user_info.get("email"))
                    _append_normalized(base)
                    continue

                time_entries_list = entry_data.get("time_entries") if isinstance(entry_data, dict) else None
                if isinstance(time_entries_list, list) and time_entries_list:
                    base_info = dict(entry_data)
                    base_info.pop("time_entries", None)
                    for sub_entry in time_entries_list:
                        if not isinstance(sub_entry, dict):
                            continue
                        child = dict(base_info)
                        sub_id = sub_entry.get("id") or sub_entry.get("time_entry_id")
                        if sub_id is not None:
                            child["id"] = sub_id
                        if "seconds" in sub_entry:
                            child["seconds"] = sub_entry.get("seconds")
                            child.setdefault("duration", sub_entry.get("seconds"))
                        if sub_entry.get("start"):
                            child["start"] = sub_entry.get("start")
                        if sub_entry.get("stop"):
                            child["stop"] = sub_entry.get("stop")
                        if sub_entry.get("at"):
                            child.setdefault("updated_at", sub_entry.get("at"))
                        _append_normalized(child)
                    continue

                base = dict(entry_data)
                _append_normalized(base)

            # Store cache and update metadata if cacheable
            if cacheable and cache_path and normalized_entries:
                self._store_cached_entries(cache_path, normalized_entries)
                
                # Update cache metadata with hash and detect changes
                if self.storage and workspace and start_day and end_day:
                    data_hash = self._calculate_data_hash(normalized_entries)
                    year = start_day.year
                    month = start_day.month
                    
                    # Check if hash changed (data was modified)
                    existing_metadata = self.storage.get_cache_metadata(int(workspace), year, month)
                    if existing_metadata and existing_metadata.get('data_hash'):
                        old_hash = existing_metadata.get('data_hash')
                        if old_hash != data_hash:
                            # Data changed - mark the entire range as dirty for next refresh
                            self.storage.mark_dirty_range(int(workspace), start_day, end_day)
                    
                    # Update metadata with new hash and clear dirty ranges (since we just refreshed)
                    self.storage.set_cache_metadata(
                        int(workspace),
                        year,
                        month,
                        data_hash=data_hash,
                        clear_dirty=True
                    )

        # Filter by user_id AFTER cache is saved (so cache contains all users' entries)
        if user_ids:
            target_ids = {int(u) for u in user_ids}
            normalized_entries = [
                entry for entry in normalized_entries
                if entry.get('user_id') in target_ids
            ]

        if workspace:
            # Projects should already be pre-loaded at the start of get_time_entries
            for entry in normalized_entries:
                if entry.get("project_name"):
                    continue
                project_id = entry.get("project_id")
                name = self._lookup_project_name(workspace, project_id)
                if name:
                    entry["project_name"] = name
                    existing_project = entry.get("project")
                    if not isinstance(existing_project, dict):
                        entry["project"] = {"id": project_id, "name": name}
                    else:
                        existing_project.setdefault("name", name)

        if workspace:
            # Pre-load tasks for projects that actually appear in entries
            unique_project_ids = set()
            for entry in normalized_entries:
                project_id = entry.get("project_id")
                task_id = entry.get("task_id")
                if project_id and task_id:
                    try:
                        unique_project_ids.add(int(project_id))
                    except (TypeError, ValueError):
                        pass
            
            # Load tasks for each unique project using correct cache structure
            workspace_key = str(workspace)
            project_cache = self._task_cache.setdefault(workspace_key, {})
            for project_id in unique_project_ids:
                # Check if tasks for this project are already cached
                if project_id not in project_cache or not project_cache[project_id]:
                    try:
                        tasks = self.get_project_tasks(project_id, workspace)
                        task_cache = project_cache.setdefault(project_id, {})
                        for task in tasks or []:
                            tid = task.get("id")
                            name = task.get("name")
                            try:
                                tid_int = int(tid)
                            except (TypeError, ValueError):
                                continue
                            task_cache[tid_int] = name
                    except Exception:
                        pass  # If loading fails, _lookup_task_name will handle it as fallback
            
            for entry in normalized_entries:
                if entry.get("task_name"):
                    continue
                task_id = entry.get("task_id")
                project_id = entry.get("project_id")
                name = self._lookup_task_name(workspace, project_id, task_id)
                if name:
                    entry["task_name"] = name
                    existing_task = entry.get("task")
                    if not isinstance(existing_task, dict):
                        entry["task"] = {"id": task_id, "name": name}
                    else:
                        existing_task.setdefault("name", name)

        # Convert to TimeEntry objects
        entries: List[TimeEntry] = []
        for entry_data in normalized_entries:
            try:
                entry = TimeEntry.from_toggl_data(entry_data)
                entries.append(entry)
            except Exception as e:
                # Log error but continue with other entries
                print(f"Warning: Failed to parse time entry {entry_data.get('id', 'unknown')}: {e}")
                continue

        return entries

    def _cache_file_path(self, workspace: Optional[Any], start: date, end: date) -> Path:
        workspace_key = str(workspace or self.workspace_id or "default")
        workspace_dir = self._toggl_cache_dir / workspace_key
        workspace_dir.mkdir(parents=True, exist_ok=True)
        return workspace_dir / f"{start:%Y%m%d}_{end:%Y%m%d}.json"
    
    def _projects_cache_path(self, workspace: Optional[Any]) -> Path:
        """Get cache path for projects."""
        workspace_key = str(workspace or self.workspace_id or "default")
        workspace_dir = self._toggl_cache_dir / workspace_key
        workspace_dir.mkdir(parents=True, exist_ok=True)
        return workspace_dir / "projects.json"
    
    def _users_cache_path(self, workspace: Optional[Any]) -> Path:
        """Get cache path for users."""
        workspace_key = str(workspace or self.workspace_id or "default")
        workspace_dir = self._toggl_cache_dir / workspace_key
        workspace_dir.mkdir(parents=True, exist_ok=True)
        return workspace_dir / "users.json"

    @staticmethod
    def _parse_iso_to_date(value: Optional[str]) -> Optional[date]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None

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
    
    def _calculate_data_hash(self, entries: List[Dict[str, Any]]) -> str:
        """Calculate hash of time entries data for change detection."""
        if not entries:
            return ""
        
        # Create a hash based on entry IDs and updated_at timestamps
        hash_data = []
        for entry in entries:
            entry_id = entry.get('id') or entry.get('time_entry_id')
            updated_at = entry.get('updated_at') or entry.get('at')
            hash_data.append(f"{entry_id}:{updated_at}")
        
        hash_data.sort()
        hash_string = "|".join(hash_data)
        return hashlib.md5(hash_string.encode('utf-8')).hexdigest()
    
    def _calculate_projects_hash(self, projects: List[Dict[str, Any]]) -> str:
        """Calculate hash of projects data for change detection."""
        if not projects:
            return ""
        
        # Create a hash based on project IDs and updated_at timestamps
        hash_data = []
        for project in projects:
            project_id = project.get('id') or project.get('project_id')
            updated_at = project.get('at') or project.get('updated_at') or project.get('server_deleted_at')
            hash_data.append(f"{project_id}:{updated_at}")
        
        hash_data.sort()
        hash_string = "|".join(hash_data)
        return hashlib.md5(hash_string.encode('utf-8')).hexdigest()
    
    def _is_cache_fresh(
        self,
        workspace_id: Optional[int],
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
    
    def _is_projects_cache_fresh(self, cache_metadata: Optional[Dict[str, Any]]) -> tuple[bool, bool]:
        """
        Check if projects cache is fresh. Returns (is_fresh, has_dirty_ranges).
        
        Projects cache TTL: 30 days (monthly refresh)
        """
        if not cache_metadata or not cache_metadata.get('last_full_fetch'):
            return False, False
        
        try:
            last_fetch = datetime.fromisoformat(cache_metadata['last_full_fetch'])
            days_old = (datetime.now() - last_fetch).days
            
            # Projects cache TTL is 30 days
            ttl_days = 30
            
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
            user_id = user.get('id') or user.get('user_id')
            updated_at = user.get('updated_at') or user.get('at') or user.get('modified_at')
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

    def _load_cached_entries(self, path: Path) -> Optional[List[Dict[str, Any]]]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except FileNotFoundError:
            return None
        except Exception:
            return None

    def _store_cached_entries(self, path: Path, entries: List[Dict[str, Any]]) -> None:
        try:
            with path.open("w", encoding="utf-8") as handle:
                json.dump(entries, handle)
        except Exception:
            pass
    
    def _load_cached_projects(self, path: Path) -> Optional[List[Dict[str, Any]]]:
        """Load cached projects from file."""
        try:
            with path.open("r", encoding="utf-8") as handle:
                raw = json.load(handle)
            items, _ = self._normalize_projects_payload(raw)
            return items if items else None
        except FileNotFoundError:
            return None
        except Exception:
            return None
    
    def _store_cached_projects(self, path: Path, projects: List[Dict[str, Any]]) -> None:
        """Store projects cache to file."""
        try:
            with path.open("w", encoding="utf-8") as handle:
                json.dump(projects, handle)
        except Exception:
            pass

    # Convenience wrappers using timezone-aware ranges
    def get_time_entries_last_week(self, user_ids: Optional[List[int]] = None) -> List[TimeEntry]:
        start_iso, end_iso = last_week_range(self.settings.timezone)
        return self.get_time_entries(start_iso, end_iso, user_ids=user_ids)

    def get_time_entries_last_month(self, user_ids: Optional[List[int]] = None) -> List[TimeEntry]:
        start_iso, end_iso = last_month_range(self.settings.timezone)
        return self.get_time_entries(start_iso, end_iso, user_ids=user_ids)

    def get_time_entries_current_week(self, user_ids: Optional[List[int]] = None) -> List[TimeEntry]:
        start_iso, end_iso = current_week_range(self.settings.timezone)
        return self.get_time_entries(start_iso, end_iso, user_ids=user_ids)

    def get_time_entries_current_month_to_date(self, user_ids: Optional[List[int]] = None) -> List[TimeEntry]:
        start_iso, end_iso = current_month_to_date_range(self.settings.timezone)
        return self.get_time_entries(start_iso, end_iso, user_ids=user_ids)
    
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
    
    def get_project_first_tracking_date(
        self,
        project: Project,
        workspace_id: Optional[int] = None
    ) -> Optional[date]:
        """
        Find the first date when project was tracked (earliest time entry for the project).
        Uses project.start_date and searches from (start_date - 1 month) to today.
        Cache is created per month for the entire period.
        
        Args:
            project: Project object with start_date
            workspace_id: Workspace ID (defaults to settings.workspace_id)
        
        Returns:
            Date of first tracking or None if not found
        """
        workspace = workspace_id or self.workspace_id
        if not workspace:
            return None
        
        # Get project start_date, if not available use created_at or default to 1 year ago
        project_start = project.start_date
        if not project_start and project.created_at:
            project_start = project.created_at.date()
        
        if not project_start:
            # Fallback: search last year
            today = date.today()
            project_start = today.replace(year=today.year - 1, month=1, day=1)
        
        # Calculate search period: (start_date - 1 month) to today
        search_start = project_start
        if search_start.month == 1:
            search_start = search_start.replace(year=search_start.year - 1, month=12)
        else:
            search_start = search_start.replace(month=search_start.month - 1)
        
        today = date.today()
        search_end = today
        
        # Generate monthly sequence for caching
        months_to_search = []
        current = search_start.replace(day=1)
        end_month = search_end.replace(day=1)
        while current <= end_month:
            months_to_search.append((current.year, current.month))
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        
        # Fetch time entries month by month (this ensures cache is created per month)
        all_entries = []
        earliest_date = None
        matching_entries_count = 0
        
        for year, month in months_to_search:
            month_start = date(year, month, 1)
            if month == 12:
                month_end = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                month_end = date(year, month + 1, 1) - timedelta(days=1)
            
            # Adjust first and last month to match search period
            if month_start < search_start:
                month_start = search_start
            if month_end > search_end:
                month_end = search_end
            
            start_iso = f"{month_start}T00:00:00Z"
            end_iso = f"{month_end}T23:59:59Z"
            
            try:
                # Fetch entries for this month (will use cache if available, create if not)
                month_entries = self.get_time_entries(start_iso, end_iso, workspace_id=workspace, force_refresh=False)
                all_entries.extend(month_entries)
            except Exception:
                continue
        
        if not all_entries:
            return None
        
        # Find earliest entry for the project
        for entry in all_entries:
            matched = False
            
            # Match by project_id
            if project.project_id is not None and entry.project_id == project.project_id:
                entry_date = entry.date
                matching_entries_count += 1
                if earliest_date is None or entry_date < earliest_date:
                    earliest_date = entry_date
                matched = True
                continue
            
            # Match by project_name if not matched by ID
            if not matched and project.name:
                normalized_search = self._normalize_project_name(project.name)
                entry_project_name = entry.project_name or ""
                normalized_entry = self._normalize_project_name(entry_project_name)
                if normalized_search == normalized_entry:
                    entry_date = entry.date
                    matching_entries_count += 1
                    if earliest_date is None or entry_date < earliest_date:
                        earliest_date = entry_date
                    matched = True
        
        return earliest_date
    
    @staticmethod
    def _normalize_project_name(name: Optional[str]) -> str:
        """Normalize project name for comparison."""
        return (name or "").strip().lower()