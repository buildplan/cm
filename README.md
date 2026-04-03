# Container Monitor

Container Monitor is a lightweight, containerized web application and background service for tracking, managing, and updating Docker containers. It provides a web interface for daily administration and an automated background script for monitoring container health and applying image updates.

## Features

* **Dashboard & Controls:** View host system utilization and container status. Manage container lifecycles (Start, Stop, Restart, Pull, Recreate) directly from the web interface.
* **Log Viewer:** Access application logs for the background monitor and individual container logs without requiring CLI access.
* **Automated Updates:** Configurable auto-update engine that pulls new images and recreates containers based on tag strategies (e.g., digest matching for `latest` tags or semver matching).
* **Resource Monitoring:** Tracks CPU, memory, disk space, and network errors against configurable thresholds.
* **Notifications:** Supports alerts via Discord webhooks, Ntfy, or generic JSON webhooks.
* **Healthchecks.io Integration:** Supports start/fail/up pinging for the background cron job.
* **Security:** Designed to operate behind a Docker Socket Proxy to prevent direct root socket mounting. Includes token-based authentication for the web interface.

## Architecture

* **Backend:** FastAPI (Python) and Bash.
* **Frontend:** Vanilla JavaScript, HTML, and Tailwind CSS.
* **Base Image:** Alpine Linux (Multi-stage build).

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
    environment:
      # System Configuration
      - DOCKER_HOST=tcp://dockerproxy:2375
      - DATA_DIR=/app/data
      - HOST_DISK_CHECK_FILESYSTEM=/hostfs
      - CONTAINER_MODE=true
      - TZ=Europe/London
      - SECRET_TOKEN=your_secure_password_here

      # Optional Configuration Seeds (Populates config.yml on first boot)
      - MONITOR_INTERVAL_HOURS=6
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

1. **Environment Variables (Initialization):** When the container boots for the first time, it reads the environment variables from the `docker-compose.yml` and generates a structured `config.yml` file in the mapped `./data` directory. It also queries the Docker socket to automatically populate the monitoring list with currently running containers.
2. **YAML Configuration (Runtime):** Once `config.yml` is generated, it acts as the source of truth. You can modify this file directly via the web UI's "Settings" tab. The backend includes a strict YAML linter that validates syntax before saving changes to disk.

## Security Notes

* **Docker Socket:** Avoid mounting `/var/run/docker.sock` directly into the `container-monitor` container. Using the `linuxserver/socket-proxy` limits the attack surface by only exposing necessary API endpoints.
* **Authentication:** The web UI is protected by a Bearer token mechanism. Set a strong `SECRET_TOKEN` in your environment variables. Without this token, the API will return HTTP 401 Unauthorized for all requests.
* **Compose Paths:** The `working_dir` of your containers must be mapped identically inside the `container-monitor` container (e.g., `/opt/docker:/opt/docker`) so the script can execute `docker compose pull` and `up -d` commands accurately during update cycles.
