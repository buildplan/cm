# 1: Builder Stage
FROM alpine:3.23 AS builder

# Install build-time dependencies
RUN apk add --no-cache python3 py3-pip curl

# Create a python virtual environment & install packages
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip3 install --no-cache-dir fastapi uvicorn apscheduler

# Download yq
ARG TARGETARCH=amd64
RUN curl -fsSL "https://github.com/mikefarah/yq/releases/latest/download/yq_linux_${TARGETARCH}" -o /yq \
    && chmod +x /yq

# 2: Final Image
FROM alpine:3.23

# Install runtime dependencies
RUN apk add --no-cache \
    bash jq skopeo curl gawk coreutils docker-cli docker-cli-compose tzdata \
    python3 py3-yaml

# Copy the virtual environment and yq from the builder stage
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /yq /usr/local/bin/yq

ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Copy application files
COPY container-monitor.sh .
COPY backend/ ./backend/
COPY frontend/ ./frontend/

RUN chmod +x /app/container-monitor.sh && mkdir -p /app/data

EXPOSE 9000
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "9000", "--workers", "1"]
