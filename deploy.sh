#!/usr/bin/env bash
set -Eeuo pipefail

# Full update + deployment script for pi.lot.
# Usage:
#   ./deploy.sh
#
# If this script is run from inside a pi.lot checkout, that checkout is updated.
# If this script is run elsewhere, the repo is cloned into ./pi.lot by default.
#
# Optional overrides:
#   REPO_URL=https://github.com/oliverruoff/pi.lot.git APP_DIR=/opt/pi.lot ./deploy.sh

REPO_URL="${REPO_URL:-https://github.com/oliverruoff/pi.lot.git}"
BRANCH="${BRANCH:-main}"
IMAGE_NAME="${IMAGE_NAME:-pi-lot}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
CONTAINER_NAME="${CONTAINER_NAME:-pi-lot}"
RESTART_POLICY="${RESTART_POLICY:-unless-stopped}"
STOP_TIMEOUT="${STOP_TIMEOUT:-30}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -z "${APP_DIR:-}" ]; then
  if [ -d "$SCRIPT_DIR/.git" ] || [ -f "$SCRIPT_DIR/Dockerfile" ]; then
    APP_DIR="$SCRIPT_DIR"
  else
    APP_DIR="$SCRIPT_DIR/pi.lot"
  fi
fi

if [ -z "${ENV_FILE:-}" ]; then
  if [ -f "$APP_DIR/.env" ]; then
    ENV_FILE="$APP_DIR/.env"
  elif [ -f "$SCRIPT_DIR/.env" ]; then
    ENV_FILE="$SCRIPT_DIR/.env"
  else
    ENV_FILE="$APP_DIR/.env"
  fi
fi

WORKSPACE_DIR="${WORKSPACE_DIR:-$APP_DIR/workspace}"
BACKUP_DIR="${BACKUP_DIR:-$APP_DIR/backups}"
BACKUP_ENABLED="${BACKUP_ENABLED:-true}"
DOCKER_RUN_ARGS="${DOCKER_RUN_ARGS:-}"

log() { printf '\n[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
fail() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"; }

need git
need docker

if [ ! -d "$APP_DIR/.git" ]; then
  if [ -e "$APP_DIR" ] && [ "$(find "$APP_DIR" -mindepth 1 -maxdepth 1 2>/dev/null | head -n 1)" ]; then
    fail "$APP_DIR exists but is not a git checkout and is not empty. Set APP_DIR to an empty/new directory, e.g. APP_DIR=$SCRIPT_DIR/pi.lot ./deploy.sh"
  fi
  log "Cloning $REPO_URL into $APP_DIR"
  mkdir -p "$(dirname "$APP_DIR")"
  git clone --branch "$BRANCH" "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"

log "Updating repository in $APP_DIR"
git fetch origin "$BRANCH"
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

[ -f "$ENV_FILE" ] || fail "Env file not found: $ENV_FILE. Create it from .env.example and add TELEGRAM_BOT_TOKEN/API keys."
mkdir -p "$WORKSPACE_DIR"

if grep -Eq '^PILOT_DATA_DIR=/data(/|$)?' "$ENV_FILE"; then
  log "WARNING: $ENV_FILE sets PILOT_DATA_DIR=/data, but this script mounts $WORKSPACE_DIR to /workspace. Change PILOT_DATA_DIR to /workspace/data or mount /data too."
fi

if [ "$BACKUP_ENABLED" = "true" ]; then
  mkdir -p "$BACKUP_DIR"
  BACKUP_FILE="$BACKUP_DIR/${CONTAINER_NAME}-workspace-$(date '+%Y%m%d-%H%M%S').tar.gz"
  log "Backing up workspace to $BACKUP_FILE"
  tar -czf "$BACKUP_FILE" -C "$WORKSPACE_DIR" .
fi

log "Building Docker image ${IMAGE_NAME}:${IMAGE_TAG}"
docker build --pull -t "${IMAGE_NAME}:${IMAGE_TAG}" "$APP_DIR"

if docker ps -a --format '{{.Names}}' | grep -Fxq "$CONTAINER_NAME"; then
  log "Stopping existing container $CONTAINER_NAME"
  docker stop --time "$STOP_TIMEOUT" "$CONTAINER_NAME" >/dev/null || true
  log "Removing existing container $CONTAINER_NAME"
  docker rm "$CONTAINER_NAME" >/dev/null || true
fi

log "Starting new container $CONTAINER_NAME"
# shellcheck disable=SC2086 # DOCKER_RUN_ARGS is intentionally word-split for optional extra docker args.
docker run -d \
  --name "$CONTAINER_NAME" \
  --restart "$RESTART_POLICY" \
  --env-file "$ENV_FILE" \
  -v "$WORKSPACE_DIR:/workspace" \
  $DOCKER_RUN_ARGS \
  "${IMAGE_NAME}:${IMAGE_TAG}"

log "Deployment complete"
docker ps --filter "name=^/${CONTAINER_NAME}$"
