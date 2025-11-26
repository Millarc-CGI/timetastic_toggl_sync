"""
Data aggregator for merging Toggl and Timetastic data.
"""

from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date, timedelta
from collections import defaultdict

from ..config import Settings
from ..models.user import User
from ..models.time_entry import TimeEntry
from ..models.absence import Absence


class DataAggregator:
    """Aggregates and merges data from Toggl and Timetastic."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.default_daily_hours = settings.default_daily_hours
        # Absence rules will be defined here in the logic layer
        self.absence_rules = {
            "vacation": "DEFAULT_HOURS",
            "holiday": "DEFAULT_HOURS",
            "maternity": "DEFAULT_HOURS",
            "paternity": "DEFAULT_HOURS"
        }
        self.remote_work_types = {"remote work", "remote_work", "remote"}
        self.full_day_types = {
            "meeting",
            "sick",
            "sick leave",
            "compassionate",
            "workshops",
            "paternity",
            "maternity"
        }
        self.pto_like_types = {"pto", "medical appointment", "medical_appointment"}
        self.partial_pto_cap = 2.5
    
    def aggregate_daily(
        self, 
        user_email: str,
        target_date: date,
        time_entries: List[TimeEntry],
        absences: List[Absence]
    ) -> Dict[str, Any]:
        """Aggregate data for a single user for a single day."""
        
        # Filter entries for the specific date
        day_entries = [entry for entry in time_entries if entry.date == target_date]

        # Check for absences on this date
        day_absences = [abs for abs in absences if abs.is_date_in_range(target_date)]

        # Calculate total hours from time entries
        total_hours = sum(entry.duration_hours for entry in day_entries)
        billable_hours = sum(entry.duration_hours for entry in day_entries if entry.billable)
        is_weekend = target_date.weekday() >= 5

        # Handle absences
        absence_hours = 0.0
        absence_entries: List[Dict[str, Any]] = []
        needs_absence_review = False
        absence_review_notes: List[str] = []

        for absence in day_absences:
            info = self._classify_absence(absence, target_date, total_hours + absence_hours)
            if not info:
                continue
            absence_hours += info['hours']
            if info.get('requires_review'):
                needs_absence_review = True
                note = info.get('review_reason')
                if note:
                    absence_review_notes.append(note)
            absence_entries.append(info)

        # Calculate total hours (time entries + absence hours)
        total_daily_hours = total_hours + absence_hours

        # Project + task breakdown
        project_hours = defaultdict(float)
        project_task_hours = defaultdict(lambda: defaultdict(float))
        project_hours_by_id = defaultdict(float)
        project_task_hours_by_id = defaultdict(lambda: defaultdict(float))
        project_names_by_id: Dict[int, str] = {}
        for entry in day_entries:
            project_name = entry.project_name or "No Project"
            project_id = entry.project_id
            task_name = entry.task_name or entry.description or "No Task"
            project_hours[project_name] += entry.duration_hours
            project_task_hours[project_name][task_name] += entry.duration_hours
            if project_id is not None:
                project_hours_by_id[project_id] += entry.duration_hours
                project_task_hours_by_id[project_id][task_name] += entry.duration_hours
                project_names_by_id[project_id] = project_name

        has_holiday_absence = any(
            'holiday' in (entry.get('absence_type') or '').lower()
            for entry in absence_entries
        )
        effective_weekend = is_weekend or has_holiday_absence

        return {
            'date': target_date,
            'user_email': user_email,
            'time_entry_hours': total_hours,
            'absence_hours': absence_hours,
            'total_hours': total_daily_hours,
            'billable_hours': billable_hours,
            'absence_type': absence_entries[0]['absence_type'] if absence_entries else None,
            'absence_details': absence_entries,
            'needs_absence_review': needs_absence_review,
            'absence_review_notes': absence_review_notes,
            'project_hours': dict(project_hours),
            'time_entries_count': len(day_entries),
            'has_entries': len(day_entries) > 0,
            'has_absence': len(day_absences) > 0,
            'is_weekend': effective_weekend,
            'is_actual_weekend': is_weekend,
            'is_public_holiday': has_holiday_absence,
            'weekend_hours': total_hours if effective_weekend else 0.0,
            'task_hours': {
                project: dict(tasks) for project, tasks in project_task_hours.items()
            },
            'project_hours_by_id': dict(project_hours_by_id),
            'project_task_hours_by_id': {
                project_id: dict(tasks) for project_id, tasks in project_task_hours_by_id.items()
            },
            'project_names_by_id': project_names_by_id
        }
    
    def aggregate_monthly(
        self,
        user_email: str,
        year: int,
        month: int,
        time_entries: List[TimeEntry],
        absences: List[Absence]
    ) -> Dict[str, Any]:
        """Aggregate data for a single user for a full month."""
        
        # Filter data for the month
        start_date = date(year, month, 1)
        if month == 12:
            end_date = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(year, month + 1, 1) - timedelta(days=1)
        
        month_entries = [
            entry for entry in time_entries 
            if start_date <= entry.date <= end_date
        ]
        
        month_absences = [
            absence for absence in absences
            if absence.start_date <= end_date and absence.end_date >= start_date
        ]
        
        # Daily aggregation
        daily_data = []
        total_hours = 0
        total_billable_hours = 0
        total_absence_hours = 0
        
        project_hours = defaultdict(float)
        absence_hours_breakdown = defaultdict(float)
        missing_days = []
        absence_review_days: List[Dict[str, Any]] = []
        project_task_hours = defaultdict(lambda: defaultdict(float))
        project_hours_by_id = defaultdict(float)
        project_task_hours_by_id = defaultdict(lambda: defaultdict(float))
        project_activity_dates: Dict[Any, Dict[str, Optional[date]]] = {}
        project_names_by_id: Dict[Any, str] = {}
        today = date.today()
        
        current_date = start_date
        while current_date <= end_date:
            day_data = self.aggregate_daily(user_email, current_date, month_entries, month_absences)
            daily_data.append(day_data)
            
            total_hours += day_data['total_hours']
            total_billable_hours += day_data['billable_hours']
            total_absence_hours += day_data['absence_hours']
            
            # Aggregate project hours
            for project, hours in day_data['project_hours'].items():
                project_hours[project] += hours

            for project_id, hours in day_data.get('project_hours_by_id', {}).items():
                project_hours_by_id[project_id] += hours
                if hours > 0:
                    info = project_activity_dates.setdefault(project_id, {'start': None, 'end': None})
                    if info['start'] is None or day_data['date'] < info['start']:
                        info['start'] = day_data['date']
                    if info['end'] is None or day_data['date'] > info['end']:
                        info['end'] = day_data['date']
            
            # Track absence types by hours
            for absence_detail in day_data.get('absence_details', []):
                absence_hours_breakdown[absence_detail['absence_type']] += absence_detail['hours']
            
            # Track missing days (no entries and no absence) but skip today/future
            if (
                current_date < today
                and not day_data['has_entries']
                and not day_data['has_absence']
                and not day_data['is_weekend']
            ):
                missing_days.append(current_date)

            if day_data.get('needs_absence_review'):
                absence_review_days.append({
                    'date': current_date,
                    'notes': day_data.get('absence_review_notes', [])
                })

            for project, tasks in day_data.get('task_hours', {}).items():
                for task, hours in tasks.items():
                    project_task_hours[project][task] += hours

            for project_id, tasks in day_data.get('project_task_hours_by_id', {}).items():
                for task, hours in tasks.items():
                    project_task_hours_by_id[project_id][task] += hours

            for project_id, name in (day_data.get('project_names_by_id') or {}).items():
                project_names_by_id[project_id] = name

            current_date += timedelta(days=1)
        
        # Calculate working days in month
        working_days = len([d for d in daily_data if d['total_hours'] > 0])

        absence_breakdown = {
            absence_type: hours / self.default_daily_hours if self.default_daily_hours else hours
            for absence_type, hours in absence_hours_breakdown.items()
        }
        
        return {
            'user_email': user_email,
            'year': year,
            'month': month,
            'period_start': start_date,
            'period_end': end_date,
            'total_hours': total_hours,
            'billable_hours': total_billable_hours,
            'absence_hours': total_absence_hours,
            'working_days': working_days,
            'project_hours': dict(project_hours),
            'absence_breakdown': absence_breakdown,
            'absence_hours_breakdown': dict(absence_hours_breakdown),
            'missing_days': missing_days,
            'absence_review_days': absence_review_days,
            'daily_data': daily_data,
            'time_entries_count': len(month_entries),
            'absences_count': len(month_absences),
            'project_task_hours': {
                project: dict(tasks) for project, tasks in project_task_hours.items()
            },
            'project_hours_by_id': dict(project_hours_by_id),
            'project_task_hours_by_id': {
                project_id: dict(tasks) for project_id, tasks in project_task_hours_by_id.items()
            },
            'project_activity_dates': {
                project_id: {
                    'start': info.get('start'),
                    'end': info.get('end')
                } for project_id, info in project_activity_dates.items()
            },
            'project_names_by_id': project_names_by_id
        }
    
    def aggregate_all_users(
        self,
        users: List[User],
        time_entries: List[TimeEntry],
        absences: List[Absence],
        year: int,
        month: int
    ) -> Dict[str, Any]:
        """Aggregate data for all users for a month."""
        
        all_user_data = {}
        total_hours_all = 0
        total_billable_all = 0
        total_users = len(users)
        
        # Group entries by user
        entries_by_user = defaultdict(list)
        for entry in time_entries:
            if entry.user_email:
                entries_by_user[entry.user_email.lower()].append(entry)
        
        absences_by_user = defaultdict(list)
        for absence in absences:
            if absence.user_email:
                absences_by_user[absence.user_email.lower()].append(absence)
        
        # Process each user
        for user in users:
            user_email = user.email.lower()
            user_entries = entries_by_user.get(user_email, [])
            user_absences = absences_by_user.get(user_email, [])
            
            user_data = self.aggregate_monthly(user_email, year, month, user_entries, user_absences)
            all_user_data[user_email] = user_data
            
            total_hours_all += user_data['total_hours']
            total_billable_all += user_data['billable_hours']
        
        # Project statistics across all users
        all_project_hours = defaultdict(float)
        for user_data in all_user_data.values():
            for project, hours in user_data['project_hours'].items():
                all_project_hours[project] += hours
        
        return {
            'year': year,
            'month': month,
            'total_users': total_users,
            'total_hours_all': total_hours_all,
            'total_billable_all': total_billable_all,
            'average_hours_per_user': total_hours_all / total_users if total_users > 0 else 0,
            'all_project_hours': dict(all_project_hours),
            'user_data': all_user_data
        }


    def _calculate_absence_hours_for_date(self, absence: Absence, target_date: date) -> float:
        """Determine how many hours of an absence apply to a specific date."""
        default_hours = self.default_daily_hours
        absence_type = (absence.absence_type or "").lower()
        is_weekend = target_date.weekday() >= 5
        is_public_holiday = "holiday" in absence_type

        if is_weekend and not is_public_holiday:
            # Skip non-working weekend days
            return 0.0

        partial_fraction = self._get_partial_day_fraction(absence, target_date)
        if partial_fraction is not None:
            return default_hours * partial_fraction

        total_hours = absence.duration_hours(default_hours)
        working_days = self._working_days_between(absence.start_date, absence.end_date)
        if working_days <= 0:
            working_days = max(1, absence.duration_days)
        return min(default_hours, total_hours / working_days) if working_days else default_hours

    @staticmethod
    def _working_days_between(start_date: date, end_date: date) -> int:
        days = 0
        current = start_date
        while current <= end_date:
            if current.weekday() < 5:
                days += 1
            current += timedelta(days=1)
        return days

    def _classify_absence(self, absence: Absence, target_date: date, current_total_hours: float) -> Optional[Dict[str, Any]]:
        absence_type = (absence.absence_type or "unknown").strip().lower()
        if absence_type in self.remote_work_types:
            return None

        hours_for_day = self._calculate_absence_hours_for_date(absence, target_date)
        if hours_for_day <= 0:
            return None

        entry: Dict[str, Any] = {
            'absence_type': absence_type,
            'hours': hours_for_day,
            'original_hours': hours_for_day,
            'booking_unit': absence.booking_unit,
            'requires_review': False,
            'review_reason': None,
            'absence_id': absence.timetastic_id,
        }

        if absence_type in self.full_day_types:
            entry['hours'] = self.default_daily_hours
        elif absence_type in self.pto_like_types:
            adjusted, needs_review, note = self._adjust_pto_hours(absence, hours_for_day, current_total_hours)
            entry['hours'] = adjusted
            entry['requires_review'] = needs_review
            entry['review_reason'] = note
        elif absence_type in self.absence_rules:
            rule = self.absence_rules[absence_type]
            if rule == "DEFAULT_HOURS":
                entry['hours'] = self.default_daily_hours
            elif isinstance(rule, (int, float)):
                entry['hours'] = float(rule)

        entry['hours'] = max(0.0, entry['hours'])
        return entry

    def _adjust_pto_hours(self, absence: Absence, hours_for_day: float, current_total_hours: float) -> Tuple[float, bool, Optional[str]]:
        target = self.default_daily_hours
        requires_review = False
        review_reason = None
        is_full_day = self._is_full_day_absence(hours_for_day)
        if is_full_day:
            adjusted_hours = target
        else:
            adjusted_hours = min(hours_for_day, self.partial_pto_cap)

        remaining_capacity = max(0.0, target - current_total_hours)
        adjusted_hours = min(adjusted_hours, remaining_capacity)
        combined = self._round_to_half_hour(current_total_hours + adjusted_hours)

        if combined < target:
            requires_review = True
            review_reason = (
                f"PTO deficit: worked {combined:.1f}h (< {target:.1f}h)"
            )
        return adjusted_hours, requires_review, review_reason

    def _is_full_day_absence(self, hours_for_day: float) -> bool:
        return hours_for_day >= (self.default_daily_hours - 0.25)

    def _get_partial_day_fraction(self, absence: Absence, target_date: date) -> Optional[float]:
        """Infer if the absence only covers half a day."""
        marker_start = self._normalize_half_day_marker(absence.start_type)
        marker_end = self._normalize_half_day_marker(absence.end_type)

        if absence.is_single_day:
            if marker_start and marker_end:
                if marker_start == marker_end:
                    return 0.5
                if marker_start == "am" and marker_end == "pm":
                    return 1.0
            return None

        if target_date == absence.start_date and marker_start == "pm":
            return 0.5
        if target_date == absence.end_date and marker_end == "am":
            return 0.5
        return None

    @staticmethod
    def _normalize_half_day_marker(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        normalized = value.strip().lower()
        mapping = {
            "am": "am",
            "pm": "pm",
            "morning": "am",
            "afternoon": "pm",
            "first_half": "am",
            "second_half": "pm",
            "firsthalf": "am",
            "secondhalf": "pm",
            "first half": "am",
            "second half": "pm",
        }
        return mapping.get(normalized, None)

    @staticmethod
    def _round_to_half_hour(value: float) -> float:
        return round(value * 2) / 2.0

    def fill_absence_hours(
        self,
        time_entries: List[TimeEntry],
        absences: List[Absence],
        target_date: date
    ) -> List[Dict[str, Any]]:
        """Fill in absence hours for days with no time entries but with approved absences."""
        
        # Group by user email
        entries_by_user = defaultdict(list)
        for entry in time_entries:
            if entry.user_email and entry.date == target_date:
                entries_by_user[entry.user_email.lower()].append(entry)
        
        absences_by_user = defaultdict(list)
        for absence in absences:
            if absence.user_email and absence.is_date_in_range(target_date):
                absences_by_user[absence.user_email.lower()].append(absence)
        
        filled_hours = []
        
        # Process each user with absences
        for user_email, user_absences in absences_by_user.items():
            user_entries = entries_by_user.get(user_email, [])
            
            # If user has absence but no time entries, add absence hours
            if not user_entries and user_absences:
                total_hours = 0.0
                types = []
                absence_id = None
                for absence in user_absences:
                    hours = self._calculate_absence_hours_for_date(absence, target_date)
                    if hours <= 0:
                        continue
                    total_hours += hours
                    types.append(absence.absence_type.lower())
                    absence_id = absence.timetastic_id
                if total_hours <= 0:
                    continue

                filled_hours.append({
                    'user_email': user_email,
                    'date': target_date,
                    'hours': total_hours,
                    'absence_type': ', '.join(types) if types else 'unknown',
                    'absence_id': absence_id,
                    'is_filled': True
                })

        return filled_hours
    
    def detect_missing_entries(
        self,
        users: List[User],
        time_entries: List[TimeEntry],
        absences: List[Absence],
        start_date: date,
        end_date: date
    ) -> Dict[str, List[date]]:
        """Detect missing time entries for users."""
        
        missing_by_user = defaultdict(list)
        
        # Group data by user
        entries_by_user = defaultdict(set)
        for entry in time_entries:
            if entry.user_email and start_date <= entry.date <= end_date:
                entries_by_user[entry.user_email.lower()].add(entry.date)
        
        absences_by_user = defaultdict(set)
        for absence in absences:
            if absence.user_email:
                # Add all dates in the absence range
                current_date = absence.start_date
                while current_date <= absence.end_date:
                    if start_date <= current_date <= end_date:
                        absences_by_user[absence.user_email.lower()].add(current_date)
                    current_date += timedelta(days=1)
        
        # Check each user
        for user in users:
            user_email = user.email.lower()
            user_entries = entries_by_user.get(user_email, set())
            user_absences = absences_by_user.get(user_email, set())
            
            # Check each date in the range
            current_date = start_date
            while current_date <= end_date:
                # Skip weekends (optional - could be configurable)
                if current_date.weekday() < 5:  # Monday = 0, Friday = 4
                    has_entry = current_date in user_entries
                    has_absence = current_date in user_absences
                    
                    if not has_entry and not has_absence:
                        missing_by_user[user_email].append(current_date)
                
                current_date += timedelta(days=1)
        
        return dict(missing_by_user)
    
    def validate_data_consistency(
        self,
        time_entries: List[TimeEntry],
        absences: List[Absence]
    ) -> Dict[str, List[str]]:
        """Validate data consistency and return issues."""
        
        issues = {
            'orphaned_entries': [],
            'overlapping_absences': [],
            'invalid_durations': [],
            'missing_user_mappings': []
        }
        
        # Check for entries with missing user mappings
        for entry in time_entries:
            if not entry.user_email:
                issues['missing_user_mappings'].append(f"Time entry {entry.toggl_id} has no user email")
        
        # Check for absences with missing user mappings
        for absence in absences:
            if not absence.user_email:
                issues['missing_user_mappings'].append(f"Absence {absence.timetastic_id} has no user email")
        
        # Check for invalid durations
        for entry in time_entries:
            if entry.duration_seconds < 0 and not entry.is_running:
                issues['invalid_durations'].append(f"Time entry {entry.toggl_id} has negative duration")
            elif entry.duration_hours > 24:
                issues['invalid_durations'].append(f"Time entry {entry.toggl_id} has suspiciously long duration: {entry.duration_hours:.1f}h")
        
        # Check for overlapping absences (same user, overlapping dates)
        absences_by_user = defaultdict(list)
        for absence in absences:
            absences_by_user[absence.user_email.lower()].append(absence)
        
        for user_email, user_absences in absences_by_user.items():
            for i, abs1 in enumerate(user_absences):
                for abs2 in user_absences[i+1:]:
                    # Check for overlap
                    if (abs1.start_date <= abs2.end_date and abs2.start_date <= abs1.end_date):
                        issues['overlapping_absences'].append(
                            f"User {user_email} has overlapping absences: {abs1.absence_type} ({abs1.start_date} to {abs1.end_date}) and {abs2.absence_type} ({abs2.start_date} to {abs2.end_date})"
                        )
        
        return issues
