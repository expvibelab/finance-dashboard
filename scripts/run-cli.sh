#!/usr/bin/env bash
# Spawn a one-off REPL against the live container's data volume.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose run --rm aether aether chat --project /app
