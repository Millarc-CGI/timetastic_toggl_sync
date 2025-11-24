"""
Simple overtime calculator - calculates overtime based on default 8 hours per day.
More complex rules will be added later.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, date, timedelta
from collections import defaultdict

from ..config import Settings
from ..models.user import User


class OvertimeCalculator:
    """Simple overtime calculator - 8 hours per day default."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.default_daily_hours = settings.default_daily_hours
    
    def get_user_rules(self, user_email: str) -> Dict[str, Any]:
        """Get overtime rules for a specific user - simplified for now."""
        return {
            'daily_threshold': self.default_daily_hours,
            'weekly_threshold': self.settings.default_weekly_hours,
            'monthly_threshold': self.settings.default_monthly_hours,
            'overtime_multiplier': 1.5
        }
    
    def calculate_daily_overtime(
        self,
        user_email: str,
        target_date: date,
        total_hours: float
    ) -> float:
        """Calculate overtime for a single day - simple 8 hour threshold."""
        return max(0.0, total_hours - self.default_daily_hours)
    
    def calculate_weekly_overtime(
        self,
        user_email: str,
        week_start: date,
        daily_hours: List[float]
    ) -> float:
        """Calculate overtime for a week - simple 40 hour threshold."""
        total_weekly_hours = sum(daily_hours)
        threshold = self.settings.default_weekly_hours
        return total_weekly_hours - threshold
    
    def calculate_monthly_overtime(
        self,
        user_email: str,
        year: int,
        month: int,
        daily_hours: List[float]
    ) -> float:
        """Calculate overtime for a month - simple 160 hour threshold."""
        total_monthly_hours = sum(daily_hours)
        return total_monthly_hours - self.settings.default_monthly_hours
    
    def calculate_user_overtime(
        self,
        user_email: str,
        year: int,
        month: int,
        daily_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Calculate all types of overtime for a user for a month."""

        rules = self.get_user_rules(user_email)
        daily_overtime_total = 0.0
        weekly_overtime = 0.0
        monthly_total_hours = 0.0
        monthly_expected_hours = 0.0
        week_hours_map = defaultdict(float)
        week_expected_map = defaultdict(float)
        weekend_overtime = 0.0
        weekend_breakdown = {}
        daily_breakdown = []

        for day_data in daily_data:
            date_obj = day_data['date']
            total_hours = day_data.get('total_hours', 0.0)
            if day_data.get('is_weekend'):
                weekend_hours = day_data.get('time_entry_hours', 0.0)
                weekend_overtime += weekend_hours
                weekend_breakdown[date_obj] = weekend_hours
                daily_breakdown.append({
                    'date': date_obj,
                    'type': 'weekend',
                    'hours': weekend_hours
                })
                month_expected_increment = 0.0
            else:
                overtime = self.calculate_daily_overtime(user_email, date_obj, total_hours)
                daily_overtime_total += overtime
                daily_breakdown.append({
                    'date': date_obj,
                    'type': 'weekday',
                    'hours': overtime
                })
                month_expected_increment = self.default_daily_hours

            week_start = date_obj - timedelta(days=date_obj.weekday())
            week_hours_map[week_start] += total_hours
            week_expected_map[week_start] += month_expected_increment
            monthly_total_hours += total_hours
            monthly_expected_hours += month_expected_increment

        weekly_breakdown_map: Dict[date, Dict[str, float]] = {}
        for week_start, worked_hours in week_hours_map.items():
            expected_hours = week_expected_map.get(week_start, 0.0)
            overtime_delta = worked_hours - expected_hours
            weekly_overtime += overtime_delta
            weekly_breakdown_map[week_start] = {
                'total_hours': worked_hours,
                'expected_hours': expected_hours,
                'overtime': overtime_delta
            }

        monthly_overtime = monthly_total_hours - monthly_expected_hours
        overtime_multiplier = 1.5

        return {
            'user_email': user_email,
            'year': year,
            'month': month,
            'daily_overtime': daily_overtime_total,
            'weekly_overtime': weekly_overtime,
            'monthly_total_hours': monthly_total_hours,
            'monthly_expected_hours': monthly_expected_hours,
            'monthly_overtime': monthly_overtime,
            'weekend_overtime': weekend_overtime,
            'overtime_multiplier': overtime_multiplier,
            'rules_used': rules,
            'daily_breakdown': daily_breakdown,
            'weekly_breakdown': weekly_breakdown_map,
            'weekend_breakdown': weekend_breakdown
        }

    def get_overtime_summary(
        self,
        users: List[User],
        user_overtime_data: Dict[str, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Get summary of overtime across all users."""
        
        total_overtime_all = 0
        users_with_overtime = 0
        total_daily_overtime = 0
        total_weekly_overtime = 0
        total_monthly_overtime = 0
        total_weekend_overtime = 0

        overtime_by_department = defaultdict(float)
        overtime_by_user = []

        for user in users:
            user_email = user.email.lower()
            overtime_data = user_overtime_data.get(user_email, {})

            if overtime_data:
                total_overtime = overtime_data.get('total_overtime', 0)
                total_overtime_all += total_overtime

                if total_overtime > 0:
                    users_with_overtime += 1
                    overtime_by_user.append({
                        'user_email': user_email,
                        'user_name': user.display_name,
                        'department': user.department or 'Unknown',
                        'total_overtime': total_overtime,
                        'daily_overtime': overtime_data.get('daily_overtime', 0),
                        'weekly_overtime': overtime_data.get('weekly_overtime', 0),
                        'monthly_overtime': overtime_data.get('monthly_overtime', 0),
                        'weekend_overtime': overtime_data.get('weekend_overtime', 0)
                    })

                total_daily_overtime += overtime_data.get('daily_overtime', 0)
                total_weekly_overtime += overtime_data.get('weekly_overtime', 0)
                total_monthly_overtime += overtime_data.get('monthly_overtime', 0)
                total_weekend_overtime += overtime_data.get('weekend_overtime', 0)

                # Group by department
                department = user.department or 'Unknown'
                overtime_by_department[department] += total_overtime

        # Sort users by overtime (highest first)
        overtime_by_user.sort(key=lambda x: x['total_overtime'], reverse=True)

        return {
            'total_users': len(users),
            'users_with_overtime': users_with_overtime,
            'total_overtime_all': total_overtime_all,
            'average_overtime_per_user': total_overtime_all / len(users) if users else 0,
            'average_overtime_with_overtime': total_overtime_all / users_with_overtime if users_with_overtime > 0 else 0,
            'total_daily_overtime': total_daily_overtime,
            'total_weekly_overtime': total_weekly_overtime,
            'total_monthly_overtime': total_monthly_overtime,
            'total_weekend_overtime': total_weekend_overtime,
            'overtime_by_department': dict(overtime_by_department),
            'top_overtime_users': overtime_by_user[:10]  # Top 10
        }

    def validate_overtime_rules(self) -> List[str]:
        """Validate simple overtime rules configuration."""
        issues = []
        
        # Check basic settings
        if self.default_daily_hours <= 0:
            issues.append("Daily hours must be greater than 0")
        
        if self.settings.default_weekly_hours <= 0:
            issues.append("Weekly hours must be greater than 0")
        
        if self.settings.default_monthly_hours <= 0:
            issues.append("Monthly hours must be greater than 0")
        
        return issues
    
    def suggest_overtime_rules(
        self,
        users: List[User],
        historical_data: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, Dict[str, Any]]:
        """Suggest overtime rules based on historical data - simplified."""
        
        suggestions = {}
        
        for user in users:
            user_email = user.email.lower()
            user_data = historical_data.get(user_email, [])
            
            if not user_data:
                continue
            
            # Simple statistics
            daily_hours = [day['total_hours'] for day in user_data]
            
            suggestions[user_email] = {
                'current_rules': self.get_user_rules(user_email),
                'suggested_daily_threshold': self.default_daily_hours,  # Keep it simple
                'suggested_weekly_threshold': self.settings.default_weekly_hours,
                'suggested_monthly_threshold': self.settings.default_monthly_hours,
                'statistics': {
                    'daily_avg': sum(daily_hours) / len(daily_hours) if daily_hours else 0,
                    'daily_max': max(daily_hours) if daily_hours else 0,
                    'data_points': len(user_data)
                }
            }
        
        return suggestions
    
    def calculate_overtime_cost(
        self,
        user_email: str,
        overtime_data: Dict[str, Any],
        hourly_rate: Optional[float] = None
    ) -> Dict[str, float]:
        """Calculate overtime cost for a user."""
        
        # Simple overtime multiplier
        overtime_multiplier = 1.5
        total_overtime = overtime_data.get('total_overtime', 0)
        
        if hourly_rate is None:
            # Default hourly rate (should be configurable)
            hourly_rate = 25.0
        
        regular_overtime_cost = total_overtime * hourly_rate
        overtime_cost = regular_overtime_cost * overtime_multiplier
        additional_cost = overtime_cost - regular_overtime_cost
        
        return {
            'hourly_rate': hourly_rate,
            'overtime_multiplier': overtime_multiplier,
            'total_overtime_hours': total_overtime,
            'regular_cost': regular_overtime_cost,
            'overtime_cost': overtime_cost,
            'additional_cost': additional_cost
        }
