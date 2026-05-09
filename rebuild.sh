#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -gt 0 ]; then
  SERVICES=("$@")
else
  SERVICES=(backend worker frontend)
fi

cd "$ROOT_DIR"

docker compose up -d --build "${SERVICES[@]}"
docker compose ps "${SERVICES[@]}"
