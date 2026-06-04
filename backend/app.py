import asyncio
import json
import subprocess
import os
import secrets
import time
from datetime import datetime
from pathlib import Path
from collections import defaultdict
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from pydantic import BaseModel
import yaml
from contextlib import asynccontextmanager
import base64
from webauthn import (
    generate_registration_options,
    verify_registration_response,
    generate_authentication_options,
    verify_authentication_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    UserVerificationRequirement,
)
from webauthn.helpers.options_to_json import options_to_json
from webauthn.helpers import base64url_to_bytes

import docker
from backend.monitor import Monitor, get_container_logs
from backend.state import StateManager
from backend.config import AppConfig


class ConfigUpdate(BaseModel):
    yaml_text: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup()
    yield


app = FastAPI(title="Container Monitor API", lifespan=lifespan)
scheduler = AsyncIOScheduler()

DATA_DIR = Path(os.environ.get("DATA_DIR", "/app/data"))

STATE_DB = DATA_DIR / "monitor_state.db"
CONFIG_F = DATA_DIR / "config.yml"
LOG_F = DATA_DIR / "container-monitor.log"
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
  monitor_interval_minutes: __INTERVAL_MINS__
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
        return " " * indent + '# - "none"'
    return "\n".join([f'{" " * indent}- "{item}"' for item in items])


# --- Rate Limiter ---
AUTH_MAX_ATTEMPTS = 5
AUTH_WINDOW_SECONDS = 60
auth_failures = defaultdict(list)


def is_rate_limited(client_ip: str) -> bool:
    now = time.time()
    recent = [ts for ts in auth_failures[client_ip] if now - ts < AUTH_WINDOW_SECONDS]
    auth_failures[client_ip] = recent
    return len(recent) >= AUTH_MAX_ATTEMPTS


def record_auth_failure(client_ip: str):
    auth_failures[client_ip].append(time.time())


# --- Auth Middleware ---
@app.middleware("http")
async def token_auth(request: Request, call_next):
    if (
        request.url.path.startswith("/api")
        and not request.url.path.startswith("/api/auth/login")
        and not request.url.path.startswith("/api/auth/status")
    ):
        try:
            mgr = StateManager(STATE_DB)
            has_passkeys = len(mgr.get_webauthn_credentials("admin")) > 0
        except Exception:
            has_passkeys = False

        try:
            with open(CONFIG_F, "r") as f:
                cfg = yaml.safe_load(f)
            disable_token_auth = cfg.get("auth", {}).get("disable_token_auth", False)
        except Exception:
            disable_token_auth = False

        if SECRET_TOKEN or has_passkeys:
            client_ip = request.client.host if request.client else "unknown"
            if is_rate_limited(client_ip):
                return JSONResponse(
                    status_code=429,
                    content={"error": "Too many failed attempts. Try again later."},
                )

            auth_header = request.headers.get("Authorization", "")
            token = auth_header.removeprefix("Bearer ").strip()
            if not token:
                token = request.query_params.get("token", "")

            is_valid = False
            # Check Token Login
            if (
                not disable_token_auth
                and SECRET_TOKEN
                and token
                and secrets.compare_digest(token.encode(), SECRET_TOKEN.encode())
            ):
                is_valid = True
            # Check Passkey Session
            elif token and has_passkeys and mgr.is_valid_auth_session(token):
                is_valid = True

            if not is_valid:
                record_auth_failure(client_ip)
                return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return await call_next(request)


sse_clients = set()


def broadcast_event(event_type: str, data: dict):
    msg = json.dumps({"type": event_type, "data": data})
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    for q in list(sse_clients):
        loop.call_soon_threadsafe(q.put_nowait, msg)


async def event_generator(q: asyncio.Queue):
    try:
        while True:
            msg = await q.get()
            yield f"data: {msg}\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        sse_clients.discard(q)


@app.get("/api/events")
async def sse_events(request: Request):
    q = asyncio.Queue()
    sse_clients.add(q)
    return StreamingResponse(event_generator(q), media_type="text/event-stream")


async def scheduled_run():
    log_event("Triggering scheduled background check...", "API")
    try:
        monitor = Monitor(on_update=broadcast_event)
        await asyncio.to_thread(monitor.run)
    except Exception as e:
        log_event(f"Scheduled run failed: {e}", "ERROR")


async def docker_event_listener():
    loop = asyncio.get_running_loop()

    def listen_events():
        while True:
            try:
                client = docker.from_env()
                for event in client.events(decode=True):
                    if event.get("Type") == "container":
                        status = event.get("status")
                        if status in (
                            "start",
                            "stop",
                            "die",
                            "restart",
                            "kill",
                            "pause",
                            "unpause",
                        ):
                            msg = json.dumps(
                                {
                                    "type": "docker_event",
                                    "action": status,
                                    "container": event.get("Actor", {})
                                    .get("Attributes", {})
                                    .get("name"),
                                }
                            )
                            for q in list(sse_clients):
                                loop.call_soon_threadsafe(q.put_nowait, msg)
            except Exception as e:
                loop.call_soon_threadsafe(
                    log_event,
                    f"Docker event listener disconnected: {e}. Retrying in 5 seconds...",
                    "WARNING",
                )
                time.sleep(5)

    try:
        await asyncio.to_thread(listen_events)
    except Exception as e:
        log_event(f"Docker event listener thread failed: {e}", "ERROR")


async def startup():
    asyncio.create_task(docker_event_listener())
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_F.exists():
        try:
            result = subprocess.run(
                ["docker", "ps", "-a", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                check=True,
            )
            discovered_containers = [
                name.strip() for name in result.stdout.splitlines() if name.strip()
            ]
        except Exception as e:
            print(f"Failed to auto-discover containers: {e}")
            discovered_containers = []

        yaml_list = (
            "\n".join([f'    - "{name}"' for name in discovered_containers])
            if discovered_containers
            else '    # - "example-container"'
        )

        # Load template
        final_config = DEFAULT_CONFIG_TEMPLATE.replace(
            "__DYNAMIC_MONITOR_DEFAULTS__", yaml_list
        )

        # ... (Environment Mapping) ...
        final_config = final_config.replace(
            "__INTERVAL_MINS__", os.environ.get("MONITOR_INTERVAL_MINUTES", "360")
        )
        final_config = final_config.replace(
            "__LOG_LINES__", os.environ.get("LOG_LINES_TO_CHECK", "40")
        )
        final_config = final_config.replace(
            "__CACHE_HOURS__", os.environ.get("UPDATE_CHECK_CACHE_HOURS", "6")
        )
        final_config = final_config.replace(
            "__LOCK_TIMEOUT__", os.environ.get("LOCK_TIMEOUT_SECONDS", "30")
        )
        final_config = final_config.replace(
            "__HC_URL__", os.environ.get("HEALTHCHECKS_JOB_URL", "")
        )
        final_config = final_config.replace(
            "__HC_FAIL_ON__", os.environ.get("HEALTHCHECKS_FAIL_ON", "")
        )
        final_config = final_config.replace(
            "__LOG_CLEAN__", os.environ.get("LOG_CLEAN_PATTERN", "^[^ ]+[[:space:]]+")
        )
        final_config = final_config.replace(
            "__DOCKER_USER__", os.environ.get("DOCKER_USERNAME", "")
        )
        final_config = final_config.replace(
            "__DOCKER_PASS__", os.environ.get("DOCKER_PASSWORD", "")
        )

        final_config = final_config.replace(
            "__CPU_WARN__", os.environ.get("CPU_WARNING_THRESHOLD", "80")
        )
        final_config = final_config.replace(
            "__MEM_WARN__", os.environ.get("MEMORY_WARNING_THRESHOLD", "80")
        )
        final_config = final_config.replace(
            "__DISK_WARN__", os.environ.get("DISK_SPACE_THRESHOLD", "80")
        )
        final_config = final_config.replace(
            "__NET_WARN__", os.environ.get("NETWORK_ERROR_THRESHOLD", "10")
        )

        final_config = final_config.replace(
            "__NOTIFY_CHANNEL__", os.environ.get("NOTIFICATION_CHANNEL", "none")
        )
        final_config = final_config.replace(
            "__NOTIFY_ON__", os.environ.get("NOTIFY_ON", "Updates,Logs")
        )
        final_config = final_config.replace(
            "__DISCORD_URL__", os.environ.get("DISCORD_WEBHOOK_URL", "")
        )
        final_config = final_config.replace(
            "__GENERIC_URL__", os.environ.get("GENERIC_WEBHOOK_URL", "")
        )

        final_config = final_config.replace(
            "__NTFY_URL__", os.environ.get("NTFY_SERVER_URL", "https://ntfy.sh")
        )
        final_config = final_config.replace(
            "__NTFY_TOPIC__", os.environ.get("NTFY_TOPIC", "your_ntfy_topic_here")
        )
        final_config = final_config.replace(
            "__NTFY_TOKEN__", os.environ.get("NTFY_ACCESS_TOKEN", "")
        )
        final_config = final_config.replace(
            "__NTFY_PRIORITY__", os.environ.get("NTFY_PRIORITY", "3")
        )
        final_config = final_config.replace(
            "__NTFY_ICON__",
            os.environ.get(
                "NTFY_ICON_URL",
                "https://raw.githubusercontent.com/buildplan/container-monitor/refs/heads/main/logo.png",
            ),
        )
        final_config = final_config.replace(
            "__NTFY_CLICK__", os.environ.get("NTFY_CLICK_URL", "")
        )

        final_config = final_config.replace(
            "__AUTO_UPDATE_ENABLED__",
            os.environ.get("AUTO_UPDATE_ENABLED", "false").lower(),
        )

        # --- Map Comma-Separated List Variables ---
        final_config = final_config.replace(
            "__ERROR_PATTERNS__",
            build_yaml_list(
                os.environ.get("LOG_ERROR_PATTERNS", ""),
                ["Exception", "SEVERE", "Traceback"],
                4,
            ),
        )
        final_config = final_config.replace(
            "__EXCLUDE_UPDATES__",
            build_yaml_list(
                os.environ.get("EXCLUDE_UPDATES", ""),
                ["my-local-app-1", "my-backend-api"],
                6,
            ),
        )
        final_config = final_config.replace(
            "__AUTO_UPDATE_TAGS__",
            build_yaml_list(
                os.environ.get("AUTO_UPDATE_TAGS", ""),
                ["latest", "stable", "main", "master", "nightly"],
                4,
            ),
        )
        final_config = final_config.replace(
            "__AUTO_UPDATE_EXCLUDE__",
            build_yaml_list(
                os.environ.get("AUTO_UPDATE_EXCLUDE", ""),
                ["postgres", "mongo", "redis"],
                4,
            ),
        )

        final_config = final_config.replace("\r\n", "\n")
        CONFIG_F.write_text(final_config)

    log_event("Container Monitor API started successfully.", "API")

    # Read interval from existing config.yml
    try:
        with open(CONFIG_F, "r") as f:
            cfg = yaml.safe_load(f)
        interval_mins = int(cfg.get("general", {}).get("monitor_interval_minutes", 360))
    except Exception:
        interval_mins = 360

    scheduler.add_job(
        scheduled_run, IntervalTrigger(minutes=interval_mins), id="monitor"
    )
    scheduler.start()


# --- API Endpoints ---
@app.get("/api/auth/status")
async def auth_status():
    try:
        mgr = StateManager(STATE_DB)
        has_passkeys = len(mgr.get_webauthn_credentials("admin")) > 0
    except Exception:
        has_passkeys = False

    try:
        with open(CONFIG_F, "r") as f:
            cfg = yaml.safe_load(f)
        disable_token_auth = cfg.get("auth", {}).get("disable_token_auth", False)
    except Exception:
        disable_token_auth = False

    token_enabled = not disable_token_auth and bool(SECRET_TOKEN)
    auth_required = bool(SECRET_TOKEN) or has_passkeys

    return {
        "has_passkeys": has_passkeys,
        "token_auth_enabled": token_enabled,
        "auth_required": auth_required,
    }


@app.get("/api/state")
async def get_state():
    mgr = StateManager(STATE_DB)
    return mgr.get_all()


webauthn_challenges = {}


@app.get("/api/auth/register/generate-options")
async def register_generate_options(request: Request):
    user_id = "admin"
    mgr = StateManager(STATE_DB)
    credentials = mgr.get_webauthn_credentials(user_id)
    exclude_credentials = [
        {"id": base64.b64decode(c["id"]), "type": "public-key"} for c in credentials
    ]

    rp_id = request.url.hostname or "localhost"
    rp_name = "Container Monitor"

    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
        user_id=user_id.encode("utf-8"),
        user_name=user_id,
        exclude_credentials=exclude_credentials,
        authenticator_selection=AuthenticatorSelectionCriteria(
            user_verification=UserVerificationRequirement.PREFERRED
        ),
    )
    webauthn_challenges[user_id] = options.challenge
    return json.loads(options_to_json(options))


@app.post("/api/auth/register/verify")
async def register_verify(request: Request):
    user_id = "admin"
    body = await request.json()
    challenge = webauthn_challenges.get(user_id)
    if not challenge:
        raise HTTPException(status_code=400, detail="No challenge found")

    rp_id = request.url.hostname or "localhost"
    origin = request.headers.get("origin")
    if not origin:
        host_header = request.headers.get("host", request.url.netloc)
        origin = f"{request.url.scheme}://{host_header}"

    try:
        verification = verify_registration_response(
            credential=body,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    mgr = StateManager(STATE_DB)
    mgr.add_webauthn_credential(
        credential_id=base64.b64encode(verification.credential_id).decode("utf-8"),
        public_key=base64.b64encode(verification.credential_public_key).decode("utf-8"),
        sign_count=verification.sign_count,
        user_id=user_id,
    )
    webauthn_challenges.pop(user_id, None)
    return {"status": "ok"}


@app.get("/api/auth/login/generate-options")
async def login_generate_options(request: Request):
    rp_id = request.url.hostname or "localhost"

    options = generate_authentication_options(
        rp_id=rp_id,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    webauthn_challenges["login"] = options.challenge
    return json.loads(options_to_json(options))


@app.post("/api/auth/login/verify")
async def login_verify(request: Request):
    body = await request.json()
    challenge = webauthn_challenges.get("login")
    if not challenge:
        raise HTTPException(status_code=400, detail="No challenge found")

    rp_id = request.url.hostname or "localhost"
    origin = request.headers.get("origin")
    if not origin:
        host_header = request.headers.get("host", request.url.netloc)
        origin = f"{request.url.scheme}://{host_header}"
    mgr = StateManager(STATE_DB)
    cred_id_str = body.get("id")
    if not cred_id_str:
        raise HTTPException(status_code=400, detail="Invalid credential")

    try:
        cred_id_bytes = base64url_to_bytes(cred_id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid credential encoding")

    creds = mgr.get_webauthn_credentials("admin")
    cred_match = next((c for c in creds if c["id"] == cred_id_bytes), None)
    if not cred_match:
        raise HTTPException(status_code=400, detail="Credential not found")

    try:
        verification = verify_authentication_response(
            credential=body,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            credential_public_key=base64.b64decode(cred_match["public_key"]),
            credential_current_sign_count=cred_match["sign_count"],
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    mgr.update_webauthn_sign_count(cred_match["id"], verification.new_sign_count)
    webauthn_challenges.pop("login", None)

    session_token = secrets.token_hex(32)
    mgr.create_auth_session(session_token)
    return {"token": session_token}


@app.get("/api/metrics/{container_name:path}")
async def get_container_metrics(container_name: str, hours: int = 24):
    mgr = StateManager(STATE_DB)
    return mgr.get_metrics(container_name, hours)


@app.get("/api/containers")
async def get_containers():
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{json .}}"], capture_output=True, text=True
    )
    return [json.loads(line) for line in result.stdout.strip().splitlines() if line]


@app.post("/api/run")
async def trigger_run(force: bool = False):
    log_event(f"Manual monitor check triggered (Force cache bypass: {force})", "API")
    try:
        monitor = Monitor(force=force, on_update=broadcast_event)
        await asyncio.to_thread(monitor.run)
        return {"exit_code": 0, "output": "Monitoring completed successfully"}
    except Exception as e:
        return {"exit_code": 1, "output": str(e)}


@app.post("/api/update/{container_name:path}")
async def update_container(container_name: str):
    log_event(f"Pull & Recreate requested for container: {container_name}", "API")
    inspect = subprocess.run(
        [
            "docker",
            "inspect",
            "--format",
            '{{index .Config.Labels "com.docker.compose.project.working_dir"}}',
            container_name,
        ],
        capture_output=True,
        text=True,
    )
    working_dir = inspect.stdout.strip()
    from backend.monitor import execute_compose_update, execute_python_update

    fallback_needed = False
    output = ""
    if working_dir:
        try:
            output = await asyncio.to_thread(
                execute_compose_update, working_dir, container_name
            )
        except Exception as e:
            log_event(
                f"Compose update failed for {container_name}: {e}. Falling back to native SDK update.",
                "WARNING",
            )
            fallback_needed = True
    else:
        fallback_needed = True

    if fallback_needed:
        try:
            output = await asyncio.to_thread(execute_python_update, container_name)
        except Exception as e:
            log_event(f"Update failed for {container_name}: {e}", "ERROR")
            return {"exit_code": 1, "output": str(e), "error": str(e)}

    log_event(f"Successfully updated {container_name}", "GOOD")
    return {"exit_code": 0, "output": output}


@app.post("/api/prune")
async def prune_system():
    log_event("System cleanup (prune -a) triggered via Web UI", "API")
    proc = await asyncio.create_subprocess_exec(
        "docker",
        "system",
        "prune",
        "-af",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    output_str = out.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        log_event(
            f"Prune failed! Docker daemon returned: {output_str.strip()}", "ERROR"
        )
    else:
        log_event("System prune completed successfully.", "GOOD")
    return {"exit_code": proc.returncode, "output": output_str}


@app.post("/api/containers/{action}/{container_name:path}")
async def control_container(action: str, container_name: str):
    if action not in ["start", "stop", "restart"]:
        raise HTTPException(400, "Invalid action")

    log_event(f"Command '{action}' sent to container: {container_name}", "API")
    proc = await asyncio.create_subprocess_exec(
        "docker",
        action,
        container_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return {
            "exit_code": proc.returncode,
            "error": out.decode("utf-8", errors="replace"),
        }
    return {"exit_code": 0, "output": out.decode("utf-8", errors="replace").strip()}


@app.get("/api/logs")
async def get_monitor_log(lines: int = 200):
    if not LOG_F.exists():
        return {"lines": []}
    return {"lines": LOG_F.read_text().splitlines()[-lines:]}


@app.get("/api/config")
def get_config():
    try:
        with open(CONFIG_F, "r") as f:
            return PlainTextResponse(f.read())
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/config/json")
def get_config_json():
    try:
        with open(CONFIG_F, "r") as f:
            return yaml.safe_load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/api/config")
async def update_config(request: Request):
    try:
        body = await request.body()
        yaml_str = body.decode("utf-8")
        parsed_yaml = yaml.safe_load(yaml_str)
        AppConfig(**parsed_yaml)

        with open(CONFIG_F, "w") as f:
            f.write(yaml_str)

        new_interval = int(
            parsed_yaml.get("general", {}).get("monitor_interval_minutes", 360)
        )
        scheduler.reschedule_job(
            "monitor", trigger=IntervalTrigger(minutes=new_interval)
        )
        log_event(
            f"Success: Rescheduled background monitor to run every {new_interval} minutes.",
            "API",
        )
        return {"status": "saved"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/config/json")
async def update_config_json(request: Request):
    try:
        data = await request.json()
        AppConfig(**data)

        with open(CONFIG_F, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        new_interval = int(data.get("general", {}).get("monitor_interval_minutes", 360))
        scheduler.reschedule_job(
            "monitor", trigger=IntervalTrigger(minutes=new_interval)
        )
        log_event(
            f"Success: Rescheduled background monitor to run every {new_interval} minutes.",
            "API",
        )
        return {"status": "saved"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/container-logs/{container_name:path}")
async def container_logs(container_name: str, filter: str = ""):
    out = get_container_logs(container_name, filter)
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
                disk_info = {
                    "size": parts[1],
                    "used": parts[2],
                    "percent": parts[4],
                    "fs": fs,
                }
    except Exception:
        pass
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
                mem_info = {
                    "total": f"{total}MB",
                    "used": f"{used}MB",
                    "percent": f"{percent}%",
                }
    except Exception:
        pass
    cpu_load = "0.00"
    try:
        with open("/proc/loadavg", "r") as f:
            cpu_load = f.read().split()[0]
    except Exception:
        pass
    return {"disk": disk_info, "memory": mem_info, "cpu_load": cpu_load}


@app.get("/health")
def health_check():
    return {"status": "healthy"}


app.mount("/", StaticFiles(directory="/app/frontend", html=True), name="frontend")
