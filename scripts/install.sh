#!/usr/bin/env bash
# One-shot installer for a VPS.
# Usage:  curl -fsSL <raw-url>/scripts/install.sh | bash
set -euo pipefail

REPO_URL="${AETHER_REPO_URL:-https://github.com/expvibelab/finance-dashboard.git}"
DEST="${AETHER_DEST:-$HOME/aether}"

echo "→ cloning to $DEST"
if [ -d "$DEST/.git" ]; then
  git -C "$DEST" pull --rebase
else
  git clone "$REPO_URL" "$DEST"
fi
cd "$DEST"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "→ created .env from .env.example — edit it before launching"
fi

if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  echo "→ building docker image"
  docker compose build
  echo "→ done. Edit .env, then run:  docker compose up -d"
else
  echo "Docker Compose not detected. Install with:  curl -fsSL https://get.docker.com | sh"
  exit 1
fi
