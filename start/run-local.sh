#!/usr/bin/env bash
# Run the API locally on http://127.0.0.1:<port-number> (PY-D5).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export ENVIRONMENT="${ENVIRONMENT:-development}"
export SECRETS_MOUNT_PATH="${SECRETS_MOUNT_PATH:-$HOME/.pellerex/secrets/RepoUniqueNormalisedIdentifier}"

# Seed the local key-per-file secrets mount if missing/empty (same layout as the prod CSI mount).
if [ ! -d "$SECRETS_MOUNT_PATH" ] || [ -z "$(ls -A "$SECRETS_MOUNT_PATH" 2>/dev/null)" ]; then
  ./start/setup-secrets.sh
fi

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet --no-cache-dir -r requirements.txt -r requirements-dev.txt

echo "Starting uvicorn (ENVIRONMENT=$ENVIRONMENT, SECRETS_MOUNT_PATH=$SECRETS_MOUNT_PATH) on :<port-number>"
# --reload-dir app: only watch application code — without it the watcher scans the
# whole project (including .venv/) and package-file churn triggers endless reloads.
exec uvicorn app.main:app --host 0.0.0.0 --port <port-number> --reload --reload-dir app
