# 1: Builder Stage
FROM alpine:3.23@sha256:5b10f432ef3da1b8d4c7eb6c487f2f5a8f096bc91145e68878dd4a5019afde11 AS builder

RUN apk add --no-cache python3 py3-pip
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip3 install --no-cache-dir --compile fastapi uvicorn apscheduler pyyaml docker httpx
RUN pip3 uninstall -y pip setuptools \
    && find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# 2: Final Image
FROM alpine:3.23@sha256:5b10f432ef3da1b8d4c7eb6c487f2f5a8f096bc91145e68878dd4a5019afde11

RUN apk upgrade --no-cache && apk add --no-cache \
    dumb-init docker-cli docker-cli-compose tzdata python3

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY backend/ ./backend/
COPY frontend/ ./frontend/

ARG APP_VERSION=dev
RUN sed -i "s/const APP_VERSION = .*/const APP_VERSION = \"${APP_VERSION}\";/" /app/frontend/app.js

RUN mkdir -p /app/data

EXPOSE 9000
CMD ["dumb-init", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "9000", "--workers", "1", "--no-access-log"]
