
"""
Model representing a Timetastic public holiday record.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date
from typing import Any, Dict, Optional


@dataclass
class PublicHoliday:
    """Represents a public/bank holiday returned by Timetastic."""

    timetastic_id: int
    name: str
    date: date
    formatted_date: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    country_code: Optional[str] = None
    bank_holiday_set_id: Optional[int] = None

    @classmethod
    def from_timetastic_data(cls, data: Dict[str, Any]) -> "PublicHoliday":
        """Build a PublicHoliday instance from raw Timetastic API data."""
        raw_date = data.get("date") or data.get("Date")
        holiday_date = cls._parse_date(raw_date)

        created_at = cls._parse_datetime(data.get("createdAt") or data.get("CreatedAt"))
        updated_at = cls._parse_datetime(data.get("updatedAt") or data.get("UpdatedAt"))

        return cls(
            timetastic_id=int(data["id"]),
            name=str(data.get("name") or data.get("Name") or "Public Holiday"),
            date=holiday_date or date.today(),
            formatted_date=data.get("formattedDate") or data.get("FormattedDate"),
            created_at=created_at,
            updated_at=updated_at,
            country_code=data.get("countryCode") or data.get("CountryCode"),
            bank_holiday_set_id=_safe_int(data.get("bankHolidaySetId") or data.get("BankHolidaySetId")),
        )

    @staticmethod
    def _parse_date(value: Optional[str]) -> Optional[date]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return datetime.strptime(value.split("T")[0], "%Y-%m-%d").date()
            except (ValueError, IndexError):
                return None

    @staticmethod
    def _parse_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the public holiday to a dict."""
        return {
            "timetastic_id": self.timetastic_id,
            "name": self.name,
            "date": self.date.isoformat(),
            "formatted_date": self.formatted_date,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "country_code": self.country_code,
            "bank_holiday_set_id": self.bank_holiday_set_id,
        }


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
