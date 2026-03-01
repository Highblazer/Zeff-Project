#!/bin/bash
# GitHub Backup Script
# Run manually or set up cron

REPO_DIR="/root/backup/Zeff-Project"
GIT_REPO="https://github.com/Highblazer/Zeff-Project.git"
BRANCH="main"

# Source files
SOURCE_DIR="/root/.openclaw/workspace"

# Create backup directory
mkdir -p "$REPO_DIR"

# Copy only the active files
cp $SOURCE_DIR/SOUL.md $REPO_DIR/
cp $SOURCE_DIR/AGENTS.md $REPO_DIR/
cp $SOURCE_DIR/dashboard.md $REPO_DIR/
cp $SOURCE_DIR/overnight_directive.md $REPO_DIR/
cp $SOURCE_DIR/TOOLS.md $REPO_DIR/
cp $SOURCE_DIR/USER.md $REPO_DIR/

# Copy employee files
mkdir -p $REPO_DIR/employees
cp $SOURCE_DIR/employees/*.md $REPO_DIR/employees/

# Git operations
cd "$REPO_DIR"
git add -A
git commit -m "Backup $(date '+%Y-%m-%d %H:%M')" 2>/dev/null

# Push if token available (set GITHUB_TOKEN env var)
if [ -n "$GITHUB_TOKEN" ]; then
    git push https://$GITHUB_TOKEN@github.com/Highblazer/Zeff-Project.git $BRANCH
    echo "Pushed to GitHub"
else
    echo "No GITHUB_TOKEN set - commit only"
fi

echo "Backup complete"
