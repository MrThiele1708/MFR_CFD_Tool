#!/usr/bin/env python3
import os
from pathlib import Path
import yaml,json
r=Path(__file__).resolve().parents[1]; c=yaml.safe_load((Path(os.environ.get("CFD_CONFIG", str(r / "config/parameters.yaml")))).read_text()); d=r/c['project']['case']; d.mkdir(exist_ok=True); (d/'effective.json').write_text(json.dumps(c,indent=2)); print('effective config written')
