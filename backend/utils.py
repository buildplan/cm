import os
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))
LOG_F = DATA_DIR / "container-monitor.log"

MONITOR_EXCEPTIONS = (
    OSError,
    ValueError,
    KeyError,
    TypeError,
    RuntimeError,
    ConnectionError,
)


def log_event(msg: str, level="INFO"):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"{timestamp} [{level}] {msg}\n"
    try:
        if LOG_F.exists() and LOG_F.stat().st_size > 10 * 1024 * 1024:
            with open(LOG_F, "r") as f:
                f.seek(0, 2)
                f.seek(max(f.tell() - 1024 * 1024, 0))
                tail = f.read()
            with open(LOG_F, "w") as f:
                f.write(tail[tail.find("\n") + 1 :])
        with open(LOG_F, "a") as f:
            f.write(log_line)
    except MONITOR_EXCEPTIONS as e:
        print(f"Ignored error: {e}")
    print(log_line.strip())
