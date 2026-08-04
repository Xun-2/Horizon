#!/usr/bin/env bash
# Horizon daily run + deploy to GitHub Pages
# Usage: ./scripts/daily-run.sh
# Cron:  0 8 * * * /path/to/horizon/scripts/daily-run.sh >> /path/to/horizon/logs/cron.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LOG_PREFIX="[$(date '+%Y-%m-%d %H:%M:%S')]"

cd "$PROJECT_DIR"

echo "$LOG_PREFIX Starting Horizon daily run..."

# 1. Pull latest code
git pull --quiet origin main

# 2. Install/update dependencies
uv sync --quiet

# 3. Run Horizon
uv run horizon --hours 24

# 4. Deploy docs to gh-pages
echo "$LOG_PREFIX Deploying to gh-pages..."

# Use a temporary worktree to update gh-pages without switching branches
TMPDIR=$(mktemp -d)
cleanup() {
    cd "$PROJECT_DIR"
    git worktree remove --force "$TMPDIR" 2>/dev/null || rm -rf "$TMPDIR"
}
trap cleanup EXIT

git worktree prune
git fetch --quiet origin gh-pages

git worktree add --detach "$TMPDIR" origin/gh-pages
cp -r docs/* "$TMPDIR/"

cd "$TMPDIR"
git add -A
git commit -m "Daily Summary: $(date '+%Y-%m-%d')" || { echo "$LOG_PREFIX Nothing to commit."; exit 0; }
git push origin HEAD:gh-pages

echo "$LOG_PREFIX Done."
