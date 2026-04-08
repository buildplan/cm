import asyncio, json, subprocess, os, secrets
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from pydantic import BaseModel
import yaml

class ConfigUpdate(BaseModel): yaml_text: str

app = FastAPI(title="Container Monitor API")
scheduler = AsyncIOScheduler()

DATA_DIR  = Path(os.environ.get("DATA_DIR", "/app/data"))
SCRIPT    = Path("/app/backend/container-monitor.sh")
STATE_F   = DATA_DIR / ".monitor_state.json"
CONFIG_F  = DATA_DIR / "config.yml"
LOG_F     = DATA_DIR / "container-monitor.log"
SECRET_TOKEN = os.environ.get("SECRET_TOKEN", "")

# --- Unified Logging Function ---
def log_event(msg: str, level="INFO"):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"{timestamp} [{level}] {msg}\n"
    try:
        with open(LOG_F, "a") as f:
            f.write(log_line)
    except Exception:
        pass
    print(log_line.strip())

DEFAULT_CONFIG_TEMPLATE = """# Docker Container Monitor Configuration

general:
  log_lines_to_check: __LOG_LINES__
  log_file: "/app/data/container-monitor.log"
  update_check_cache_hours: __CACHE_HOURS__
  lock_timeout_seconds: __LOCK_TIMEOUT__
  healthchecks_job_url: "__HC_URL__"
  healthchecks_fail_on: "__HC_FAIL_ON__"

logs:
  error_patterns:
__ERROR_PATTERNS__
  log_clean_pattern: '__LOG_CLEAN__'

  ignore_patterns:
    my-pgdb:
      - "database system is ready to accept connections"
      - "incomplete startup packet"

auth:
  docker_username: "__DOCKER_USER__"
  docker_password: "__DOCKER_PASS__"
  docker_config_path: "~/.docker/config.json"

thresholds:
  cpu_warning: __CPU_WARN__
  memory_warning: __MEM_WARN__
  disk_space: __DISK_WARN__
  network_error: __NET_WARN__

host_system:
  disk_check_filesystem: "/"

notifications:
  channel: "__NOTIFY_CHANNEL__"
  notify_on: "__NOTIFY_ON__"

  discord:
    webhook_url: "__DISCORD_URL__"

  generic:
    webhook_url: "__GENERIC_URL__"

  ntfy:
    server_url: "__NTFY_URL__"
    topic: "__NTFY_TOPIC__"
    access_token: "__NTFY_TOKEN__"
    priority: __NTFY_PRIORITY__
    icon_url: "__NTFY_ICON__"
    click_url: "__NTFY_CLICK__"

containers:
  monitor_defaults:
__DYNAMIC_MONITOR_DEFAULTS__

  release_urls:
    amir20/dozzle: "https://github.com/amir20/dozzle/releases"
    ghcr.io/moghtech/komodo-periphery: "https://github.com/moghtech/komodo/releases"
    henrygd/beszel: "https://github.com/henrygd/beszel/releases"

  update_strategies:
    postgres: "digest"
    redis: "digest"
    some-specific-app: "major-lock"
    grafana/grafana: "semver"

  exclude:
    updates:
__EXCLUDE_UPDATES__

auto_update:
  enabled: __AUTO_UPDATE_ENABLED__
  tags:
__AUTO_UPDATE_TAGS__
  include: []
  exclude:
__AUTO_UPDATE_EXCLUDE__
"""

def build_yaml_list(env_val, default_list, indent=4):
    items = [x.strip() for x in env_val.split(",")] if env_val else default_list
    if not items or items == [""]:
        return " " * indent + "# - \"none\""
    return "\n".join([f"{' ' * indent}- \"{item}\"" for item in items])

# --- Auth Middleware ---
@app.middleware("http")
async def token_auth(request: Request, call_next):
    if request.url.path.startswith("/api"):
        if SECRET_TOKEN:
            auth_header = request.headers.get("Authorization", "")
            token = auth_header.removeprefix("Bearer ").strip()
            if not token or not secrets.compare_digest(token.encode(), SECRET_TOKEN.encode()):
                return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return await call_next(request)

def script_env():
    return {
        **os.environ,
        "DATA_DIR": str(DATA_DIR),
        "CONTAINER_MODE": "true",
        "HOST_DISK_CHECK_FILESYSTEM": os.environ.get("HOST_DISK_CHECK_FILESYSTEM", "/hostfs"),
    }

async def run_script(*args) -> tuple[int, str]:
    cmd = [str(SCRIPT), *args]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=script_env()
        )
        out, _ = await proc.communicate()
        return proc.returncode, out.decode("utf-8", errors="replace")
    except Exception as e:
        error_msg = f"❌ Backend Execution Error: {str(e)}"
        return 1, error_msg

async def scheduled_run():
    log_event("Triggering scheduled background check...", "API")
    await run_script("--summary")

@app.on_event("startup")
async def startup():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_F.exists():
        try:
            result = subprocess.run(["docker", "ps", "-a", "--format", "{{.Names}}"], capture_output=True, text=True, check=True)
            discovered_containers = [name.strip() for name in result.stdout.splitlines() if name.strip()]
        except Exception as e:
            print(f"Failed to auto-discover containers: {e}")
            discovered_containers = []

        yaml_list = "\n".join([f"    - \"{name}\"" for name in discovered_containers]) if discovered_containers else "    # - \"example-container\""

        # Load template
        final_config = DEFAULT_CONFIG_TEMPLATE.replace("__DYNAMIC_MONITOR_DEFAULTS__", yaml_list)

        # ... (Environment Mapping) ...
        final_config = final_config.replace("__LOG_LINES__", os.environ.get("LOG_LINES_TO_CHECK", "40"))
        final_config = final_config.replace("__CACHE_HOURS__", os.environ.get("UPDATE_CHECK_CACHE_HOURS", "6"))
        final_config = final_config.replace("__LOCK_TIMEOUT__", os.environ.get("LOCK_TIMEOUT_SECONDS", "30"))
        final_config = final_config.replace("__HC_URL__", os.environ.get("HEALTHCHECKS_JOB_URL", ""))
        final_config = final_config.replace("__HC_FAIL_ON__", os.environ.get("HEALTHCHECKS_FAIL_ON", ""))
        final_config = final_config.replace("__LOG_CLEAN__", os.environ.get("LOG_CLEAN_PATTERN", "^[^ ]+[[:space:]]+"))
        final_config = final_config.replace("__DOCKER_USER__", os.environ.get("DOCKER_USERNAME", ""))
        final_config = final_config.replace("__DOCKER_PASS__", os.environ.get("DOCKER_PASSWORD", ""))

        final_config = final_config.replace("__CPU_WARN__", os.environ.get("CPU_WARNING_THRESHOLD", "80"))
        final_config = final_config.replace("__MEM_WARN__", os.environ.get("MEMORY_WARNING_THRESHOLD", "80"))
        final_config = final_config.replace("__DISK_WARN__", os.environ.get("DISK_SPACE_THRESHOLD", "80"))
        final_config = final_config.replace("__NET_WARN__", os.environ.get("NETWORK_ERROR_THRESHOLD", "10"))

        final_config = final_config.replace("__NOTIFY_CHANNEL__", os.environ.get("NOTIFICATION_CHANNEL", "none"))
        final_config = final_config.replace("__NOTIFY_ON__", os.environ.get("NOTIFY_ON", "Updates,Logs"))
        final_config = final_config.replace("__DISCORD_URL__", os.environ.get("DISCORD_WEBHOOK_URL", ""))
        final_config = final_config.replace("__GENERIC_URL__", os.environ.get("GENERIC_WEBHOOK_URL", ""))

        final_config = final_config.replace("__NTFY_URL__", os.environ.get("NTFY_SERVER_URL", "https://ntfy.sh"))
        final_config = final_config.replace("__NTFY_TOPIC__", os.environ.get("NTFY_TOPIC", "your_ntfy_topic_here"))
        final_config = final_config.replace("__NTFY_TOKEN__", os.environ.get("NTFY_ACCESS_TOKEN", ""))
        final_config = final_config.replace("__NTFY_PRIORITY__", os.environ.get("NTFY_PRIORITY", "3"))
        final_config = final_config.replace("__NTFY_ICON__", os.environ.get("NTFY_ICON_URL", "https://raw.githubusercontent.com/buildplan/container-monitor/refs/heads/main/logo.png"))
        final_config = final_config.replace("__NTFY_CLICK__", os.environ.get("NTFY_CLICK_URL", ""))

        final_config = final_config.replace("__AUTO_UPDATE_ENABLED__", os.environ.get("AUTO_UPDATE_ENABLED", "false").lower())

        # --- Map Comma-Separated List Variables ---
        final_config = final_config.replace("__ERROR_PATTERNS__", build_yaml_list(os.environ.get("LOG_ERROR_PATTERNS", ""), ["Exception", "SEVERE", "Traceback"], 4))
        final_config = final_config.replace("__EXCLUDE_UPDATES__", build_yaml_list(os.environ.get("EXCLUDE_UPDATES", ""), ["my-local-app-1", "my-backend-api"], 6))
        final_config = final_config.replace("__AUTO_UPDATE_TAGS__", build_yaml_list(os.environ.get("AUTO_UPDATE_TAGS", ""), ["latest", "stable", "main", "master", "nightly"], 4))
        final_config = final_config.replace("__AUTO_UPDATE_EXCLUDE__", build_yaml_list(os.environ.get("AUTO_UPDATE_EXCLUDE", ""), ["postgres", "mongo", "redis"], 4))

        final_config = final_config.replace("\r\n", "\n")
        CONFIG_F.write_text(final_config)

    log_event("Container Monitor API started successfully.", "API")
    interval_hours = int(os.environ.get("MONITOR_INTERVAL_HOURS", 6))
    scheduler.add_job(scheduled_run, IntervalTrigger(hours=interval_hours), id="monitor")
    scheduler.start()

# --- API Endpoints ---
@app.get("/api/state")
async def get_state():
    if not STATE_F.exists(): return {}
    return json.loads(STATE_F.read_text())

@app.get("/api/containers")
async def get_containers():
    result = subprocess.run(["docker", "ps", "-a", "--format", "{{json .}}"], capture_output=True, text=True)
    return [json.loads(l) for l in result.stdout.strip().splitlines() if l]

@app.post("/api/run")
async def trigger_run(force: bool = False):
    log_event(f"Manual monitor check triggered (Force cache bypass: {force})", "API")
    args = ["--summary", "--force"] if force else ["--summary"]
    code, out = await run_script(*args)
    return {"exit_code": code, "output": out}

@app.post("/api/update/{container_name:path}")
async def update_container(container_name: str):
    log_event(f"Pull & Recreate requested for container: {container_name}", "API")
    inspect = subprocess.run(
        ["docker", "inspect", "--format", '{{index .Config.Labels "com.docker.compose.project.working_dir"}}', container_name],
        capture_output=True, text=True
    )
    working_dir = inspect.stdout.strip()
    if not working_dir or not Path(working_dir).is_dir():
        log_event(f"Update failed: {container_name} lacks a valid working_dir", "ERROR")
        raise HTTPException(400, f"'{container_name}' lacks a compose working_dir label, or '{working_dir}' isn't mounted.")

    output_lines = []
    for compose_args in [["pull"], ["up", "-d", "--force-recreate"]]:
        proc = await asyncio.create_subprocess_exec(
            "docker", "compose", *compose_args, cwd=working_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        output_lines.append(out.decode("utf-8", errors="replace"))
        if proc.returncode != 0:
            log_event(f"Update failed for {container_name} during '{' '.join(compose_args)}'", "ERROR")
            return {"exit_code": proc.returncode, "output": "\n".join(output_lines), "error": f"Failed: {' '.join(compose_args)}"}

    log_event(f"Successfully updated {container_name}", "GOOD")
    return {"exit_code": 0, "output": "\n".join(output_lines)}

@app.post("/api/prune")
async def prune_system():
    log_event("System cleanup (prune -a) triggered via Web UI", "API")
    proc = await asyncio.create_subprocess_exec(
        "docker", "system", "prune", "-af",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await proc.communicate()
    return {"exit_code": proc.returncode, "output": out.decode("utf-8", errors="replace")}

@app.post("/api/containers/{action}/{container_name:path}")
async def control_container(action: str, container_name: str):
    if action not in ["start", "stop", "restart"]:
        raise HTTPException(400, "Invalid action")

    log_event(f"Command '{action}' sent to container: {container_name}", "API")
    proc = await asyncio.create_subprocess_exec(
        "docker", action, container_name,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return {"exit_code": proc.returncode, "error": out.decode("utf-8", errors="replace")}
    return {"exit_code": 0, "output": out.decode("utf-8", errors="replace").strip()}

@app.get("/api/logs")
async def get_monitor_log(lines: int = 200):
    if not LOG_F.exists(): return {"lines": []}
    return {"lines": LOG_F.read_text().splitlines()[-lines:]}

@app.get("/api/config")
async def get_config():
    if not CONFIG_F.exists(): raise HTTPException(404, "config.yml not found")
    return {"yaml_text": CONFIG_F.read_text()}

@app.put("/api/config")
async def update_config(data: ConfigUpdate):
    log_event("User updated configuration via Web UI", "API")
    try:
        yaml.safe_load(data.yaml_text)
    except yaml.YAMLError as e:
        log_event(f"Failed to save configuration: Invalid YAML", "ERROR")
        raise HTTPException(400, f"Invalid YAML format: {e}")
    CONFIG_F.write_text(data.yaml_text)
    return {"status": "saved"}

@app.get("/api/container-logs/{container_name:path}")
async def get_container_logs(container_name: str):
    code, out = await run_script("--logs", container_name)
    return {"output": out}

@app.get("/api/host-stats")
async def get_host_stats():
    fs = os.environ.get("HOST_DISK_CHECK_FILESYSTEM", "/hostfs")
    disk_info = {"percent": "0%", "size": "0G", "used": "0G", "fs": fs}
    try:
        disk_cmd = subprocess.run(["df", "-Ph", fs], capture_output=True, text=True)
        disk_lines = disk_cmd.stdout.strip().split("\n")
        if len(disk_lines) > 1:
            parts = disk_lines[1].split()
            if len(parts) >= 5:
                disk_info = {"size": parts[1], "used": parts[2], "percent": parts[4], "fs": fs}
    except Exception: pass
    mem_info = {"percent": "0%", "total": "0MB", "used": "0MB"}
    try:
        mem_cmd = subprocess.run(["free", "-m"], capture_output=True, text=True)
        mem_lines = mem_cmd.stdout.strip().split("\n")
        if len(mem_lines) > 1:
            parts = mem_lines[1].split()
            if len(parts) >= 3:
                total = int(parts[1])
                used = int(parts[2])
                percent = int((used / total) * 100) if total > 0 else 0
                mem_info = {"total": f"{total}MB", "used": f"{used}MB", "percent": f"{percent}%"}
    except Exception: pass
    cpu_load = "0.00"
    try:
        with open("/proc/loadavg", "r") as f:
            cpu_load = f.read().split()[0]
    except Exception: pass
    return {"disk": disk_info, "memory": mem_info, "cpu_load": cpu_load}

app.mount("/", StaticFiles(directory="/app/frontend", html=True), name="frontend")
