# 1: Builder Stage
FROM alpine:3.23 AS builder

RUN apk add --no-cache python3 py3-pip
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip3 install --no-cache-dir --compile fastapi uvicorn apscheduler pyyaml
RUN pip3 uninstall -y pip setuptools \
    && find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# 2: Final Image
FROM alpine:3.23

RUN apk upgrade --no-cache && apk add --no-cache \
    bash jq yq skopeo curl docker-cli docker-cli-compose tzdata python3

COPY --from=builder /opt/venv /opt/venv

ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY container-monitor.sh .
COPY backend/ ./backend/
COPY frontend/ ./frontend/

RUN chmod +x /app/container-monitor.sh && mkdir -p /app/data

EXPOSE 9000
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "9000", "--workers", "1"]
