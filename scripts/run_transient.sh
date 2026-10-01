#!/usr/bin/env bash
set -e
R="$(cd "$(dirname "$0")/.." && pwd)"
echo "Transient template: change solver application/control settings after steady validation."
"$R/scripts/run_straight.sh" demo "${1:-quick}" reference
