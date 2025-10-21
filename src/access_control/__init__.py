"""
Access control module for the Timetastic-Toggl sync system.

This module handles role-based access control and permissions.
"""

from .permissions import PermissionManager

__all__ = [
    'PermissionManager'
]
