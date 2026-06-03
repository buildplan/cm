# Container Monitor

Container Monitor is a lightweight, secure, and fully containerized web application for tracking, managing, and automatically updating Docker containers. It provides a web interface for daily administration and an efficient Python-based background engine.

## Features

* **Real-Time Dashboard:** View host system utilization and live container status. Updates are pushed instantly to the UI via Server-Sent Events (SSE) without polling overhead.
* **Full Lifecycle Controls:** Manage containers (Start, Stop, Restart, Pull, Recreate) directly from the web interface.
* **Automated Updates:** Configurable auto-update engine that queries the Docker Registry V2 API to pull new images and recreate containers based on tag strategies (`latest`, digest matching, or semver).
* **Resource Monitoring:** Tracks CPU, memory, disk space, and network errors directly via the native Docker API for maximum performance.
* **Live Configuration UI:** Edit settings through a Visual UI or a raw YAML editor. The Pydantic-validated backend catches errors instantly and reschedules background tasks on the fly—no container restarts required.
* **Log Viewer:** Access application logs and follow live container logs with dynamic filtering, mirroring `docker logs -f` directly in your browser.
* **Notifications:** Supports alerts via Discord webhooks, Ntfy, or generic JSON webhooks.
* **Security First:** Operates behind a Docker Socket Proxy (read-only where possible). Features Bearer token authentication and uses `dumb-init` to securely eradicate zombie processes.

## Architecture

* **Backend:** Python (FastAPI, APScheduler, custom Docker Registry V2 client).
* **Frontend:** Vanilla JavaScript, Tailwind CSS, SVG icons, and SSE reactivity (no heavy build tools).
* **Base Image:** Alpine Linux (Multi-stage build). Optimized with `dumb-init` acting as PID 1.

## Deployment

The recommended deployment method utilizes Docker Compose and a Docker Socket Proxy to restrict the monitor's access to the host daemon.

### 1. Prepare Host Directory

Create a directory for persistent data and ensure the user running the container has ownership, as the container will map permissions to the host.

```bash
mkdir -p ./data
```

### 2. Docker Compose Configuration

Create a `docker-compose.yml` file.

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
      - /opt/docker:/opt/docker # Map to your local compose directories
      # Prevent Docker Hub limits and for private registries, log in on the host system with `docker login`
      - ~/.docker/config.json:/root/.docker/config.json:ro
    environment:
      # System Configuration
      - DOCKER_HOST=tcp://dockerproxy:2375
      - DATA_DIR=/app/data
      - HOST_DISK_CHECK_FILESYSTEM=/hostfs
      - CONTAINER_MODE=true
      - TZ=Europe/London
      - SECRET_TOKEN=your_secure_password_here

      # Optional Configuration Seeds (Populates config.yml on first boot)
      - MONITOR_INTERVAL_MINUTES=360
      - UPDATE_CHECK_CACHE_HOURS=6
      - CPU_WARNING_THRESHOLD=80
      - MEMORY_WARNING_THRESHOLD=80
      - DISK_SPACE_THRESHOLD=80

      # Notifications
      - NOTIFICATION_CHANNEL=none # Options: discord, ntfy, generic, none
      - NOTIFY_ON=Updates,Logs,Status,Restarts,Resources
      - DISCORD_WEBHOOK_URL=
      - NTFY_SERVER_URL=https://ntfy.sh
      - NTFY_TOPIC=
      - NTFY_ACCESS_TOKEN=
      - NTFY_PRIORITY=3

      # Container Filters & Updates
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

## Configuration

The application uses a two-tier configuration system.

1. **Environment Variables (Initialization):** When the container boots for the first time, it reads the environment variables from compose file and generates a structured `config.yml` in the mapped `./data` directory. It also auto-discovers currently running containers.
2. **Live UI Configuration (Runtime):** Once generated, `config.yml` becomes the source of truth. You can easily modify settings via the web UI's **Visual Editor** or the advanced **YAML Editor**. Thanks to backend Pydantic validation, syntax errors are caught instantly, and background monitoring schedules are updated live without ever needing to restart the container.

## Security Notes

* **Docker Socket:** Avoid mounting `/var/run/docker.sock` directly into the `container-monitor` container. Using the `linuxserver/socket-proxy` limits the attack surface by only exposing necessary API endpoints over TCP.
* **Authentication:** The web UI is protected by a Bearer token mechanism. Set a strong `SECRET_TOKEN` in your environment variables. Without this token, the API will return HTTP 401 Unauthorized.
* **Compose Paths:** The `working_dir` of your containers must be mapped identically inside the `container-monitor` container (e.g., `/opt/docker:/opt/docker`) so the Python engine can correctly execute `docker compose pull` and `up -d` commands during auto-update cycles.
