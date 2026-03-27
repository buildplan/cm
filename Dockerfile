FROM alpine:3.19

# Install dependencies including python, docker cli, skopeo
RUN apk add --no-cache \
    bash jq skopeo curl gawk coreutils docker-cli \
    python3 py3-pip py3-yaml \
    && rm -rf /usr/lib/python3.*/EXTERNALLY-MANAGED \
    && pip3 install --no-cache-dir fastapi uvicorn apscheduler

# Install yq
ARG TARGETARCH=amd64
RUN curl -fsSL "https://github.com/mikefarah/yq/releases/latest/download/yq_linux_${TARGETARCH}" -o /usr/local/bin/yq \
    && chmod +x /usr/local/bin/yq

WORKDIR /app

# Copy application files
COPY container-monitor.sh .
COPY backend/ ./backend/
COPY frontend/ ./frontend/

RUN chmod +x /app/container-monitor.sh && mkdir -p /app/data

EXPOSE 9000
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "9000", "--workers", "1"]
