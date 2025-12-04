"""
SQLite storage for caching data and managing user mappings.
"""

import sqlite3
import json
import os
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date, timedelta
from pathlib import Path

from ..config import Settings
from ..models.user import User
from ..models.time_entry import TimeEntry
from ..models.absence import Absence


class SQLiteStorage:
    """SQLite database storage for the sync system."""
    
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db_path = settings.database_path
        
        # Ensure database directory exists
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
        
        self._init_database()
    
    def _init_database(self):
        """Initialize database tables."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # Users table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    email TEXT PRIMARY KEY,
                    toggl_user_id INTEGER,
                    timetastic_user_id INTEGER,
                    slack_user_id TEXT,
                    full_name TEXT,
                    department TEXT,
                    -- overtime_rules removed, will be implemented in overtime_calculator.py
                    is_admin BOOLEAN DEFAULT 0,
                    is_producer BOOLEAN DEFAULT 0,
                    created_at TEXT,
                    updated_at TEXT,
                    last_sync_at TEXT
                )
            """)
            
            # Time entries table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS time_entries (
                    toggl_id INTEGER PRIMARY KEY,
                    description TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    duration_seconds INTEGER,
                    project_id INTEGER,
                    project_name TEXT,
                    task_id INTEGER,
                    task_name TEXT,
                    user_id INTEGER,
                    user_email TEXT,
                    tags TEXT,
                    billable BOOLEAN DEFAULT 0,
                    workspace_id INTEGER,
                    created_at TEXT,
                    updated_at TEXT,
                    cached_at TEXT
                )
            """)
            
            # Absences table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS absences (
                    timetastic_id INTEGER PRIMARY KEY,
                    absence_type TEXT,
                    start_date TEXT,
                    end_date TEXT,
                    status TEXT,
                    user_id INTEGER,
                    user_email TEXT,
                    user_name TEXT,
                    notes TEXT,
                    department TEXT,
                    created_at TEXT,
                    updated_at TEXT,
                    cached_at TEXT
                )
            """)
            
            # Sync log table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sync_type TEXT,
                    start_time TEXT,
                    end_time TEXT,
                    status TEXT,
                    entries_processed INTEGER DEFAULT 0,
                    errors TEXT,
                    created_at TEXT
                )
            """)
            
            # Monthly reports table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS monthly_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_email TEXT,
                    year INTEGER,
                    month INTEGER,
                    report_type TEXT,
                    report_data TEXT,
                    generated_at TEXT,
                    file_path TEXT,
                    created_at TEXT
                )
            """)
            
            # Cache metadata table - tracks cache freshness and dirty ranges
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cache_metadata (
                    workspace_id INTEGER,
                    year INTEGER,
                    month INTEGER,
                    last_full_fetch TEXT,
                    last_updated_at TEXT,
                    data_hash TEXT,
                    dirty_ranges TEXT,
                    PRIMARY KEY (workspace_id, year, month)
                )
            """)
            
            # Refresh queue table - manages API refresh requests
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS refresh_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workspace_id INTEGER,
                    start_date TEXT,
                    end_date TEXT,
                    priority INTEGER DEFAULT 5,
                    status TEXT DEFAULT 'pending',
                    scheduled_at TEXT,
                    started_at TEXT,
                    completed_at TEXT,
                    retries INTEGER DEFAULT 0,
                    last_error TEXT
                )
            """)
            
            # Monthly statistics table - processed monthly aggregation results
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS monthly_statistics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_email TEXT,
                    year INTEGER,
                    month INTEGER,
                    total_hours REAL,
                    absence_hours REAL,
                    working_days INTEGER,
                    project_hours TEXT,
                    absence_breakdown TEXT,
                    missing_days TEXT,
                    generated_at TEXT,
                    created_at TEXT,
                    UNIQUE(user_email, year, month)
                )
            """)
            
            # Daily statistics table - processed daily aggregation results
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS daily_statistics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_email TEXT,
                    date TEXT,
                    time_entry_hours REAL,
                    absence_hours REAL,
                    total_hours REAL,
                    absence_type TEXT,
                    absence_details TEXT,
                    project_hours TEXT,
                    is_weekend BOOLEAN DEFAULT 0,
                    is_holiday BOOLEAN DEFAULT 0,
                    monthly_statistics_id INTEGER,
                    created_at TEXT,
                    UNIQUE(user_email, date),
                    FOREIGN KEY (monthly_statistics_id) REFERENCES monthly_statistics(id)
                )
            """)
            
            # Overtime data table - processed overtime calculation results
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS overtime_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_email TEXT,
                    year INTEGER,
                    month INTEGER,
                    monthly_overtime REAL,
                    normal_overtime REAL,
                    weekend_overtime REAL,
                    monthly_total_hours REAL,
                    monthly_expected_hours REAL,
                    daily_breakdown TEXT,
                    weekly_breakdown TEXT,
                    weekend_breakdown TEXT,
                    monthly_statistics_id INTEGER,
                    generated_at TEXT,
                    created_at TEXT,
                    UNIQUE(user_email, year, month),
                    FOREIGN KEY (monthly_statistics_id) REFERENCES monthly_statistics(id)
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_time_entries_user_email ON time_entries(user_email)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_time_entries_start_time ON time_entries(start_time)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_absences_user_email ON absences(user_email)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_absences_start_date ON absences(start_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_monthly_reports_user_period ON monthly_reports(user_email, year, month)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_monthly_stats_user_period ON monthly_statistics(user_email, year, month)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_stats_user_date ON daily_statistics(user_email, date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_stats_monthly_id ON daily_statistics(monthly_statistics_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_overtime_user_period ON overtime_data(user_email, year, month)")
            
            conn.commit()
    
    # User management methods
    def save_user(self, user: User) -> bool:
        """Save or update user."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT OR REPLACE INTO users 
                    (email, toggl_user_id, timetastic_user_id, slack_user_id, full_name, 
                     department, is_admin, is_producer, created_at, updated_at, last_sync_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user.email,
                    user.toggl_user_id,
                    user.timetastic_user_id,
                    user.slack_user_id,
                    user.full_name,
                    user.department,
                    user.is_admin,
                    user.is_producer,
                    user.created_at.isoformat() if user.created_at else None,
                    user.updated_at.isoformat() if user.updated_at else None,
                    user.last_sync_at.isoformat() if user.last_sync_at else None
                ))
                
                conn.commit()
                return True
        except Exception as e:
            print(f"Error saving user {user.email}: {e}")
            return False
    
    def get_user(self, email: str) -> Optional[User]:
        """Get user by email."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("SELECT * FROM users WHERE email = ?", (email.lower(),))
                row = cursor.fetchone()
                
                if row:
                    return self._row_to_user(row)
                return None
        except Exception as e:
            print(f"Error getting user {email}: {e}")
            return None
    
    def get_all_users(self) -> List[User]:
        """Get all users."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("SELECT * FROM users ORDER BY email")
                rows = cursor.fetchall()
                
                return [self._row_to_user(row) for row in rows]
        except Exception as e:
            print(f"Error getting all users: {e}")
            return []
    
    def _row_to_user(self, row: Tuple) -> User:
        """Convert database row to User object."""
        created_at = None
        updated_at = None
        last_sync_at = None
        
        if row[8]:  # created_at (shifted due to removed overtime_rules column)
            try:
                created_at = datetime.fromisoformat(row[8])
            except ValueError:
                pass
        
        if row[9]:  # updated_at
            try:
                updated_at = datetime.fromisoformat(row[9])
            except ValueError:
                pass
        
        if row[10]:  # last_sync_at
            try:
                last_sync_at = datetime.fromisoformat(row[10])
            except ValueError:
                pass
        
        return User(
            email=row[0],
            toggl_user_id=row[1],
            timetastic_user_id=row[2],
            slack_user_id=row[3],
            full_name=row[4] or '',
            department=row[5],
            # overtime_rules removed
            is_admin=bool(row[6]),
            is_producer=bool(row[7]),
            created_at=created_at,
            updated_at=updated_at,
            last_sync_at=last_sync_at
        )
    
    # Time entries methods
    def save_time_entries(self, entries: List[TimeEntry]) -> bool:
        """Save time entries to database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                email_cache: Dict[int, str] = {}
                
                for entry in entries:
                    email = (entry.user_email or "").strip().lower()
                    if not email and entry.user_id:
                        # Look up email via toggl_user_id if missing from payload
                        if entry.user_id in email_cache:
                            email = email_cache[entry.user_id]
                        else:
                            cursor.execute(
                                "SELECT email FROM users WHERE toggl_user_id = ? LIMIT 1",
                                (entry.user_id,),
                            )
                            row = cursor.fetchone()
                            if row and row[0]:
                                email = (row[0] or "").strip().lower()
                                email_cache[entry.user_id] = email
                    entry.user_email = email or None

                    cursor.execute("""
                        INSERT OR REPLACE INTO time_entries 
                        (toggl_id, description, start_time, end_time, duration_seconds,
                         project_id, project_name, task_id, task_name, user_id, user_email,
                         tags, billable, workspace_id, created_at, updated_at, cached_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        entry.toggl_id,
                        entry.description,
                        entry.start_time.isoformat(),
                        entry.end_time.isoformat() if entry.end_time else None,
                        entry.duration_seconds,
                        entry.project_id,
                        entry.project_name,
                        entry.task_id,
                        entry.task_name,
                        entry.user_id,
                        entry.user_email,
                        json.dumps(entry.tags or []),
                        entry.billable,
                        entry.workspace_id,
                        entry.created_at.isoformat() if entry.created_at else None,
                        entry.updated_at.isoformat() if entry.updated_at else None,
                        datetime.now().isoformat()
                    ))
                
                conn.commit()
                return True
        except Exception as e:
            print(f"Error saving time entries: {e}")
            return False
    
    def get_time_entries_for_user(
        self, 
        user_email: str, 
        start_date: Optional[date] = None, 
        end_date: Optional[date] = None
    ) -> List[TimeEntry]:
        """Get time entries for user within date range."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                query = "SELECT * FROM time_entries WHERE user_email = ?"
                params = [user_email.lower()]
                
                if start_date:
                    query += " AND start_time >= ?"
                    params.append(start_date.isoformat())
                
                if end_date:
                    query += " AND start_time <= ?"
                    params.append(end_date.isoformat())
                
                query += " ORDER BY start_time"
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                return [self._row_to_time_entry(row) for row in rows]
        except Exception as e:
            print(f"Error getting time entries for {user_email}: {e}")
            return []
    
    def get_time_entries_for_period(
        self, 
        start_date: date, 
        end_date: date
    ) -> List[TimeEntry]:
        """Get all time entries within date range."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM time_entries 
                    WHERE start_time >= ? AND start_time <= ?
                    ORDER BY start_time
                """, (start_date.isoformat(), end_date.isoformat()))
                
                rows = cursor.fetchall()
                return [self._row_to_time_entry(row) for row in rows]
        except Exception as e:
            print(f"Error getting time entries for period: {e}")
            return []
    
    def _row_to_time_entry(self, row: Tuple) -> TimeEntry:
        """Convert database row to TimeEntry object."""
        start_time = None
        end_time = None
        created_at = None
        updated_at = None
        
        if row[2]:  # start_time
            try:
                start_time = datetime.fromisoformat(row[2])
            except ValueError:
                pass
        
        if row[3]:  # end_time
            try:
                end_time = datetime.fromisoformat(row[3])
            except ValueError:
                pass
        
        if row[15]:  # created_at
            try:
                created_at = datetime.fromisoformat(row[15])
            except ValueError:
                pass
        
        if row[16]:  # updated_at
            try:
                updated_at = datetime.fromisoformat(row[16])
            except ValueError:
                pass
        
        tags = []
        if row[11]:  # tags
            try:
                tags = json.loads(row[11])
            except json.JSONDecodeError:
                pass
        
        return TimeEntry(
            toggl_id=row[0],
            description=row[1] or '',
            start_time=start_time or datetime.now(),
            end_time=end_time,
            duration_seconds=row[4] or 0,
            project_id=row[5],
            project_name=row[6],
            task_id=row[7],
            task_name=row[8],
            user_id=row[9],
            user_email=row[10],
            tags=tags,
            billable=bool(row[12]),
            workspace_id=row[13],
            created_at=created_at,
            updated_at=updated_at
        )
    
    # Absences methods
    def save_absences(self, absences: List[Absence]) -> bool:
        """Save absences to database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                email_cache: Dict[int, str] = {}
                
                # Separate public holidays from regular absences
                public_holidays = []
                regular_absences = []
                
                for absence in absences:
                    # Check if this is a public holiday (no user_email, holiday type, notes start with "Public holiday:")
                    is_public_holiday = (
                        not absence.user_email and 
                        absence.absence_type == "holiday" and 
                        absence.status == "Holiday" and
                        (absence.notes or "").strip().startswith("Public holiday:")
                    )
                    
                    if is_public_holiday:
                        public_holidays.append(absence)
                    else:
                        regular_absences.append(absence)
                
                # Get all users to assign public holidays to
                cursor.execute("SELECT email, timetastic_user_id FROM users")
                all_users = cursor.fetchall()
                user_email_map = {user_id: email.lower() for email, user_id in all_users if user_id}
                
                print(f"   [DEBUG] Save Public Holidays: Found {len(public_holidays)} public holidays, assigning to {len(user_email_map)} users")
                
                # Save regular absences
                for absence in regular_absences:
                    email = (absence.user_email or "").strip().lower()
                    if not email and absence.user_id:
                        # Look up email via timetastic_user_id if missing from payload
                        if absence.user_id in email_cache:
                            email = email_cache[absence.user_id]
                        else:
                            cursor.execute(
                                "SELECT email FROM users WHERE timetastic_user_id = ? LIMIT 1",
                                (absence.user_id,),
                            )
                            row = cursor.fetchone()
                            if row and row[0]:
                                email = (row[0] or "").strip().lower()
                                email_cache[absence.user_id] = email
                    absence.user_email = email or None

                    cursor.execute("""
                        INSERT OR REPLACE INTO absences 
                        (timetastic_id, absence_type, start_date, end_date, status,
                        user_id, user_email, user_name, notes, department,
                        created_at, updated_at, cached_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        absence.timetastic_id,
                        absence.absence_type,
                        absence.start_date.isoformat(),
                        absence.end_date.isoformat(),
                        absence.status,
                        absence.user_id,
                        absence.user_email,
                        absence.user_name,
                        absence.notes,
                        absence.department,
                        absence.created_at.isoformat() if absence.created_at else None,
                        absence.updated_at.isoformat() if absence.updated_at else None,
                        datetime.now().isoformat()
                    ))
                
                # Save public holidays for each user
                for ph in public_holidays:
                    for user_id, user_email in user_email_map.items():
                        # Create unique timetastic_id for each user's public holiday
                        # Use negative ID to avoid conflicts with regular timetastic_ids
                        unique_id = -(ph.timetastic_id * 1000000 + user_id)
                        
                        cursor.execute("""
                            INSERT OR REPLACE INTO absences 
                            (timetastic_id, absence_type, start_date, end_date, status,
                            user_id, user_email, user_name, notes, department,
                            created_at, updated_at, cached_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            unique_id,
                            ph.absence_type,
                            ph.start_date.isoformat(),
                            ph.end_date.isoformat(),
                            ph.status,
                            user_id,
                            user_email,
                            None,
                            ph.notes,
                            None,
                            ph.created_at.isoformat() if ph.created_at else None,
                            ph.updated_at.isoformat() if ph.updated_at else None,
                            datetime.now().isoformat()
                        ))
                
                conn.commit()
                return True
        except Exception as e:
            print(f"Error saving absences: {e}")
            return False
    
    def get_absences_for_user(
        self, 
        user_email: str, 
        start_date: Optional[date] = None, 
        end_date: Optional[date] = None
    ) -> List[Absence]:
        """Get absences for user within date range, including public holidays (which are now assigned to users)."""
        print(f"   [DEBUG Storage.get_absences_for_user] Called for user_email={user_email}, start_date={start_date}, end_date={end_date}")
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Get all absences for this user (including public holidays which are now assigned to users)
                query = "SELECT * FROM absences WHERE user_email = ?"
                params = [user_email.lower()]
                
                if start_date:
                    query += " AND start_date >= ?"
                    params.append(start_date.isoformat())
                
                if end_date:
                    query += " AND end_date <= ?"
                    params.append(end_date.isoformat())
                
                query += " ORDER BY start_date"
                
                print(f"   [DEBUG Storage.get_absences_for_user] Executing query: {query} with params: {params}")
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                print(f"   [DEBUG Storage.get_absences_for_user] Found {len(rows)} rows from database")
                
                absences = [self._row_to_absence(row) for row in rows]
                
                # Count public holidays
                public_holidays_count = sum(1 for abs in absences if (abs.notes or "").strip().startswith("Public holiday:"))
                regular_count = len(absences) - public_holidays_count
                
                print(f"   [DEBUG Storage.get_absences_for_user] Parsed {len(absences)} absences ({regular_count} regular + {public_holidays_count} public holidays)")
                
                if absences:
                    print(f"   [DEBUG Storage.get_absences_for_user] Sample absences (first 5):")
                    for abs in absences[:5]:
                        print(f"      {abs.start_date} to {abs.end_date} | type={abs.absence_type} | status={abs.status} | user_email={abs.user_email} | notes={abs.notes[:50] if abs.notes else None}")
                else:
                    print(f"   [DEBUG Storage.get_absences_for_user] ⚠️ No absences found in SQLite for {user_email}")
                
                return absences
        except Exception as e:
            print(f"Error getting absences for {user_email}: {e}")
            return []
    
    # Processed statistics methods - save
    def save_monthly_statistics(
        self,
        user_email: str,
        year: int,
        month: int,
        monthly_data: Dict[str, Any]
    ) -> Optional[int]:
        """Save monthly statistics to database. Returns monthly_statistics_id."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                
                # Prepare JSON fields
                project_hours_json = json.dumps(monthly_data.get('project_hours', {}))
                absence_breakdown_json = json.dumps(monthly_data.get('absence_breakdown', {}))
                missing_days_json = json.dumps([d.isoformat() if isinstance(d, date) else d for d in monthly_data.get('missing_days', [])])
                
                cursor.execute("""
                    INSERT OR REPLACE INTO monthly_statistics
                    (user_email, year, month, total_hours, absence_hours, working_days,
                     project_hours, absence_breakdown, missing_days, generated_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_email.lower(),
                    year,
                    month,
                    monthly_data.get('total_hours', 0.0),
                    monthly_data.get('absence_hours', 0.0),
                    monthly_data.get('working_days', 0),
                    project_hours_json,
                    absence_breakdown_json,
                    missing_days_json,
                    now,
                    now
                ))
                
                # Get the ID of the inserted/updated row
                cursor.execute("""
                    SELECT id FROM monthly_statistics
                    WHERE user_email = ? AND year = ? AND month = ?
                """, (user_email.lower(), year, month))
                row = cursor.fetchone()
                monthly_statistics_id = row[0] if row else None
                
                conn.commit()
                return monthly_statistics_id
        except Exception as e:
            print(f"Error saving monthly statistics for {user_email} ({year}-{month:02d}): {e}")
            return None
    
    def save_daily_statistics(
        self,
        user_email: str,
        year: int,
        month: int,
        daily_data: List[Dict[str, Any]],
        monthly_statistics_id: Optional[int]
    ) -> bool:
        """Save daily statistics to database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                
                # Delete existing daily statistics for this user/month
                cursor.execute("""
                    DELETE FROM daily_statistics
                    WHERE user_email = ? AND date >= ? AND date <= ?
                """, (
                    user_email.lower(),
                    date(year, month, 1).isoformat(),
                    (date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year + 1, 1, 1) - timedelta(days=1)).isoformat()
                ))
                
                # Batch insert all days
                for day in daily_data:
                    date_obj = day.get('date')
                    if isinstance(date_obj, str):
                        date_str = date_obj
                    elif isinstance(date_obj, date):
                        date_str = date_obj.isoformat()
                    else:
                        continue
                    
                    # Map is_public_holiday to is_holiday (where public holidays are also holidays)
                    is_holiday = day.get('is_public_holiday', False) or day.get('is_holiday', False)
                    
                    absence_details_json = json.dumps(day.get('absence_details', []))
                    project_hours_json = json.dumps(day.get('project_hours', {}))
                    
                    cursor.execute("""
                        INSERT INTO daily_statistics
                        (user_email, date, time_entry_hours, absence_hours, total_hours,
                         absence_type, absence_details, project_hours, is_weekend, is_holiday,
                         monthly_statistics_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_email.lower(),
                        date_str,
                        day.get('time_entry_hours', 0.0),
                        day.get('absence_hours', 0.0),
                        day.get('total_hours', 0.0),
                        day.get('absence_type'),
                        absence_details_json,
                        project_hours_json,
                        1 if day.get('is_weekend', False) else 0,
                        1 if is_holiday else 0,
                        monthly_statistics_id,
                        now
                    ))
                
                conn.commit()
                return True
        except Exception as e:
            print(f"Error saving daily statistics for {user_email} ({year}-{month:02d}): {e}")
            return False
    
    def save_overtime_data(
        self,
        user_email: str,
        year: int,
        month: int,
        overtime_data: Dict[str, Any],
        monthly_statistics_id: Optional[int]
    ) -> bool:
        """Save overtime data to database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                
                # Map daily_overtime to normal_overtime (weekday)
                normal_overtime = overtime_data.get('daily_overtime', 0.0)
                weekend_overtime = overtime_data.get('weekend_overtime', 0.0)
                
                # Prepare JSON fields
                daily_breakdown_json = json.dumps(overtime_data.get('daily_breakdown', []), default=str)
                weekly_breakdown_json = json.dumps(
                    {str(k): v for k, v in overtime_data.get('weekly_breakdown', {}).items()},
                    default=str
                )
                weekend_breakdown_json = json.dumps(
                    {str(k): v for k, v in overtime_data.get('weekend_breakdown', {}).items()},
                    default=str
                )
                
                cursor.execute("""
                    INSERT OR REPLACE INTO overtime_data
                    (user_email, year, month, monthly_overtime, normal_overtime, weekend_overtime,
                     monthly_total_hours, monthly_expected_hours, daily_breakdown, weekly_breakdown,
                     weekend_breakdown, monthly_statistics_id, generated_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_email.lower(),
                    year,
                    month,
                    overtime_data.get('monthly_overtime', 0.0),
                    normal_overtime,
                    weekend_overtime,
                    overtime_data.get('monthly_total_hours', 0.0),
                    overtime_data.get('monthly_expected_hours', 0.0),
                    daily_breakdown_json,
                    weekly_breakdown_json,
                    weekend_breakdown_json,
                    monthly_statistics_id,
                    now,
                    now
                ))
                
                conn.commit()
                return True
        except Exception as e:
            print(f"Error saving overtime data for {user_email} ({year}-{month:02d}): {e}")
            return False
    
    def save_user_monthly_processed_data(
        self,
        user_email: str,
        year: int,
        month: int,
        monthly_data: Dict[str, Any],
        overtime_data: Dict[str, Any]
    ) -> bool:
        """
        Save all processed data for a user/month: monthly statistics, daily statistics, and overtime data.
        This is a new unified method that saves data from data_aggregator and overtime_calculator.
        """
        try:
            # First save monthly statistics to get the ID
            monthly_statistics_id = self.save_monthly_statistics(user_email, year, month, monthly_data)
            
            if not monthly_statistics_id:
                print(f"   [DEBUG SQLite] Failed to save monthly statistics for {user_email} ({year}-{month:02d})")
                return False
            
            # Save daily statistics
            daily_data = monthly_data.get('daily_data', [])
            if daily_data:
                daily_saved = self.save_daily_statistics(user_email, year, month, daily_data, monthly_statistics_id)
                if not daily_saved:
                    print(f"   [DEBUG SQLite] Failed to save daily statistics for {user_email} ({year}-{month:02d})")
            
            # Save overtime data
            overtime_saved = self.save_overtime_data(user_email, year, month, overtime_data, monthly_statistics_id)
            if not overtime_saved:
                print(f"   [DEBUG SQLite] Failed to save overtime data for {user_email} ({year}-{month:02d})")
            
            return True
            
        except Exception as e:
            print(f"Error saving processed data for {user_email} ({year}-{month:02d}): {e}")
            return False
    
    # Processed statistics methods - read
    def get_monthly_statistics(
        self,
        user_email: str,
        year: int,
        month: int
    ) -> Optional[Dict[str, Any]]:
        """Get monthly statistics from database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT total_hours, absence_hours, working_days, project_hours,
                           absence_breakdown, missing_days, generated_at
                    FROM monthly_statistics
                    WHERE user_email = ? AND year = ? AND month = ?
                """, (user_email.lower(), year, month))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                # Deserialize JSON fields
                project_hours = {}
                absence_breakdown = {}
                missing_days = []
                
                if row[3]:  # project_hours
                    try:
                        project_hours = json.loads(row[3])
                    except json.JSONDecodeError:
                        pass
                
                if row[4]:  # absence_breakdown
                    try:
                        absence_breakdown = json.loads(row[4])
                    except json.JSONDecodeError:
                        pass
                
                if row[5]:  # missing_days
                    try:
                        missing_days_raw = json.loads(row[5])
                        missing_days = [datetime.fromisoformat(d).date() if isinstance(d, str) else d for d in missing_days_raw]
                    except (json.JSONDecodeError, ValueError):
                        pass
                
                return {
                    'total_hours': row[0],
                    'absence_hours': row[1],
                    'working_days': row[2],
                    'project_hours': project_hours,
                    'absence_breakdown': absence_breakdown,
                    'missing_days': missing_days,
                    'generated_at': row[6]
                }
        except Exception as e:
            print(f"Error getting monthly statistics for {user_email} ({year}-{month:02d}): {e}")
            return None
    
    def get_daily_statistics(
        self,
        user_email: str,
        year: int,
        month: int
    ) -> List[Dict[str, Any]]:
        """Get daily statistics from database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                start_date = date(year, month, 1).isoformat()
                end_date = (date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year + 1, 1, 1) - timedelta(days=1)).isoformat()
                
                cursor.execute("""
                    SELECT date, time_entry_hours, absence_hours, total_hours,
                           absence_type, absence_details, project_hours, is_weekend, is_holiday
                    FROM daily_statistics
                    WHERE user_email = ? AND date >= ? AND date <= ?
                    ORDER BY date
                """, (user_email.lower(), start_date, end_date))
                
                rows = cursor.fetchall()
                daily_data = []
                
                for row in rows:
                    # Deserialize JSON fields
                    absence_details = []
                    project_hours = {}
                    
                    if row[5]:  # absence_details
                        try:
                            absence_details = json.loads(row[5])
                        except json.JSONDecodeError:
                            pass
                    
                    if row[6]:  # project_hours
                        try:
                            project_hours = json.loads(row[6])
                        except json.JSONDecodeError:
                            pass
                    
                    # Map is_holiday back to is_public_holiday for compatibility
                    is_public_holiday = bool(row[8])  # is_holiday
                    
                    daily_data.append({
                        'date': datetime.fromisoformat(row[0]).date() if isinstance(row[0], str) else row[0],
                        'time_entry_hours': row[1],
                        'absence_hours': row[2],
                        'total_hours': row[3],
                        'absence_type': row[4],
                        'absence_details': absence_details,
                        'project_hours': project_hours,
                        'is_weekend': bool(row[7]),
                        'is_public_holiday': is_public_holiday,
                        'is_holiday': is_public_holiday  # Also include is_holiday for consistency
                    })
                
                return daily_data
        except Exception as e:
            print(f"Error getting daily statistics for {user_email} ({year}-{month:02d}): {e}")
            return []
    
    def get_overtime_data(
        self,
        user_email: str,
        year: int,
        month: int
    ) -> Optional[Dict[str, Any]]:
        """Get overtime data from database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT monthly_overtime, normal_overtime, weekend_overtime,
                           monthly_total_hours, monthly_expected_hours,
                           daily_breakdown, weekly_breakdown, weekend_breakdown, generated_at
                    FROM overtime_data
                    WHERE user_email = ? AND year = ? AND month = ?
                """, (user_email.lower(), year, month))
                
                row = cursor.fetchone()
                if not row:
                    return None
                
                # Deserialize JSON fields
                daily_breakdown = []
                weekly_breakdown = {}
                weekend_breakdown = {}
                
                if row[5]:  # daily_breakdown
                    try:
                        daily_breakdown = json.loads(row[5])
                        # Convert date strings back to date objects
                        for item in daily_breakdown:
                            if 'date' in item and isinstance(item['date'], str):
                                item['date'] = datetime.fromisoformat(item['date']).date()
                    except json.JSONDecodeError:
                        pass
                
                if row[6]:  # weekly_breakdown
                    try:
                        weekly_breakdown_raw = json.loads(row[6])
                        # Convert date string keys back to date objects
                        weekly_breakdown = {
                            datetime.fromisoformat(k).date() if isinstance(k, str) else k: v
                            for k, v in weekly_breakdown_raw.items()
                        }
                    except (json.JSONDecodeError, ValueError):
                        pass
                
                if row[7]:  # weekend_breakdown
                    try:
                        weekend_breakdown_raw = json.loads(row[7])
                        # Convert date string keys back to date objects
                        weekend_breakdown = {
                            datetime.fromisoformat(k).date() if isinstance(k, str) else k: v
                            for k, v in weekend_breakdown_raw.items()
                        }
                    except (json.JSONDecodeError, ValueError):
                        pass
                
                # Map normal_overtime back to daily_overtime for compatibility
                daily_overtime = row[1]  # normal_overtime
                
                return {
                    'monthly_overtime': row[0],
                    'daily_overtime': daily_overtime,  # mapped from normal_overtime
                    'weekend_overtime': row[2],
                    'monthly_total_hours': row[3],
                    'monthly_expected_hours': row[4],
                    'daily_breakdown': daily_breakdown,
                    'weekly_breakdown': weekly_breakdown,
                    'weekend_breakdown': weekend_breakdown,
                    'generated_at': row[8]
                }
        except Exception as e:
            print(f"Error getting overtime data for {user_email} ({year}-{month:02d}): {e}")
            return None
    
    def _row_to_absence(self, row: Tuple) -> Absence:
        """Convert database row to Absence object."""
        start_date = None
        end_date = None
        created_at = None
        updated_at = None
        
        if row[2]:  # start_date
            try:
                start_date = datetime.fromisoformat(row[2]).date()
            except ValueError:
                pass
        
        if row[3]:  # end_date
            try:
                end_date = datetime.fromisoformat(row[3]).date()
            except ValueError:
                pass
        
        if row[10]:  # created_at
            try:
                created_at = datetime.fromisoformat(row[10])
            except ValueError:
                pass
        
        if row[11]:  # updated_at
            try:
                updated_at = datetime.fromisoformat(row[11])
            except ValueError:
                pass
        
        return Absence(
            timetastic_id=row[0],
            absence_type=row[1] or 'Unknown',
            start_date=start_date or date.today(),
            end_date=end_date or date.today(),
            status=row[4] or 'Approved',
            user_id=row[5],
            user_email=row[6],
            user_name=row[7],
            notes=row[8],
            department=row[9],
            created_at=created_at,
            updated_at=updated_at
        )
    
    # Sync log methods
    def log_sync_start(self, sync_type: str) -> int:
        """Log sync start and return log ID."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    INSERT INTO sync_log (sync_type, start_time, status, created_at)
                    VALUES (?, ?, ?, ?)
                """, (sync_type, datetime.now().isoformat(), 'running', datetime.now().isoformat()))
                
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            print(f"Error logging sync start: {e}")
            return -1
    
    def log_sync_end(self, log_id: int, status: str, entries_processed: int = 0, errors: Optional[List[str]] = None):
        """Log sync completion."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                errors_json = json.dumps(errors or [])
                
                cursor.execute("""
                    UPDATE sync_log 
                    SET end_time = ?, status = ?, entries_processed = ?, errors = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), status, entries_processed, errors_json, log_id))
                
                conn.commit()
        except Exception as e:
            print(f"Error logging sync end: {e}")
    
    def get_sync_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent sync history."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT * FROM sync_log 
                    ORDER BY created_at DESC 
                    LIMIT ?
                """, (limit,))
                
                rows = cursor.fetchall()
                
                history = []
                for row in rows:
                    errors = []
                    if row[6]:  # errors column
                        try:
                            errors = json.loads(row[6])
                        except json.JSONDecodeError:
                            pass
                    
                    history.append({
                        'id': row[0],
                        'sync_type': row[1],
                        'start_time': row[2],
                        'end_time': row[3],
                        'status': row[4],
                        'entries_processed': row[5],
                        'errors': errors,
                        'created_at': row[7]
                    })
                
                return history
        except Exception as e:
            print(f"Error getting sync history: {e}")
            return []
    
    def cleanup_old_data(self, days_to_keep: int = 90):
        """Clean up old cached data."""
        try:
            cutoff_date = (datetime.now() - timedelta(days=days_to_keep)).isoformat()
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # Clean old time entries
                cursor.execute("DELETE FROM time_entries WHERE cached_at < ?", (cutoff_date,))
                time_entries_deleted = cursor.rowcount
                
                # Clean old absences
                cursor.execute("DELETE FROM absences WHERE cached_at < ?", (cutoff_date,))
                absences_deleted = cursor.rowcount
                
                # Clean old sync logs (keep more sync logs)
                sync_cutoff = (datetime.now() - timedelta(days=365)).isoformat()
                cursor.execute("DELETE FROM sync_log WHERE created_at < ?", (sync_cutoff,))
                sync_logs_deleted = cursor.rowcount
                
                conn.commit()
                
                print(f"Cleanup completed: {time_entries_deleted} time entries, {absences_deleted} absences, {sync_logs_deleted} sync logs deleted")
        except Exception as e:
            print(f"Error during cleanup: {e}")
    
    def get_database_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                stats = {}
                
                # Count records in each table
                cursor.execute("SELECT COUNT(*) FROM users")
                stats['users'] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM time_entries")
                stats['time_entries'] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM absences")
                stats['absences'] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM monthly_reports")
                stats['monthly_reports'] = cursor.fetchone()[0]
                
                cursor.execute("SELECT COUNT(*) FROM sync_log")
                stats['sync_logs'] = cursor.fetchone()[0]
                
                # Get database size
                stats['db_size_mb'] = os.path.getsize(self.db_path) / (1024 * 1024)
                
                return stats
        except Exception as e:
            print(f"Error getting database stats: {e}")
            return {}
    
    # Cache metadata methods
    def get_cache_metadata(self, workspace_id: int, year: int, month: int) -> Optional[Dict[str, Any]]:
        """Get cache metadata for a specific workspace/month."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT last_full_fetch, last_updated_at, data_hash, dirty_ranges
                    FROM cache_metadata
                    WHERE workspace_id = ? AND year = ? AND month = ?
                """, (workspace_id, year, month))
                row = cursor.fetchone()
                
                if row:
                    dirty_ranges = []
                    if row[3]:
                        try:
                            dirty_ranges = json.loads(row[3])
                        except json.JSONDecodeError:
                            pass
                    
                    return {
                        'last_full_fetch': row[0],
                        'last_updated_at': row[1],
                        'data_hash': row[2],
                        'dirty_ranges': dirty_ranges
                    }
                return None
        except Exception as e:
            print(f"Error getting cache metadata: {e}")
            return None
    
    def set_cache_metadata(
        self,
        workspace_id: int,
        year: int,
        month: int,
        data_hash: Optional[str] = None,
        dirty_ranges: Optional[List[Dict[str, str]]] = None,
        clear_dirty: bool = False
    ) -> bool:
        """Set or update cache metadata."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                now = datetime.now().isoformat()
                
                # Check if metadata exists
                cursor.execute("""
                    SELECT last_full_fetch, dirty_ranges FROM cache_metadata
                    WHERE workspace_id = ? AND year = ? AND month = ?
                """, (workspace_id, year, month))
                existing = cursor.fetchone()
                
                if existing:
                    # Update existing
                    current_dirty = []
                    if existing[1]:
                        try:
                            current_dirty = json.loads(existing[1])
                        except json.JSONDecodeError:
                            pass
                    
                    # Merge dirty ranges if provided
                    if dirty_ranges:
                        current_dirty.extend(dirty_ranges)
                        # Remove duplicates and merge overlapping ranges
                        current_dirty = self._merge_dirty_ranges(current_dirty)
                    
                    dirty_ranges_json = None if clear_dirty or not current_dirty else json.dumps(current_dirty)
                    
                    cursor.execute("""
                        UPDATE cache_metadata
                        SET last_full_fetch = ?,
                            last_updated_at = ?,
                            data_hash = COALESCE(?, data_hash),
                            dirty_ranges = ?
                        WHERE workspace_id = ? AND year = ? AND month = ?
                    """, (now, now, data_hash, dirty_ranges_json, workspace_id, year, month))
                else:
                    # Insert new
                    dirty_ranges_json = None if not dirty_ranges else json.dumps(dirty_ranges)
                    cursor.execute("""
                        INSERT INTO cache_metadata
                        (workspace_id, year, month, last_full_fetch, last_updated_at, data_hash, dirty_ranges)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (workspace_id, year, month, now, now, data_hash, dirty_ranges_json))
                
                conn.commit()
                return True
        except Exception as e:
            print(f"Error setting cache metadata: {e}")
            return False
    
    def mark_dirty_range(self, workspace_id: int, start_date: date, end_date: date) -> bool:
        """Mark a date range as dirty (needs refresh)."""
        try:
            # Determine which months are affected
            current = start_date
            months_to_update = set()
            
            while current <= end_date:
                months_to_update.add((current.year, current.month))
                # Move to next month
                if current.month == 12:
                    current = date(current.year + 1, 1, 1)
                else:
                    current = date(current.year, current.month + 1, 1)
            
            # Update each affected month
            for year, month in months_to_update:
                metadata = self.get_cache_metadata(workspace_id, year, month)
                if metadata:
                    dirty_ranges = metadata.get('dirty_ranges', [])
                else:
                    dirty_ranges = []
                
                # Add new range
                dirty_ranges.append({
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat()
                })
                
                # Merge overlapping ranges
                dirty_ranges = self._merge_dirty_ranges(dirty_ranges)
                
                self.set_cache_metadata(workspace_id, year, month, dirty_ranges=dirty_ranges)
            
            return True
        except Exception as e:
            print(f"Error marking dirty range: {e}")
            return False
    
    @staticmethod
    def _merge_dirty_ranges(ranges: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Merge overlapping date ranges."""
        if not ranges:
            return []
        
        # Parse dates and sort
        parsed = []
        for r in ranges:
            try:
                start = datetime.fromisoformat(r['start']).date()
                end = datetime.fromisoformat(r['end']).date()
                parsed.append((start, end))
            except (ValueError, KeyError):
                continue
        
        if not parsed:
            return []
        
        parsed.sort()
        
        # Merge overlapping
        merged = [parsed[0]]
        for start, end in parsed[1:]:
            last_start, last_end = merged[-1]
            if start <= last_end + timedelta(days=1):  # Overlapping or adjacent
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))
        
        # Convert back to dict format
        return [{'start': s.isoformat(), 'end': e.isoformat()} for s, e in merged]
    
    # Refresh queue methods
    def add_refresh_job(
        self,
        workspace_id: int,
        start_date: date,
        end_date: date,
        priority: int = 5
    ) -> int:
        """Add a refresh job to the queue. Returns job ID."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO refresh_queue
                    (workspace_id, start_date, end_date, priority, status, scheduled_at)
                    VALUES (?, ?, ?, ?, 'pending', ?)
                """, (
                    workspace_id,
                    start_date.isoformat(),
                    end_date.isoformat(),
                    priority,
                    datetime.now().isoformat()
                ))
                conn.commit()
                return cursor.lastrowid
        except Exception as e:
            print(f"Error adding refresh job: {e}")
            return -1
    
    def get_next_refresh_job(self) -> Optional[Dict[str, Any]]:
        """Get the next pending refresh job (highest priority first)."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT id, workspace_id, start_date, end_date, priority, retries
                    FROM refresh_queue
                    WHERE status = 'pending'
                    ORDER BY priority ASC, scheduled_at ASC
                    LIMIT 1
                """)
                row = cursor.fetchone()
                
                if row:
                    return {
                        'id': row[0],
                        'workspace_id': row[1],
                        'start_date': row[2],
                        'end_date': row[3],
                        'priority': row[4],
                        'retries': row[5]
                    }
                return None
        except Exception as e:
            print(f"Error getting next refresh job: {e}")
            return None
    
    def mark_refresh_job_started(self, job_id: int) -> bool:
        """Mark a refresh job as started."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE refresh_queue
                    SET status = 'running', started_at = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), job_id))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error marking refresh job started: {e}")
            return False
    
    def mark_refresh_job_completed(self, job_id: int, success: bool = True, error: Optional[str] = None) -> bool:
        """Mark a refresh job as completed."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                status = 'completed' if success else 'failed'
                cursor.execute("""
                    UPDATE refresh_queue
                    SET status = ?, completed_at = ?, last_error = ?
                    WHERE id = ?
                """, (status, datetime.now().isoformat(), error, job_id))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error marking refresh job completed: {e}")
            return False
    
    def increment_refresh_job_retries(self, job_id: int) -> bool:
        """Increment retry count for a refresh job."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE refresh_queue
                    SET retries = retries + 1, status = 'pending'
                    WHERE id = ?
                """, (job_id,))
                conn.commit()
                return True
        except Exception as e:
            print(f"Error incrementing refresh job retries: {e}")
            return False
