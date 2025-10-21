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
            "sick": 0,
            "personal": 0,
            "holiday": "DEFAULT_HOURS",
            "maternity": "DEFAULT_HOURS",
            "paternity": "DEFAULT_HOURS"
        }
    
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
        
        # Handle absences
        absence_hours = 0
        absence_type = None
        
        if day_absences:
            absence = day_absences[0]  # Take the first absence if multiple
            absence_type = absence.absence_type.lower()
            
            # Apply absence rules
            if absence_type in self.absence_rules:
                rule = self.absence_rules[absence_type]
                if rule == "DEFAULT_HOURS":
                    absence_hours = self.default_daily_hours
                elif isinstance(rule, (int, float)):
                    absence_hours = rule
                else:
                    absence_hours = self.default_daily_hours
            else:
                # Default rule for unknown absence types
                absence_hours = self.default_daily_hours
        
        # Calculate total hours (time entries + absence hours)
        total_daily_hours = total_hours + absence_hours
        
        # Project breakdown
        project_hours = defaultdict(float)
        for entry in day_entries:
            project_name = entry.project_name or "No Project"
            project_hours[project_name] += entry.duration_hours
        
        return {
            'date': target_date,
            'user_email': user_email,
            'time_entry_hours': total_hours,
            'absence_hours': absence_hours,
            'total_hours': total_daily_hours,
            'billable_hours': billable_hours,
            'absence_type': absence_type,
            'project_hours': dict(project_hours),
            'time_entries_count': len(day_entries),
            'has_entries': len(day_entries) > 0,
            'has_absence': len(day_absences) > 0
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
        absence_breakdown = defaultdict(int)
        missing_days = []
        
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
            
            # Track absence types
            if day_data['absence_type']:
                absence_breakdown[day_data['absence_type']] += 1
            
            # Track missing days (no entries and no absence)
            if not day_data['has_entries'] and not day_data['has_absence']:
                missing_days.append(current_date)
            
            current_date += timedelta(days=1)
        
        # Calculate working days in month
        working_days = len([d for d in daily_data if d['total_hours'] > 0])
        
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
            'absence_breakdown': dict(absence_breakdown),
            'missing_days': missing_days,
            'daily_data': daily_data,
            'time_entries_count': len(month_entries),
            'absences_count': len(month_absences)
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
                absence = user_absences[0]  # Take first absence
                absence_type = absence.absence_type.lower()
                
                # Determine hours based on absence rules
                hours = 0
                if absence_type in self.absence_rules:
                    rule = self.absence_rules[absence_type]
                    if rule == "DEFAULT_HOURS":
                        hours = self.default_daily_hours
                    elif isinstance(rule, (int, float)):
                        hours = rule
                else:
                    hours = self.default_daily_hours
                
                filled_hours.append({
                    'user_email': user_email,
                    'date': target_date,
                    'hours': hours,
                    'absence_type': absence_type,
                    'absence_id': absence.timetastic_id,
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
