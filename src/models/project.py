"""
Project model for Toggl data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional, Dict, Any


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class Project:
    """Represents a Toggl project with useful metadata."""

    project_id: int
    name: str
    workspace_id: Optional[int] = None
    client_id: Optional[int] = None
    active: bool = True
    billable: Optional[bool] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_toggl(cls, data: Dict[str, Any]) -> "Project":
        """Create a Project instance from Toggl API payload."""
        project_id = data.get("id") or data.get("project_id")
        if project_id is None:
            raise ValueError("Project payload missing 'id'")
        name = data.get("name") or f"Project {project_id}"
        start_date = (
            _parse_date(data.get("start_date"))
            or _parse_date(data.get("startDate"))
            or _parse_date(data.get("start"))
        )
        end_date = _parse_date(data.get("end_date")) or _parse_date(data.get("endDate"))
        created_at = _parse_datetime(data.get("created_at") or data.get("createdAt"))
        updated_at = _parse_datetime(data.get("at") or data.get("updated_at") or data.get("updatedAt"))

        return cls(
            project_id=int(project_id) if project_id is not None else 0,
            name=name,
            workspace_id=data.get("workspace_id") or data.get("wid"),
            client_id=data.get("client_id") or data.get("cid"),
            active=bool(data.get("active", True)),
            billable=data.get("billable"),
            start_date=start_date,
            end_date=end_date,
            created_at=created_at,
            updated_at=updated_at,
        )

    @property
    def is_billable_active(self) -> bool:
        """Return True when the project is active and billable (or unspecified)."""
        return bool(self.active) and (self.billable is None or bool(self.billable))
