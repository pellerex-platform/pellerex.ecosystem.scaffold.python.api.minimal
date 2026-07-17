#!/usr/bin/env bash
# Build the image and run it, exposing the API on http://127.0.0.1:8890.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

IMAGE="repouniquenormalisedidentifier:local"
SECRETS_MOUNT_PATH="${SECRETS_MOUNT_PATH:-$HOME/.pellerex/secrets/RepoUniqueNormalisedIdentifier}"

docker build -t "$IMAGE" .

# Mount the local secrets dir read-only at the same path the CSI driver uses in-cluster,
# so the container reads its secret the same way (PY-D6). Run as the non-root image user.
docker run --rm -p 8890:8890 \
  -e ENVIRONMENT=development \
  -e SECRETS_MOUNT_PATH=/mnt/secrets-store \
  $( [ -d "$SECRETS_MOUNT_PATH" ] && echo "-v $SECRETS_MOUNT_PATH:/mnt/secrets-store:ro" ) \
  "$IMAGE"
