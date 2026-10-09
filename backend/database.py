import os
import sqlite3


class DatabaseMissingError(FileNotFoundError):
    '''Raised when opening a database that must already exist.'''


class Database:
    def __init__(self, file_name, create=True):
        self.cursor = None
        self.connection = None
        self.open(file_name, create=create)

    def __del__(self):
        self.close()

    def open(self, file_name, create=True):
        '''Opens the database connection.'''
        if create:
            self.connection = sqlite3.connect(file_name, timeout=5.0)
        else:
            if not os.path.isfile(file_name):
                raise DatabaseMissingError(file_name)
            abs_path = os.path.abspath(file_name)
            self.connection = sqlite3.connect(
                f'file:{abs_path}?mode=rw', uri=True, timeout=5.0)
        self.cursor = self.connection.cursor()
        self.connection.execute("PRAGMA busy_timeout=5000")

    def close(self):
        '''Closes the data base.'''
        if self.connection is None:
            return
        self.connection.commit()
        self.connection.close()
        self.connection = None
        self.cursor = None

    def execute(self, query):
        '''Executes a query and returns resulting rows.'''
        self.cursor.execute(query)
        return self.cursor.fetchall()

    def execute_params(self, query, params=()):
        '''Executes a parameterized query and returns resulting rows.'''
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def execute_params_no_result(self, query, params=()):
        '''Executes a parameterized statement without returning rows.'''
        self.cursor.execute(query, params)


def open_database(path='data/db.sqlite', create=True):
    '''Open a database; use create=False from the web server (never create files).'''
    return Database(path, create=create)
