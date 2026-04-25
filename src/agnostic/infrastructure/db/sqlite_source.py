import sqlite3
from pathlib import Path

class SQLiteDataSource:
    source_type = "sqlite"

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.connection = None

    def connect(self):
        if not self.connection:
            self.connection = sqlite3.connect(self.db_path)
            # Aumentar o limite de tamanho do buffer para 10MB
            self.connection.execute("PRAGMA cache_size = -2000;")
        return self.connection

    def list_units(self) -> list["SQLiteTabularUnit"]:
        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        return [SQLiteTabularUnit(table, self.db_path) for table in tables]

    def close(self):
        if self.connection:
            self.connection.close()
            self.connection = None
