#!/usr/bin/env python3
import os
from pathlib import Path
import json
import yaml

ROOT = Path(__file__).resolve().parents[1]
config = yaml.safe_load((Path(os.environ.get("CFD_CONFIG", str(ROOT / "config/parameters.yaml")))).read_text(encoding='utf-8'))
features = config.get('mesh', {}).get('features', {}) or {}
enabled = bool(features.get('enabled', False))
angle = float(features.get('includedAngle', 150.0))
tri = ROOT / 'case/constant/triSurface'
system = ROOT / 'case/system'
system.mkdir(parents=True, exist_ok=True)
parts = features.get('parts', [])

if not parts:
    parts = [p.name for p in sorted(tri.glob('*.stl')) if 'radiator' not in p.name and p.name != 'assembly.stl']

used = []
entries = []
for filename in parts:
    path = tri / filename
    if not path.exists():
        print('Missing feature source:', path)
        continue
    name = Path(filename).stem
    used.append(filename)
    entry = f"""{name}
{{
    surfaces
    (
        \"{filename}\"
    );
    includedAngle {angle};
}}"""
    entries.append(entry)

header = """FoamFile
{
    version 2.0;
    format ascii;
    class dictionary;
    object surfaceFeaturesDict;
}

"""

(system / 'surfaceFeaturesDict').write_text(header + '\n'.join(entries) + '\n', encoding='utf-8')
(system / 'featureSources.json').write_text(
    json.dumps({'enabled': enabled, 'includedAngle': angle, 'parts': used}, indent=2),
    encoding='utf-8'
)

print('Generated surfaceFeaturesDict for surfaceFeatures')
print('Feature sources:', len(used), 'includedAngle:', angle, 'enabled:', enabled)
