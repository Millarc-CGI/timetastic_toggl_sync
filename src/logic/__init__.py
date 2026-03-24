"""
Business logic module for the Timetastic-Toggl sync system.

This module contains the core business logic for data aggregation,
overtime calculations, statistics generation, and report creation.
"""

from .data_aggregator import DataAggregator
from .overtime_calculator import OvertimeCalculator
from .statistics_generator import StatisticsGenerator
from .report_generator import ReportGenerator
from .kpi_calculator import (
    HOURS_SHARE_PCT,
    KPI_LEGEND_LINES,
    OVERTIME_SHARE_PCT,
    aggregate_by_user,
    compute_team_totals,
    enrich_project_stat_rows,
)
from .date_ranges import (
    last_week_range,
    last_month_range,
    current_week_range,
    current_month_to_date_range,
)

__all__ = [
    'DataAggregator',
    'OvertimeCalculator',
    'StatisticsGenerator',
    'ReportGenerator',
    'HOURS_SHARE_PCT',
    'KPI_LEGEND_LINES',
    'OVERTIME_SHARE_PCT',
    'aggregate_by_user',
    'compute_team_totals',
    'enrich_project_stat_rows',
    'last_week_range',
    'last_month_range',
    'current_week_range',
    'current_month_to_date_range',
]
