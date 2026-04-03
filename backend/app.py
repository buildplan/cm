import asyncio, json, subprocess, os, secrets
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
SCRIPT    = Path("/app/container-monitor.sh")
STATE_F   = DATA_DIR / ".monitor_state.json"
CONFIG_F  = DATA_DIR / "config.yml"
LOG_F     = DATA_DIR / "container-monitor.log"
SECRET_TOKEN = os.environ.get("SECRET_TOKEN", "")

DEFAULT_CONFIG_TEMPLATE = """# Docker Container Monitor Configuration

general:
  log_lines_to_check: 40
  log_file: "container-monitor.log"
  update_check_cache_hours: 6 # check for new updates after 6 hours
  lock_timeout_seconds: 30 # configurable lock timeout
  healthchecks_job_url: "" # e.g., "https://hc.mydomain.com/ping/YOUR-KEY-HERE"
  healthchecks_fail_on: "" # Comma-separated list of issues to fail on:
                           # Status,Restarts,Resources,Disk,Network,Updates,Logs

logs:
  error_patterns:
    - "Exception"
    - "SEVERE"
    - "Traceback"
  log_clean_pattern: '^[^ ]+[[:space:]]+'

  ignore_patterns:
    my-pgdb:
      - "database system is ready to accept connections"
      - "incomplete startup packet"

auth:
  docker_username: ""
  docker_password: ""
  docker_config_path: "~/.docker/config.json"

thresholds:
  cpu_warning: 80
  memory_warning: 80
  disk_space: 80
  network_error: 10

host_system:
  disk_check_filesystem: "/"

notifications:
  channel: "none"
  notify_on: "Updates,Logs"

  discord:
    webhook_url: "https://discord.com/api/webhooks/xxxxxxxx"

  generic:
    webhook_url: "" 

  ntfy:
    server_url: "https://ntfy.sh"
    topic: "your_ntfy_topic_here"
    access_token: ""
    priority: 3
    icon_url: "https://raw.githubusercontent.com/buildplan/container-monitor/refs/heads/main/logo.png"
    click_url: ""

containers:
  # Add the names of containers to monitor by default
  monitor_defaults:
__DYNAMIC_MONITOR_DEFAULTS__

  # URLs for release notes, used for update checks
  release_urls:
    amir20/dozzle: "https://github.com/amir20/dozzle/releases"
    ghcr.io/moghtech/komodo-periphery: "https://github.com/moghtech/komodo/releases"
    henrygd/beszel: "https://github.com/henrygd/beszel/releases"
    codeberg.org/forgejo/forgejo: "https://forgejo.org/releases"
    postgres: "https://www.postgresql.org/docs/release/"
    portainer/portainer-ce: "https://github.com/portainer/portainer/releases"
    lscr.io/linuxserver/radarr: "https://github.com/lscr.io/linuxserver.io/pkgs/container/radarr"

  update_strategies:
    postgres: "digest"
    redis: "digest"
    themythologist/monkeytype: "digest"
    grafana/grafana: "semver"

  exclude:
    updates:
      - my-local-app-1     
      - my-backend-api     

auto_update:
  enabled: false
  tags:
    - "latest"
    - "stable"
    - "main"
    - "master"
    - "nightly"
  include: []  
  exclude:
    - "postgres"  
    - "mongo"
    - "redis"
"""

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
    cmd = [str(SCRIPT), "--no-update", *args]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=script_env()
        )
        out, _ = await proc.communicate()
        return proc.returncode, out.decode("utf-8", errors="replace")
    except Exception as e:
        error_msg = f"❌ Backend Execution Error: {str(e)}\n\n(If you see 'No such file or directory' or 'Exec format error', your container-monitor.sh script likely has Windows CRLF line endings. You need to convert it to LF formatting!)"
        return 1, error_msg

async def scheduled_run():
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
        if discovered_containers:
            yaml_list = "\n".join([f"    - \"{name}\"" for name in discovered_containers])
        else:
            yaml_list = "    # No running containers detected.\n    # - \"example-container\""
        final_config = DEFAULT_CONFIG_TEMPLATE.replace("__DYNAMIC_MONITOR_DEFAULTS__", yaml_list)
        final_config = final_config.replace("\r\n", "\n")
        CONFIG_F.write_text(final_config)
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
    args = ["--summary", "--force"] if force else ["--summary"]
    code, out = await run_script(*args)
    return {"exit_code": code, "output": out}

@app.post("/api/update/{container_name:path}")
async def update_container(container_name: str):
    inspect = subprocess.run(
        ["docker", "inspect", "--format", '{{index .Config.Labels "com.docker.compose.project.working_dir"}}', container_name],
        capture_output=True, text=True
    )
    working_dir = inspect.stdout.strip()
    if not working_dir or not Path(working_dir).is_dir():
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
            return {"exit_code": proc.returncode, "output": "\n".join(output_lines), "error": f"Failed: {' '.join(compose_args)}"}
    return {"exit_code": 0, "output": "\n".join(output_lines)}

@app.post("/api/prune")
async def prune_system():
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
    try:
        yaml.safe_load(data.yaml_text)
    except yaml.YAMLError as e:
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
