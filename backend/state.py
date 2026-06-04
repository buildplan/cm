import sqlite3
import json
import time
from pathlib import Path


class StateManager:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS state (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    container_name TEXT,
                    timestamp INTEGER,
                    cpu_percent REAL,
                    mem_percent REAL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_metrics_container ON metrics(container_name)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_metrics_time ON metrics(timestamp)"
            )

            # Migrate from old JSON state if exists and db is empty
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM state")
            if cursor.fetchone()[0] == 0:
                old_state_file = self.db_path.parent / ".monitor_state.json"
                if old_state_file.exists():
                    try:
                        with open(old_state_file, "r") as f:
                            data = json.load(f)
                            for k, v in data.items():
                                conn.execute(
                                    "INSERT INTO state (key, value) VALUES (?, ?)",
                                    (k, json.dumps(v)),
                                )
                    except Exception as e:
                        print(f"Error migrating old state: {e}")

    def get_all(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM state")
            return {row[0]: json.loads(row[1]) for row in cursor.fetchall()}

    def get(self, key, default=None):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM state WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return default

    def set(self, key, value):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )

    def update(self, data: dict):
        with sqlite3.connect(self.db_path) as conn:
            for k, v in data.items():
                conn.execute(
                    "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                    (k, json.dumps(v)),
                )

    def record_metrics(
        self, container_name: str, cpu_percent: float, mem_percent: float
    ):
        now = int(time.time())
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO metrics (container_name, timestamp, cpu_percent, mem_percent)
                VALUES (?, ?, ?, ?)
            """,
                (container_name, now, round(cpu_percent, 2), round(mem_percent, 2)),
            )

            # Keep only last 24 hours (86400 seconds)
            conn.execute("DELETE FROM metrics WHERE timestamp < ?", (now - 86400,))

    def get_metrics(self, container_name: str, hours: int = 24):
        since = int(time.time()) - (hours * 3600)
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT timestamp, cpu_percent, mem_percent
                FROM metrics
                WHERE container_name = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            """,
                (container_name, since),
            )
            rows = cursor.fetchall()
            return [{"t": r[0], "cpu": r[1], "mem": r[2]} for r in rows]
