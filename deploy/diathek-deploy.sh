#!/usr/bin/env bash
# Deploy script for diathek — triggered by systemd path unit.
# Runs as root (needs to restart the service), drops to DIATHEK_USER for app commands.
set -euo pipefail

DIATHEK_DIR="${DIATHEK_DIR:-/usr/share/webapps/diathek}"
DIATHEK_USER="${DIATHEK_USER:-diathek}"
FLAG_FILE="${DIATHEK_DEPLOY_FLAG_FILE:-$DIATHEK_DIR/data/deploy.flag}"
LOG_TAG="diathek-deploy"

log() { logger -t "$LOG_TAG" "$@"; echo "[$(date -Is)] $*"; }

# Remove flag immediately so we don't re-trigger
rm -f "$FLAG_FILE"

log "Deploy started"

cd "$DIATHEK_DIR"

log "Running git pull"
sudo -u "$DIATHEK_USER" git pull --ff-only

log "Running uv sync"
sudo -u "$DIATHEK_USER" uv sync

log "Running migrations"
sudo -u "$DIATHEK_USER" uv run python src/manage.py migrate --noinput

log "Collecting static files"
sudo -u "$DIATHEK_USER" uv run python src/manage.py collectstatic --noinput

log "Restarting diathek service"
systemctl restart diathek

log "Deploy completed"
