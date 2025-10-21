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
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_time_entries_user_email ON time_entries(user_email)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_time_entries_start_time ON time_entries(start_time)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_absences_user_email ON absences(user_email)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_absences_start_date ON absences(start_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_monthly_reports_user_period ON monthly_reports(user_email, year, month)")
            
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
                
                for entry in entries:
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
                
                for absence in absences:
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
        """Get absences for user within date range."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                query = "SELECT * FROM absences WHERE user_email = ?"
                params = [user_email.lower()]
                
                if start_date:
                    query += " AND start_date >= ?"
                    params.append(start_date.isoformat())
                
                if end_date:
                    query += " AND end_date <= ?"
                    params.append(end_date.isoformat())
                
                query += " ORDER BY start_date"
                
                cursor.execute(query, params)
                rows = cursor.fetchall()
                
                return [self._row_to_absence(row) for row in rows]
        except Exception as e:
            print(f"Error getting absences for {user_email}: {e}")
            return []
    
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
