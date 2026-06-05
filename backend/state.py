import sqlite3
import json
import time
from pathlib import Path


class StateManager:
    _db_initialized = False

    def __init__(self, db_path: Path):
        self.db_path = db_path
        if not StateManager._db_initialized:
            self.init_db()
            StateManager._db_initialized = True

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def init_db(self):
        with self._get_conn() as conn:
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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS webauthn_credentials (
                    credential_id TEXT PRIMARY KEY,
                    public_key TEXT,
                    sign_count INTEGER,
                    user_id TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token TEXT PRIMARY KEY,
                    created_at INTEGER
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
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM state")
            return {row[0]: json.loads(row[1]) for row in cursor.fetchall()}

    def get(self, key, default=None):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM state WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return default

    def set(self, key, value):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )

    def update(self, data: dict):
        with self._get_conn() as conn:
            for k, v in data.items():
                conn.execute(
                    "INSERT OR REPLACE INTO state (key, value) VALUES (?, ?)",
                    (k, json.dumps(v)),
                )

    def record_metrics(
        self, container_name: str, cpu_percent: float, mem_percent: float
    ):
        now = int(time.time())
        with self._get_conn() as conn:
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
        with self._get_conn() as conn:
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

    def add_webauthn_credential(
        self, credential_id: str, public_key: str, sign_count: int, user_id: str
    ):
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO webauthn_credentials (credential_id, public_key, sign_count, user_id) VALUES (?, ?, ?, ?)",
                (credential_id, public_key, sign_count, user_id),
            )

    def get_webauthn_credentials(self, user_id: str = "admin"):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT credential_id, public_key, sign_count FROM webauthn_credentials WHERE user_id = ?",
                (user_id,),
            )
            return [
                {"id": r[0], "public_key": r[1], "sign_count": r[2]}
                for r in cursor.fetchall()
            ]

    def update_webauthn_sign_count(self, credential_id: str, sign_count: int):
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE webauthn_credentials SET sign_count = ? WHERE credential_id = ?",
                (sign_count, credential_id),
            )

    def create_auth_session(self, token: str):
        now = int(time.time())
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO auth_sessions (token, created_at) VALUES (?, ?)",
                (token, now),
            )

    def is_valid_auth_session(self, token: str, max_age_hours: int = 24) -> bool:
        min_created = int(time.time()) - (max_age_hours * 3600)
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM auth_sessions WHERE token = ? AND created_at >= ?",
                (token, min_created),
            )
            return cursor.fetchone() is not None
