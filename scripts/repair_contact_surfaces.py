#!/usr/bin/env python3
"""Detect and optionally remove coincident contact faces from selected STL parts.

The body is the master surface. Only secondary parts are modified. Default mode
is report; use --mode apply only after reviewing the report.
"""
from pathlib import Path
import argparse,csv,json,math,shutil
import numpy as np
import yaml
import trimesh
try:
 from scipy.spatial import cKDTree
except Exception as e:
 raise SystemExit("Missing scipy. Install with: python3 -m pip install scipy")

ROOT=Path(__file__).resolve().parents[1]

def load(p): return yaml.safe_load(Path(p).read_text(encoding='utf-8'))
def scale_units(u): return 0.001 if str(u).lower() in ('mm','millimeter','millimetre') else 1.0

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--config',default=str(ROOT/'config/contactRepair.yaml')); ap.add_argument('--mode',choices=['report','apply'],default=None); a=ap.parse_args()
 c=load(a.config); mode=a.mode or c.get('mode','report'); inp=ROOT/c['inputDirectory']; out=ROOT/c['outputDirectory']; units=c.get('units','mm'); scale=scale_units(units); tol_m=float(c.get('distanceToleranceMeters',0.0005)); tol=tol_m/scale; angle=float(c.get('normalAngleToleranceDeg',15)); coslim=math.cos(math.radians(angle)); master_name=c['masterPart']; second=c.get('secondaryParts',[])
 mf=inp/master_name
 if not mf.exists(): raise SystemExit(f'Master STL not found: {mf}')
 master=trimesh.load(mf,force='mesh',process=False)
 if not isinstance(master,trimesh.Trimesh): raise SystemExit('Master is not a single mesh')
 # Face-centre and vertex samples provide a practical proximity test.
 pts=np.vstack([master.vertices,master.triangles_center]); tree=cKDTree(pts)
 face_tree=cKDTree(master.triangles_center); body_normals=master.face_normals
 report={'mode':mode,'inputDirectory':str(inp),'outputDirectory':str(out),'masterPart':master_name,'distanceToleranceMeters':tol_m,'normalAngleToleranceDeg':angle,'parts':[]}
 if mode=='apply': out.mkdir(parents=True,exist_ok=True)
 allnames=sorted(p.name for p in inp.glob('*.stl'))
 for name in allnames:
  src=inp/name
  if name==master_name or name not in second:
   if mode=='apply': shutil.copy2(src,out/name)
   continue
  mesh=trimesh.load(src,force='mesh',process=False)
  if not isinstance(mesh,trimesh.Trimesh): report['parts'].append({'file':name,'status':'not_single_mesh'}); continue
  centers=mesh.triangles_center; normals=mesh.face_normals
  dist,_=tree.query(centers,k=1)
  _,bi=face_tree.query(centers,k=1)
  align=np.abs(np.einsum('ij,ij->i',normals,body_normals[bi]))
  remove=(dist<=tol)&(align>=coslim)
  # Exact duplicate triangle candidates are always included.
  removed=int(remove.sum()); area=float(mesh.area_faces[remove].sum()) if removed else 0.0
  item={'file':name,'trianglesBefore':int(len(mesh.faces)),'candidateFaces':removed,'candidateAreaInputUnits2':area,'minDistanceInputUnits':float(dist.min()) if len(dist) else None,'status':'candidate' if removed else 'no_candidate'}
  if mode=='apply' and removed:
   mesh.update_faces(~remove); mesh.remove_unreferenced_vertices(); mesh.export(out/name); item['trianglesAfter']=int(len(mesh.faces))
  elif mode=='apply':
   shutil.copy2(src,out/name); item['trianglesAfter']=int(len(mesh.faces))
  report['parts'].append(item)
 # write report files
 rep=ROOT/'results/contact_surface_report.json'; rep.parent.mkdir(exist_ok=True); rep.write_text(json.dumps(report,indent=2),encoding='utf-8')
 with (ROOT/'results/contact_surface_candidates.csv').open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=['file','trianglesBefore','candidateFaces','candidateAreaInputUnits2','minDistanceInputUnits','status','trianglesAfter']); w.writeheader()
  for item in report['parts']: w.writerow(item)
 print(json.dumps(report,indent=2)); print('Report:',rep); print('CSV:',ROOT/'results/contact_surface_candidates.csv')
 if mode=='apply': print('Repaired files written to:',out)
if __name__=='__main__': main()
