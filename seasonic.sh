#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec docker compose -f "$SCRIPT_DIR/docker/docker-compose.yml" run --rm seasonic
