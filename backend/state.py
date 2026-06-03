import sqlite3
import json
import os
from pathlib import Path

class StateManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')

            # Migrate from old JSON state if exists and db is empty
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM state')
            if cursor.fetchone()[0] == 0:
                old_state_file = self.db_path.parent / ".monitor_state.json"
                if old_state_file.exists():
                    try:
                        with open(old_state_file, "r") as f:
                            data = json.load(f)
                            for k, v in data.items():
                                conn.execute('INSERT INTO state (key, value) VALUES (?, ?)', (k, json.dumps(v)))
                    except Exception as e:
                        print(f"Error migrating old state: {e}")

    def get_all(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT key, value FROM state')
            return {row[0]: json.loads(row[1]) for row in cursor.fetchall()}

    def get(self, key, default=None):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT value FROM state WHERE key = ?', (key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return default

    def set(self, key, value):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)', (key, json.dumps(value)))

    def update(self, data: dict):
        with sqlite3.connect(self.db_path) as conn:
            for k, v in data.items():
                conn.execute('INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)', (k, json.dumps(v)))
