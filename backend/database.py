import sqlite3


class Database:
    def __init__(self, file_name):
        self.cursor = None
        self.connection = None
        self.open(file_name)

    def __del__(self):
        self.close()

    def open(self, file_name):
        '''Opens the database connection.'''
        self.connection = sqlite3.connect(file_name)
        self.cursor = self.connection.cursor()

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
