# Container Monitor

Container Monitor is a lightweight, secure, and fully containerized web application designed to monitor, update, and manage Docker containers. It features a modern, responsive web dashboard with real-time updates and an efficient Python-based background engine.

By default, the application is designed to run behind a Docker Socket Proxy (e.g., `linuxserver/socket-proxy`) to limit the attack surface by only exposing necessary read/write endpoints over TCP rather than mounting the raw Docker socket directly.

---

## Key Features

* **Real-Time SSE Broadcasts:** Instant updates for container statuses and host system metrics are pushed directly to the UI via Server-Sent Events (SSE) instead of aggressive client-side polling.
* **SQLite State & Metrics Manager:** Powered by SQLite in WAL (Write-Ahead Logging) mode. It keeps a history of general container statuses, updates, and records 24 hours of time-series CPU and Memory utilization.
* **WebAuthn / Passkey Authentication:** Secure your monitor with modern biometric or hardware security keys (e.g., TouchID, FaceID, YubiKey). Once registered, password/token authentication can be fully disabled.
* **Dynamic Sibling Container Updates:** Execute pulls and updates via `docker compose` in the compose directory. If the compose file directory is not locally mounted inside the app's container, it automatically spins up an ephemeral `docker:cli` sibling container to perform the pull and recreate actions safely on the host daemon.
* **Live Configuration UI:** Edit the configuration directly from the UI using either the Visual Editor or raw YAML Editor. The backend validates edits against strict Pydantic schemas and reschedules background check timers instantly—no container restarts required.
* **Log Viewer & Scanner:** View application logs or stream container stdout/stderr live with regex-based filter support, mirroring `docker logs -f` inside the browser.
* **Multi-Channel Notifications:** Alerts via Discord, Ntfy (with access tokens & priority control), or generic HTTP POST webhooks.
* **Zero-Bloat Alpine Container:** A minimal security footprint utilizing an Alpine Linux base image with `dumb-init` as PID 1 to prevent zombie processes.

---

## Architecture

* **Backend:** FastAPI (Python), APScheduler, Python Docker SDK, and a custom native HTTP OCI registry client.
* **Frontend:** Single-page app using Vanilla JS, Tailwind CSS, CSS animations, and SSE. No Node.js build tools.
* **Database:** SQLite (operating in WAL mode) stored in `/app/data/monitor_state.db`.

---

## Deployment

The recommended deployment method utilizes Docker Compose and a Docker Socket Proxy to restrict access to the host daemon.

### 1. Prepare Host Directory

Create a directory for persistent data and ensure the user running the container has ownership:

```bash
mkdir -p ./data
```

### 2. Docker Compose Configuration

Create a `docker-compose.yml` file. This config includes the Docker Socket Proxy configured to safely support monitoring, compose recreates, and system prunes.

```yaml
services:
  dockerproxy:
    image: lscr.io/linuxserver/socket-proxy:latest
    container_name: dockerproxy
    restart: unless-stopped
    environment:
      # Required for basic tracking
      - CONTAINERS=1 # Allow listing, inspecting, and reading logs
      - IMAGES=1     # Allow pulling images and checking digests
      - INFO=1       # Allow 'docker info' for daemon connection checks

      # Required for app actions
      - POST=1       # Allow POST operations (Start, Stop, Restart, Pull, Recreate)
      - EXEC=1       # Allow 'docker exec' for container disk/network stats gathering
      - SYSTEM=1     # Allow 'docker system prune' for the UI cleanup button

      # Required for compose recreation
      - NETWORKS=1   # Needed for compose to attach containers to networks
      - VOLUMES=1    # Needed for compose to attach existing volumes
      - BUILD=1      # Allows clearing the docker build cache
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    read_only: true
    tmpfs:
      - /run

  container-monitor:
    image: ghcr.io/buildplan/cm:latest
    container_name: container-monitor
    hostname: myserver
    restart: unless-stopped
    depends_on:
      - dockerproxy
    ports:
      - "9000:9000"
    volumes:
      - /:/hostfs:ro
      - ./data:/app/data
      # Map to your local compose directories so compose can recreate containers locally
      - /opt/docker:/opt/docker
      # Map host docker config for private registries or Docker Hub rate-limit prevention
      - ~/.docker/config.json:/root/.docker/config.json:ro
    environment:
      # --- System Configuration ---
      - DOCKER_HOST=tcp://dockerproxy:2375
      - DATA_DIR=/app/data
      - HOST_DISK_CHECK_FILESYSTEM=/hostfs
      - CONTAINER_MODE=true
      - TZ=Europe/London
      - SECRET_TOKEN=your_secure_password_here # Set a strong login password

      # --- Optional Configuration Seeds ---
      # (These seed config.yml on the very first boot of the container)
      - MONITOR_INTERVAL_MINUTES=360
      - UPDATE_CHECK_CACHE_HOURS=6
      - CPU_WARNING_THRESHOLD=80
      - MEMORY_WARNING_THRESHOLD=80
      - DISK_SPACE_THRESHOLD=80
      - NETWORK_ERROR_THRESHOLD=10
      - LOG_LINES_TO_CHECK=40

      # --- External Health Check ---
      - HEALTHCHECKS_JOB_URL=
      - HEALTHCHECKS_FAIL_ON=Status,Restarts,Resources,Disk,Network,Updates,Logs

      # --- Notifications ---
      - NOTIFICATION_CHANNEL=none # Options: discord, ntfy, generic, none
      - NOTIFY_ON=Updates,Logs,Status,Restarts,Resources
      - DISCORD_WEBHOOK_URL=
      - GENERIC_WEBHOOK_URL=
      - NTFY_SERVER_URL=https://ntfy.sh
      - NTFY_TOPIC=
      - NTFY_ACCESS_TOKEN=
      - NTFY_PRIORITY=3
      - NTFY_ICON_URL=
      - NTFY_CLICK_URL=

      # --- Container Filters & Auto-Updates ---
      - EXCLUDE_UPDATES=my-local-app-1,my-backend-api
      - LOG_ERROR_PATTERNS=Exception,SEVERE,Traceback,panic,fatal
      - AUTO_UPDATE_ENABLED=false
      - AUTO_UPDATE_TAGS=latest,stable,main
      - AUTO_UPDATE_EXCLUDE=postgres,redis,mongo
```

### 3. Start the Service

```bash
docker compose up -d
```

Access the web interface at `http://<your-host-ip>:9000` and log in using the `SECRET_TOKEN` defined in your compose file.

---

## Configuration System

Container Monitor uses a two-tier configuration system:

1. **Environment Variables (Initialization):** On the very first boot, the application reads the compose file's environment variables to auto-discover containers and generate a structured `/app/data/config.yml` configuration file.
2. **Live UI Configuration (Runtime):** Once generated, `/app/data/config.yml` becomes the single source of truth. Any edits made via the web UI's **Visual Settings Panel** or the **YAML Editor** are saved directly to this file, validated by Pydantic models on the backend, and applied immediately without restarting the container.

---

## Security Hardening

### Docker Socket Proxy

Directly mounting `/var/run/docker.sock` exposes your system to root access vulnerabilities. By routing requests through `linuxserver/socket-proxy`, the container is only allowed to access specific API endpoints. The recommended compose file restricts access to listing containers, checking images, running container commands, and running `system prune` actions, while blocking access to host network configuration or system-level sockets.

### Passkey Authentication (WebAuthn)

You can register biometrics (Windows Hello, FaceID, TouchID) or hardware security keys (YubiKeys) from the settings panel.
1. Log in to the UI with your `SECRET_TOKEN`.
2. Go to the Settings panel and click **Register Passkey**.
3. Follow your browser's prompts to save your passkey.
4. (Optional) Once a passkey is registered, you can disable traditional token-based logins from settings in the UI or by opening the Settings YAML editor and setting:

   ```yaml
   auth:
     disable_token_auth: true
   ```
   *Note: If no passkeys are registered, token auth remains enabled as a safety fallback.*

### Bounded Log Rotation
The application monitors its log files and automatically trims them to prevent disk depletion. When `/app/data/container-monitor.log` exceeds 10MB, the file is automatically rotated and truncated to its last 1MB of log history.
