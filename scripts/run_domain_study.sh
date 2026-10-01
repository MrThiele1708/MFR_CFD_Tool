#!/usr/bin/env bash
set -e
R="$(cd "$(dirname "$0")/.." && pwd)"
for d in small reference large; do echo "=== domain $d ==="; "$R/scripts/run_straight.sh" demo "${1:-balanced}" "$d"; done
