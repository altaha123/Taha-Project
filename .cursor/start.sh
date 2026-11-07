#!/usr/bin/env bash
# Per-boot reconciliation. Must tolerate restarts and return promptly.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The point-in-time store, tracker ledger and delivery panels live here. In
# production this is a mounted disk (DATA_DIR=/data); locally it is a folder in
# the workspace so the data survives between runs.
mkdir -p "$REPO_ROOT/.data"

# The frontend browser tests (and CI) expect Playwright under
# /tmp/portfolio-browser. /tmp is ephemeral per boot, so re-point it at the
# persistent copy created by install.sh.
if [ -d "$HOME/portfolio-browser/node_modules" ] && [ ! -e /tmp/portfolio-browser ]; then
  ln -s "$HOME/portfolio-browser" /tmp/portfolio-browser
fi
