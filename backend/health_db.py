import os
import sqlite3
from pathlib import Path

_GRABBER_LOOP_KEY = 'grabber_last_loop_utc'
_DEVICE_SUCCESS_KEY = 'device_last_success_utc'


def _age_from_iso(value):
    from datetime import datetime, timezone
    try:
        last = datetime.fromisoformat(value)
    except ValueError:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return (now - last).total_seconds()


def _db_path():
    return str(Path('data/db.sqlite').resolve())


def check_database_readable():
    '''Return (ok, reason, detail) without creating or writing the DB.'''
    path = _db_path()
    if not os.path.isfile(path):
        return False, 'database_missing', 'data/db.sqlite not found'
    try:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            conn.execute('SELECT 1 FROM current LIMIT 1')
        finally:
            conn.close()
    except sqlite3.Error as exc:
        return False, 'database_unavailable', str(exc)
    return True, None, None


def read_meta_age_seconds_readonly(key):
    path = _db_path()
    if not os.path.isfile(path):
        return None
    try:
        conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            row = conn.execute(
                "SELECT value FROM schema_meta WHERE key = ?",
                (key,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    return _age_from_iso(row[0])
