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

# --- Shared Env ---
def script_env():
    return {
        **os.environ,
        "DATA_DIR": str(DATA_DIR),
        "CONTAINER_MODE": "true",
        "HOST_DISK_CHECK_FILESYSTEM": os.environ.get("HOST_DISK_CHECK_FILESYSTEM", "/hostfs"),
    }

async def run_script(*args) -> tuple[int, str]:
    cmd = [str(SCRIPT), "--no-update", *args]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=script_env()
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode("utf-8", errors="replace")

async def scheduled_run():
    await run_script("--summary")

@app.on_event("startup")
async def startup():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
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

@app.post("/api/update/{container_name}")
async def update_container(container_name: str):
    # Direct compose execution (Trap 1 Fix)
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

@app.get("/api/container-logs/{container_name}")
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

# --- Serve Frontend ---
app.mount("/", StaticFiles(directory="/app/frontend", html=True), name="frontend")
