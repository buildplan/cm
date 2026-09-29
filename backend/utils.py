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


LOG_MAX_SIZE_MB = 10


def set_log_max_size(mb: int):
    global LOG_MAX_SIZE_MB
    LOG_MAX_SIZE_MB = mb


def log_event(msg: str, level="INFO"):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"{timestamp} [{level}] {msg}\n"
    try:
        if (
            LOG_MAX_SIZE_MB > 0
            and LOG_F.exists()
            and LOG_F.stat().st_size > LOG_MAX_SIZE_MB * 1024 * 1024
        ):
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


def setup_docker_config(auth_cfg):
    """
    Creates a temporary docker config.json and points DOCKER_CONFIG to it.
    This enables docker-py and subprocess(docker compose) to pick up credentials seamlessly.
    """
    import base64
    import json

    docker_config_dir = Path("/tmp/cm_docker_config")
    docker_config_dir.mkdir(parents=True, exist_ok=True)
    config_file = docker_config_dir / "config.json"

    auths = {}

    # Check if there's a custom user-mounted config we can merge/copy
    custom_path_str = auth_cfg.get("docker_config_path", "")
    if custom_path_str:
        p = Path(custom_path_str).expanduser()
        if p.exists():
            try:
                with open(p, "r") as f:
                    cfg = json.load(f)
                    auths = cfg.get("auths", {})
            except Exception as e:  # noqa: BLE001
                log_event(
                    f"Failed to read custom docker config path {p}: {e}", "WARNING"
                )
    else:
        # Default fallback locations if no custom path
        paths = [
            Path("/root/.docker/config.json"),
            Path.home() / ".docker" / "config.json",
        ]
        p = next((path for path in paths if path.exists()), None)
        if p:
            try:
                with open(p, "r") as f:
                    cfg = json.load(f)
                    auths = cfg.get("auths", {})
            except Exception:  # noqa: BLE001, S110
                pass

    # 1. Global credentials
    global_user = auth_cfg.get("docker_username", "")
    global_pwd = auth_cfg.get("docker_password", "")
    if global_user and global_pwd:
        auth_bytes = f"{global_user}:{global_pwd}".encode()
        auths["https://index.docker.io/v1/"] = {
            "auth": base64.b64encode(auth_bytes).decode("utf-8")
        }

    # 2. Per-registry credentials
    registries = auth_cfg.get("registries", {})
    for reg, reg_data in registries.items():
        user = reg_data.get("username", "")
        pwd = reg_data.get("password", "")
        if user and pwd:
            auth_bytes = f"{user}:{pwd}".encode()
            auths[reg] = {"auth": base64.b64encode(auth_bytes).decode("utf-8")}

    final_config = {"auths": auths}

    with open(config_file, "w") as f:
        json.dump(final_config, f, indent=2)

    os.environ["DOCKER_CONFIG"] = str(docker_config_dir)
