# 1: Builder Stage
FROM alpine:3.24@sha256:a2d49ea686c2adfe3c992e47dc3b5e7fa6e6b5055609400dc2acaeb241c829f4 AS builder

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

# 2: Final Image
FROM alpine:3.24@sha256:a2d49ea686c2adfe3c992e47dc3b5e7fa6e6b5055609400dc2acaeb241c829f4

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

# hadolint ignore=DL3018
RUN apk upgrade --no-cache && apk add --no-cache \
    dumb-init docker-cli docker-cli-compose tzdata python3

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

COPY backend/ ./backend/
COPY frontend/ ./frontend/

ARG APP_VERSION=dev

# hadolint ignore=DL3059
RUN sed -i "s/const APP_VERSION = .*/const APP_VERSION = \"${APP_VERSION}\";/" /app/frontend/app.js && \
    mkdir -p /app/data

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python3 -c "import sys, urllib.request; sys.exit(0) if urllib.request.urlopen('http://127.0.0.1:9000/health', timeout=8).getcode() == 200 else sys.exit(1)" > /dev/null 2>&1 || exit 1

EXPOSE 9000
CMD ["dumb-init", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "9000", "--workers", "1", "--no-access-log"]
