'''Short-lived SQLite sessions with explicit commit/rollback.'''

from contextlib import contextmanager

from database import Database


@contextmanager
def db_session(path='data/db.sqlite'):
    db = Database(path)
    try:
        yield db
        db.connection.commit()
    except Exception:
        if db.connection is not None:
            db.connection.rollback()
        raise
    finally:
        db.close()
