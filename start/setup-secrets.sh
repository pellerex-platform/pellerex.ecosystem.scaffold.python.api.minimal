#!/usr/bin/env bash
# Recreate the cluster's CSI tmpfs secret layout locally: one file per secret under
# $SECRETS_MOUNT_PATH, named after the Key Vault object (PY-D6). Reads "Name=value" lines from
# secrets.example (or the file passed as $1). This exercises the SAME code path the pod uses
# (pydantic-settings secrets_dir) — no env-var secrets.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:-$ROOT/secrets.example}"
SECRETS_MOUNT_PATH="${SECRETS_MOUNT_PATH:-$HOME/.pellerex/secrets/RepoUniqueNormalisedIdentifier}"

mkdir -p "$SECRETS_MOUNT_PATH"
chmod 700 "$SECRETS_MOUNT_PATH"

while IFS= read -r line; do
  case "$line" in
    ''|'#'*) continue ;;
  esac
  name="${line%%=*}"
  value="${line#*=}"
  printf '%s' "$value" > "$SECRETS_MOUNT_PATH/$name"
  chmod 600 "$SECRETS_MOUNT_PATH/$name"
  echo "wrote $SECRETS_MOUNT_PATH/$name"
done < "$SRC"

echo "Secrets written to $SECRETS_MOUNT_PATH (export SECRETS_MOUNT_PATH=$SECRETS_MOUNT_PATH before running the app)."
