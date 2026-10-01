#!/usr/bin/env bash

set -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export ZSH_NAME=""

source /opt/openfoam13/etc/bashrc
set -e

if [ -f "$ROOT/.venv/bin/activate" ]; then
    source "$ROOT/.venv/bin/activate"
fi

FEATURES_ENABLED=$(python3 - <<'PY_FEATURE'
import os
import yaml

config_path = os.environ.get(
    "CFD_CONFIG",
    "config/parameters.yaml",
)

with open(config_path, encoding="utf-8") as f:
    config = yaml.safe_load(f)

enabled = config.get("mesh", {}).get(
    "features", {}
).get("enabled", False)

print(str(bool(enabled)).lower())
PY_FEATURE
)

if [ "$FEATURES_ENABLED" = "true" ]; then
    echo "=== Generating feature-edge dictionary ==="
    python3 "$ROOT/scripts/generate_surface_features.py"

    cd "$ROOT/case"

    echo "=== Running surfaceFeatures ==="
    surfaceFeatures 2>&1 | tee log.surfaceFeatures

    cd "$ROOT"

    echo "=== Applying feature-edge settings ==="
    python3 "$ROOT/scripts/apply_feature_settings.py"
else
    echo "Feature-edge extraction disabled."
fi
