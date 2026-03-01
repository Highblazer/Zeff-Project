#!/bin/bash
# ============================================================
# Zeff.bot Fleet — Automated GitHub Backup
# ============================================================
# Commits and pushes all tracked code to GitHub.
# Excludes secrets, state files, and logs via .gitignore.
#
# Usage:
#   ./backup_to_github.sh           # Auto-commit and push
#   ./backup_to_github.sh --local   # Commit only, no push
#
# Cron (daily at 02:00 SAST):
#   0 2 * * * /root/.openclaw/workspace/backup_to_github.sh >> /root/.openclaw/workspace/logs/backup.log 2>&1
# ============================================================

set -euo pipefail

WORKSPACE="/root/.openclaw/workspace"
BRANCH="master"
LOG_FILE="$WORKSPACE/logs/backup.log"
# Load PAT from .env (GITHUB_TOKEN=...) or environment
if [ -f "$WORKSPACE/.env" ]; then
    GITHUB_PAT=$(grep "^GITHUB_TOKEN=" "$WORKSPACE/.env" 2>/dev/null | cut -d'=' -f2-)
fi
GITHUB_PAT="${GITHUB_PAT:-$GITHUB_TOKEN}"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

cd "$WORKSPACE"

# Safety: ensure .gitignore excludes secrets
if ! grep -q "^\.env$" .gitignore 2>/dev/null; then
    log "ERROR: .gitignore missing .env exclusion — refusing to backup"
    exit 1
fi

# Stage all tracked and new files (respects .gitignore)
git add -A

# Check if there are changes to commit
if git diff --cached --quiet 2>/dev/null; then
    log "No changes to backup"
    exit 0
fi

# Commit with timestamp
TIMESTAMP=$(date '+%Y-%m-%d %H:%M')
git commit -m "Auto-backup $TIMESTAMP" --quiet

log "Committed: Auto-backup $TIMESTAMP"

# Push unless --local flag
if [[ "${1:-}" == "--local" ]]; then
    log "Local-only mode — skipping push"
    exit 0
fi

# Push using PAT
if git push "https://${GITHUB_PAT}@github.com/Highblazer/Zeff-Project.git" "$BRANCH" --quiet 2>&1; then
    log "Pushed to GitHub successfully"
else
    log "ERROR: Push to GitHub failed"
    exit 1
fi

# Also create a local timestamped backup of critical state files
BACKUP_DIR="/root/backup/fleet-snapshots/$(date '+%Y-%m-%d')"
mkdir -p "$BACKUP_DIR"
cp -f "$WORKSPACE"/employees/*_state.json "$BACKUP_DIR/" 2>/dev/null || true
cp -f "$WORKSPACE"/employees/*_status.json "$BACKUP_DIR/" 2>/dev/null || true
cp -f "$WORKSPACE"/.env "$BACKUP_DIR/env.backup" 2>/dev/null || true

# Rotate old snapshots (keep 14 days)
find /root/backup/fleet-snapshots/ -maxdepth 1 -type d -mtime +14 -exec rm -rf {} \; 2>/dev/null || true

log "Backup complete — code on GitHub, state snapshot in $BACKUP_DIR"
