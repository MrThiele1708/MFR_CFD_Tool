#!/usr/bin/env python3
import os
from pathlib import Path
import json
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]
config = yaml.safe_load((Path(os.environ.get("CFD_CONFIG", str(ROOT / "config/parameters.yaml")))).read_text(encoding='utf-8'))
features = config.get('mesh', {}).get('features', {}) or {}
enabled = bool(features.get('enabled', False))
level = int(features.get('level', 4))
tol = float(features.get('snapTolerance', 1.0))
niter = int(features.get('nFeatureSnapIter', 15))

p = ROOT / 'case/system/snappyHexMeshDict'
text = p.read_text(encoding='utf-8')
source_file = ROOT / 'case/system/featureSources.json'
sources = json.loads(source_file.read_text()) if source_file.exists() else {'parts': []}

if enabled:
    entries = ''.join(
        f"""
    {{
        file "{Path(name).stem}.eMesh";
        level {level};
    }}
""" for name in sources.get('parts', [])
    )
    block = 'features\n(\n' + entries + ');'
else:
    block = 'features\n(\n);'

text, n = re.subn(r'features\s*\(.*?\);', block, text, count=1, flags=re.S)
if n != 1:
    raise SystemExit('features block not found')

text = re.sub(r'explicitFeatureSnap\s+(true|false);', f'explicitFeatureSnap {str(enabled).lower()};', text, count=1)
text = re.sub(r'nFeatureSnapIter\s+[^;]+;', f'nFeatureSnapIter {niter};', text, count=1)
text = re.sub(r'(?m)^\s*tolerance\s+[^;]+;', f'    tolerance {tol};', text, count=1)
p.write_text(text, encoding='utf-8')
print('Applied feature snapping:', enabled, 'level:', level, 'tolerance:', tol, 'iterations:', niter)
