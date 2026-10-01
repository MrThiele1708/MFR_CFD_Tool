#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

unset CFD_CASE CFD_RESULTS CFD_MANIFEST
export CFD_CONFIG="$ROOT/config/parameters.yaml"

MODE="${1:-full}"

exec "$ROOT/scripts/run_case.sh" "$MODE"
