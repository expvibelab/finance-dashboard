FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AETHER_HOME=/data \
    AETHER_DB_PATH=/data/state.db

# System deps: git for SDK plumbing, curl for healthchecks, ca-certs for HTTPS,
# nodejs+npm so the SDK's underlying claude-code CLI can run.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates build-essential nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Install the Claude Code CLI (the SDK shells out to it).
RUN npm install -g @anthropic-ai/claude-code

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

COPY . .

RUN mkdir -p /data && chmod 755 /data

VOLUME ["/data"]

# Default: run all configured gateways. Override with: docker run ... aether chat
CMD ["aether", "all", "--project", "/app"]
