#!/usr/bin/env python3
import os
from pathlib import Path
import yaml
r=Path(__file__).resolve().parents[1]; d=r/'case/system/snappyHexMeshDict'; txt=d.read_text(); m=yaml.safe_load((Path(os.environ.get("CFD_MANIFEST", str(r / "config/geometryManifest.yaml")))).read_text()); names=[s['patch'] for s in m['parts'].values() if s.get('include',True)]; layers=' '.join(f'"{x}.*" {{ nSurfaceLayers 3; }}' for x in sorted(set(names))); d.write_text(txt.replace('layers {}','layers { '+layers+' }'))
