#!/usr/bin/env python3
"""
Database backup script for timetastic_toggl_sync.

Creates a backup of the SQLite database with:
- Timestamped filename
- SHA256 checksum for integrity verification
- Optional SQL dump
- Automatic rotation (keeps backups for specified retention period)

Usage:
    python scripts/backup_db.py
    python scripts/backup_db.py --retention-days 90
    python scripts/backup_db.py --db-path ./data/sync.db --backup-dir ./backups
"""

import os
import sys
import sqlite3
import hashlib
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import argparse

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from src.config import load_settings
except ImportError:
    print("Error: Cannot import src.config. Make sure you're running from project root.")
    sys.exit(1)


def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA256 checksum of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def create_sql_dump(db_path: Path, dump_path: Path) -> bool:
    """Create SQL dump of the database."""
    try:
        conn = sqlite3.connect(db_path)
        with open(dump_path, 'w', encoding='utf-8') as f:
            for line in conn.iterdump():
                f.write(f"{line}\n")
        conn.close()
        return True
    except Exception as e:
        print(f"Warning: Failed to create SQL dump: {e}")
        return False


def rotate_backups(backup_dir: Path, retention_days: int = 90) -> int:
    """Remove backups older than retention_days. Returns number of deleted backups."""
    if not backup_dir.exists():
        return 0
    
    cutoff_date = datetime.now() - timedelta(days=retention_days)
    deleted_count = 0
    
    for backup_file in backup_dir.glob("sync_*.db"):
        try:
            # Extract timestamp from filename: sync_YYYY-MM-DD_HH-MM.db
            filename = backup_file.stem  # sync_2025-01-15_02-00
            if len(filename) < 20:  # Minimum expected length
                continue
            
            date_str = filename[5:15]  # Extract YYYY-MM-DD
            time_str = filename[16:21]  # Extract HH-MM
            
            backup_datetime = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H-%M")
            
            if backup_datetime < cutoff_date:
                # Delete backup file and its checksum
                backup_file.unlink()
                checksum_file = backup_file.with_suffix('.db.sha256')
                if checksum_file.exists():
                    checksum_file.unlink()
                sql_file = backup_file.with_suffix('.sql')
                if sql_file.exists():
                    sql_file.unlink()
                deleted_count += 1
                print(f"  Deleted old backup: {backup_file.name}")
        except (ValueError, IndexError) as e:
            print(f"  Warning: Could not parse date from {backup_file.name}: {e}")
            continue
    
    return deleted_count


def backup_database(
    db_path: Optional[str] = None,
    backup_dir: Optional[str] = None,
    retention_days: int = 90,
    create_sql: bool = True
) -> bool:
    """Create a backup of the database."""
    
    # Load settings
    settings = load_settings()
    
    # Determine paths
    if db_path is None:
        db_path = settings.database_path
    
    db_path = Path(db_path).resolve()
    
    if backup_dir is None:
        backup_dir = Path("./backups")
    else:
        backup_dir = Path(backup_dir)
    
    # Check if database exists
    if not db_path.exists():
        print(f"Error: Database not found at {db_path}")
        return False
    
    # Create backup directory
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate timestamped filename
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    backup_filename = f"sync_{timestamp}.db"
    backup_path = backup_dir / backup_filename
    
    print(f"📦 Creating backup...")
    print(f"   Source: {db_path}")
    print(f"   Destination: {backup_path}")
    
    # Copy database file
    try:
        shutil.copy2(db_path, backup_path)
        print(f"✅ Database copied successfully")
    except Exception as e:
        print(f"❌ Error copying database: {e}")
        return False
    
    # Calculate checksum
    print(f"🔐 Calculating checksum...")
    checksum = calculate_sha256(backup_path)
    checksum_path = backup_path.with_suffix('.db.sha256')
    
    with open(checksum_path, 'w') as f:
        f.write(f"{checksum}  {backup_filename}\n")
    
    print(f"✅ Checksum: {checksum}")
    print(f"   Saved to: {checksum_path}")
    
    # Create SQL dump (optional)
    if create_sql:
        print(f"📄 Creating SQL dump...")
        sql_path = backup_path.with_suffix('.sql')
        if create_sql_dump(db_path, sql_path):
            print(f"✅ SQL dump created: {sql_path}")
        else:
            print(f"⚠️  SQL dump skipped")
    
    # Rotate old backups
    print(f"🔄 Rotating backups (retention: {retention_days} days)...")
    deleted = rotate_backups(backup_dir, retention_days)
    if deleted > 0:
        print(f"✅ Deleted {deleted} old backup(s)")
    else:
        print(f"✅ No old backups to delete")
    
    # Summary
    backup_size = backup_path.stat().st_size / (1024 * 1024)  # MB
    print(f"\n📊 Backup Summary:")
    print(f"   File: {backup_filename}")
    print(f"   Size: {backup_size:.2f} MB")
    print(f"   Checksum: {checksum}")
    print(f"   Location: {backup_path}")
    
    return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Backup SQLite database")
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Path to database file (default: from config)"
    )
    parser.add_argument(
        "--backup-dir",
        type=str,
        default=None,
        help="Directory for backups (default: ./backups)"
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=90,
        help="Number of days to keep backups (default: 90)"
    )
    parser.add_argument(
        "--no-sql",
        action="store_true",
        help="Skip SQL dump creation"
    )
    
    args = parser.parse_args()
    
    success = backup_database(
        db_path=args.db_path,
        backup_dir=args.backup_dir,
        retention_days=args.retention_days,
        create_sql=not args.no_sql
    )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

