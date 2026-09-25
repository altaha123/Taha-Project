#!/usr/bin/env bash
# Idempotent bootstrap for the Altaha Screener development environment.
# Runs after the repository is checked out. Safe to run repeatedly.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV="$REPO_ROOT/.venv"
PW_DIR="$HOME/portfolio-browser"

echo "==> Ensuring python venv support is present"
if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
  sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-venv
fi

echo "==> Creating / updating the Python virtual environment"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip

echo "==> Installing backend dependencies"
pip install -r backend/requirements.txt
# Test-only tools kept out of requirements.txt (and therefore the deployed
# image); starlette's TestClient needs httpx to start.
pip install pytest httpx

echo "==> Compiling every backend module (catches syntax errors)"
python -m compileall -q backend research

echo "==> Installing Playwright + Chromium for the frontend browser tests"
# Kept in a persistent location (home dir) so it survives across boots. The
# repo's browser tests read NODE_PATH; a symlink into /tmp keeps the CI-style
# invocation (NODE_PATH=/tmp/portfolio-browser/node_modules) working too.
npm install --prefix "$PW_DIR" playwright@1.58.2
"$PW_DIR/node_modules/.bin/playwright" install --with-deps chromium

echo "==> install.sh complete"
