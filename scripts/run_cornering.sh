#!/usr/bin/env bash
set -e
R="$(cd "$(dirname "$0")/.." && pwd)"
python3 - <<PY
from pathlib import Path
import yaml
p=Path("$R/config/parameters.yaml"); d=yaml.safe_load(p.read_text()); d['flow']['yawAngle']=10.0; d['geometry']['steeringAngle']=20.0; d['geometry']['rollAngle']=3.0; p.write_text(yaml.safe_dump(d,sort_keys=False))
PY
"$R/scripts/run_straight.sh" demo "${1:-quick}" "${2:-reference}"
