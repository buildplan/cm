# 1: Builder Stage
FROM alpine:3.24@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6 AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# hadolint ignore=DL3018,DL3059
RUN apk add --no-cache python3 py3-pip

# hadolint ignore=DL3059
RUN python3 -m venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

# hadolint ignore=DL3013,DL3059
RUN pip3 install --no-cache-dir --compile fastapi uvicorn apscheduler pyyaml docker httpx webauthn

# hadolint ignore=DL3059
RUN pip3 uninstall -y pip setuptools \
    && find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# 1.5: Frontend Asset Builder (Tailwind CSS + Chart.js)
FROM alpine:3.24@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6 AS frontend

ARG TARGETARCH

# hadolint ignore=DL3018,DL3059
RUN apk add --no-cache wget ca-certificates libstdc++ libgcc

RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) TAILWIND_ARCH="x64"; TAILWIND_SHA256="a04d34ceacc8f52cbe8920ad846cdeb61d3d0021dba32db0d1f77c9d9fad7a6c" ;; \
      arm64) TAILWIND_ARCH="arm64"; TAILWIND_SHA256="71ea4be79c9de9827545682df3e040053fb535d37c71ed2cfdedf9385a0868e0" ;; \
      *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    wget -q -O /tmp/tailwindcss "https://github.com/tailwindlabs/tailwindcss/releases/download/v4.3.3/tailwindcss-linux-${TAILWIND_ARCH}-musl"; \
    printf '%s  /tmp/tailwindcss\n' "${TAILWIND_SHA256}" > /tmp/tailwindcss.sha256; \
    sha256sum -c /tmp/tailwindcss.sha256; \
    chmod +x /tmp/tailwindcss

WORKDIR /app

COPY frontend/ ./frontend/

# hadolint ignore=DL3059
RUN /tmp/tailwindcss -i ./frontend/app.css -o ./frontend/styles.css --minify

# hadolint ignore=DL3059
RUN wget -q -O ./frontend/chart.umd.min.js "https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js"

# 2: Final Image
FROM alpine:3.24@sha256:294b683cb724975bec92580e1e685676bd4b50bda910ddb8c51d4cabeaec77e6

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# hadolint ignore=DL3018
RUN apk upgrade --no-cache && apk add --no-cache \
    dumb-init docker-cli docker-cli-compose tzdata python3

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

COPY backend/ ./backend/
COPY frontend/index.html frontend/app.js ./frontend/
COPY --from=frontend /app/frontend/styles.css ./frontend/styles.css
COPY --from=frontend /app/frontend/chart.umd.min.js ./frontend/chart.umd.min.js

ARG APP_VERSION=dev

# hadolint ignore=DL3059
RUN sed -i "s/const APP_VERSION = .*/const APP_VERSION = \"${APP_VERSION}\";/" /app/frontend/app.js && \
    mkdir -p /app/data

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["python3", "-c", "import sys, urllib.request; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:9000/health', timeout=8).getcode() == 200 else sys.exit(1)"]

EXPOSE 9000
CMD ["dumb-init", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "9000", "--workers", "1", "--no-access-log"]
