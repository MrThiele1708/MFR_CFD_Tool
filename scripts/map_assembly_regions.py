#!/usr/bin/env python3
"""Map faces of a watertight assembly STL to component STL references.

Default mode is report. Apply mode writes non-overlapping component STLs made
from the assembly faces, so the assembly is the authoritative mesh geometry.
"""
from pathlib import Path
import argparse, csv, json, math
import numpy as np
import yaml
import trimesh
from scipy.spatial import cKDTree

ROOT=Path(__file__).resolve().parents[1]

def scale_value(units):
    return 0.001 if str(units).lower() in ('mm','millimeter','millimetre') else 1.0

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--config',default=str(ROOT/'config/assemblyMapping.yaml'))
    ap.add_argument('--mode',choices=['report','apply','strict'],default=None)
    args=ap.parse_args()
    cfg=yaml.safe_load(Path(args.config).read_text(encoding='utf-8'))
    mode=args.mode or cfg.get('mode','report')
    inp=ROOT/cfg['inputDirectory']; out=ROOT/cfg['outputDirectory']
    assembly_file=inp/cfg['assemblyFile']; units=cfg.get('units','mm'); unit_scale=scale_value(units)
    tolerance=float(cfg.get('distanceToleranceMeters',0.001))/unit_scale
    cos_limit=math.cos(math.radians(float(cfg.get('normalAngleToleranceDeg',25))))
    if not assembly_file.exists(): raise SystemExit(f'Missing assembly STL: {assembly_file}')
    assembly=trimesh.load(assembly_file,force='mesh',process=False)
    if not isinstance(assembly,trimesh.Trimesh): raise SystemExit('Assembly is not a single mesh')
    parts=cfg.get('parts',[])
    if not parts: raise SystemExit('No component parts configured')
    refs={}
    for name in parts:
        f=inp/name
        if not f.exists(): raise SystemExit(f'Missing component STL: {f}')
        refs[name]=trimesh.load(f,force='mesh',process=False)
    centers=assembly.triangles_center; normals=assembly.face_normals
    candidates=[]
    for name,mesh in refs.items():
        samples=np.vstack([mesh.vertices,mesh.triangles_center])
        candidates.append((name,mesh,cKDTree(samples),cKDTree(mesh.triangles_center)))
    assigned={name:[] for name in refs}; ambiguous=[]; unassigned=[]
    perpart={name:{'faces':0,'areaInputUnits2':0.0,'minDistanceInputUnits':None} for name in refs}
    for i,(center,normal) in enumerate(zip(centers,normals)):
        hits=[]
        for name,mesh,tree,facetree in candidates:
            dist,_=tree.query(center,k=1)
            _,idx=facetree.query(center,k=1)
            align=abs(float(np.dot(normal,mesh.face_normals[idx])))
            if dist<=tolerance and align>=cos_limit: hits.append((float(dist),name))
        hits.sort()
        if not hits: unassigned.append(i); continue
        if len(hits)>1 and hits[1][0]-hits[0][0] < tolerance*0.25:
            ambiguous.append({'face':i,'candidates':[x[1] for x in hits[:4]],'distances':[x[0] for x in hits[:4]]})
            continue
        name=hits[0][1]; assigned[name].append(i); perpart[name]['faces']+=1; perpart[name]['areaInputUnits2']+=float(assembly.area_faces[i])
        d=hits[0][0]; old=perpart[name]['minDistanceInputUnits']; perpart[name]['minDistanceInputUnits']=d if old is None else min(old,d)
    report={'mode':mode,'assemblyFile':str(assembly_file),'inputDirectory':str(inp),'outputDirectory':str(out),'units':units,'distanceToleranceInputUnits':tolerance,'normalAngleToleranceDeg':float(cfg.get('normalAngleToleranceDeg',25)),'assemblyTriangles':int(len(assembly.faces)),'assignedFaces':sum(len(v) for v in assigned.values()),'unassignedFaces':len(unassigned),'ambiguousFaces':len(ambiguous),'parts':perpart,'unassignedFaceIndices':unassigned[:1000],'ambiguousExamples':ambiguous[:1000]}
    report_path=ROOT/'results/assembly_mapping_report.json'; csv_path=ROOT/'results/assembly_mapping_report.csv'; report_path.parent.mkdir(exist_ok=True); report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    with csv_path.open('w',newline='',encoding='utf-8') as f:
        w=csv.writer(f); w.writerow(['part','mappedFaces','areaInputUnits2','minDistanceInputUnits']);
        for name,d in perpart.items(): w.writerow([name,d['faces'],d['areaInputUnits2'],d['minDistanceInputUnits']])
    print(json.dumps(report,indent=2)); print('JSON report:',report_path); print('CSV report:',csv_path)
    if mode=='strict' and (unassigned or ambiguous): raise SystemExit('Strict mapping failed: unresolved assembly faces remain.')
    if mode=='apply':
        if unassigned or ambiguous: raise SystemExit('Apply refused: run report first and resolve unassigned/ambiguous faces, or use --mode apply only after setting allowUnresolved.')
        out.mkdir(parents=True,exist_ok=True)
        for name,indices in assigned.items():
            face_array=np.asarray(indices,dtype=int)
            mesh=trimesh.Trimesh(vertices=assembly.vertices.copy(),faces=assembly.faces[face_array],process=False)
            mesh.remove_unreferenced_vertices(); mesh.export(out/name)
        print('Mapped component STLs written:',out)

if __name__=='__main__': main()
