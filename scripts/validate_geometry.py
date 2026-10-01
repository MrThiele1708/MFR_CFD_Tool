#!/usr/bin/env python3
from pathlib import Path
import argparse,json,trimesh
a=argparse.ArgumentParser(); a.add_argument('--input',required=True); a.add_argument('--units',default='mm'); a.add_argument('--output',default='results/geometry_report.json'); x=a.parse_args(); files=sorted(Path(x.input).glob('*.stl')); scale=.001 if x.units.lower() in ('mm','millimeter') else 1.0; out=[]
for f in files:
 m=trimesh.load(f,force='mesh'); b=m.bounds; out.append({'file':f.name,'triangles':len(m.faces),'watertight':bool(m.is_watertight),'winding_consistent':bool(m.is_winding_consistent),'bounds_m':(b*scale).tolist(),'extents_m':(m.extents*scale).tolist()})
res={'units_assumed':x.units,'files':out}; p=Path(x.output); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(res,indent=2)); print(json.dumps(res,indent=2))
