"""
Toggl Track API service.
"""

import base64
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime

from ..config import Settings
from ..models.time_entry import TimeEntry
from ..logic.date_ranges import last_week_range, last_month_range, current_week_range, current_month_to_date_range


class TogglService:
    """Service for interacting with Toggl Track API."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.toggl_base_url
        self.reports_base_url = settings.toggl_reports_base_url
        self.token = settings.toggl_api_token
        self.workspace_id = settings.workspace_id
        self._project_cache: Dict[str, Dict[int, str]] = {}
        self._task_cache: Dict[str, Dict[int, Dict[int, str]]] = {}
    
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

    def get_project_tasks(self, project_id: int, workspace_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get list of tasks for a project."""
        workspace = workspace_id or self.workspace_id
        if not workspace:
            raise ValueError("Workspace ID is required")

        return self._make_request(f"/workspaces/{workspace}/projects/{project_id}/tasks")

    def _lookup_project_name(self, workspace: Optional[int], project_id: Optional[int]) -> Optional[str]:
        """Resolve project name using a per-workspace cache."""
        if workspace is None or project_id is None:
            return None
        try:
            project_id_int = int(project_id)
        except (TypeError, ValueError):
            return None

        workspace_key = str(workspace)
        cache = self._project_cache.setdefault(workspace_key, {})
        if project_id_int in cache:
            return cache[project_id_int]

        try:
            workspace_param = int(workspace)
        except (TypeError, ValueError):
            return None

        try:
            projects = self.get_projects(workspace_param)
        except Exception:
            return None

        for project in projects or []:
            pid = project.get("id")
            name = project.get("name")
            try:
                pid_int = int(pid)
            except (TypeError, ValueError):
                continue
            cache[pid_int] = name

        return cache.get(project_id_int)

    def _lookup_task_name(
        self,
        workspace: Optional[int],
        project_id: Optional[int],
        task_id: Optional[int],
    ) -> Optional[str]:
        """Resolve task name using a project-scoped cache."""
        if workspace is None or project_id is None or task_id is None:
            return None
        try:
            workspace_key = str(int(workspace))
            project_id_int = int(project_id)
            task_id_int = int(task_id)
        except (TypeError, ValueError):
            return None

        project_cache = self._task_cache.setdefault(workspace_key, {})
        task_cache = project_cache.setdefault(project_id_int, {})
        if task_id_int in task_cache:
            return task_cache[task_id_int]

        try:
            tasks = self.get_project_tasks(project_id_int, int(workspace))
        except Exception:
            return None

        for task in tasks or []:
            tid = task.get("id")
            name = task.get("name")
            try:
                tid_int = int(tid)
            except (TypeError, ValueError):
                continue
            task_cache[tid_int] = name

        return task_cache.get(task_id_int)
    
    def get_time_entries(
        self,
        start_date: str,
        end_date: str,
        workspace_id: Optional[int] = None,
        user_ids: Optional[List[int]] = None,
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
                # Common shape: { "time_entries": [ ... ], ... }
                entries_data = data.get("time_entries") or data.get("data") or []
            else:
                entries_data = data or []
        else:
            # No workspace provided; use current user endpoint (only current user data allowed)
            params = {"start_date": start_date, "end_date": end_date}
            entries_data = self._make_request("/me/time_entries", params)

        raw_entries = entries_data or []

        # Filter by user_id locally if requested (Reports API returns all users)
        if user_ids:
            target_ids = {int(u) for u in user_ids}
            filtered: List[Dict[str, Any]] = []
            for entry_data in raw_entries:
                if not isinstance(entry_data, dict):
                    continue
                uid = entry_data.get("user_id")
                if uid is None and isinstance(entry_data.get("user"), dict):
                    uid = entry_data["user"].get("id")
                try:
                    uid_int = int(uid) if uid is not None else None
                except (TypeError, ValueError):
                    uid_int = None
                if uid_int is None:
                    continue
                if uid_int in target_ids:
                    filtered.append(entry_data)
            raw_entries = filtered

        # Normalize Reports API payload (often nested under 'time_entry' or 'time_entries')
        normalized_entries: List[Dict[str, Any]] = []

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

        if workspace:
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
