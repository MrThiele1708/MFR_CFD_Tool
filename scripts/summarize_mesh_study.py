#!/usr/bin/env python3
from pathlib import Path
import re,csv,json
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]; BASE=ROOT/'results'/'meshStudy'; OUT=ROOT/'results'
levels=['quick','balanced','highFidelity']; rho=1.2041; U=13.889; A=1.0; L=1.560; q=.5*rho*U*U*A
num_re=re.compile(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?')
def last_force(path):
 rows=[]
 if not path.exists(): return {}
 for line in path.read_text(errors='replace').splitlines():
  s=line.strip()
  if not s or s.startswith('#'): continue
  v=[float(x) for x in num_re.findall(s)]
  if len(v)>1: rows.append(v)
 if not rows:return {}
 r=rows[-1]; n=len(r)-1
 if n==18: fg=[(1,4),(4,7),(7,10)]; mg=[(10,13),(13,16),(16,19)]
 elif n==12: fg=[(1,4),(4,7)]; mg=[(7,10),(10,13)]
 else:return {}
 f=[sum(r[a+i] for a,b in fg) for i in range(3)]; m=[sum(r[a+i] for a,b in mg) for i in range(3)]
 return {'time':r[0],'Fx_total':f[0],'Fy_total':f[1],'Fz_total':f[2],'Drag_N':-f[0],'CY':f[1]/q,'CL_from_forces':f[2]/q,'CmRoll':m[0]/(q*L),'CmPitch':m[1]/(q*L),'CmYaw':m[2]/(q*L)}
def last_coeff(path):
 if not path.exists():return {}
 header=None; rows=[]
 for line in path.read_text(errors='replace').splitlines():
  s=line.strip()
  if s.startswith('#'):
   h=s.lstrip('#').strip()
   if h.startswith('Time'): header=h.split()
   continue
  if header and s:
   v=s.split()
   if len(v)==len(header): rows.append(v)
 if not header or not rows:return {}
 d=dict(zip(header,rows[-1])); out={'coeffTime':float(d['Time'])}
 for k in ['Cm','Cd','Cl','Cl(f)','Cl(r)']:
  if k in d: out[k.replace('(','_').replace(')','')]=float(d[k])
 if 'Cd' in out: out['Cd_positive']=-out['Cd']
 return out
def mesh(path):
 s=path.read_text(errors='replace') if path.exists() else ''
 def find(p):
  m=re.search(p,s); return float(m.group(1)) if m else None
 return {'cells':find(r'cells:\s+(\d+)'),'points':find(r'points:\s+(\d+)'),'maxAspectRatio':find(r'Max aspect ratio\s*=\s*([\deE+.-]+)'),'maxNonOrthogonality':find(r'Mesh non-orthogonality Max:\s*([\deE+.-]+)'),'maxSkewness':find(r'Max skewness\s*=\s*([\deE+.-]+)'),'failedChecks':find(r'Failed\s+(\d+)\s+mesh checks'),'meshOK':('Mesh OK' in s)}
rows=[]
for level in levels:
 d=BASE/level; r={'meshLevel':level}; r.update(mesh(d/'log.checkMesh')); r.update(last_force(d/'postProcessing'/'forces_total'/'0'/'forces.dat')); r.update(last_coeff(d/'postProcessing'/'total'/'0'/'forceCoeffs.dat')); rows.append(r)
df=pd.DataFrame(rows); csvpath=OUT/'meshStudy_summary.csv'; df.to_csv(csvpath,index=False)
xlsx=OUT/'meshStudy_summary.xlsx'; df.to_excel(xlsx,index=False,sheet_name='Summary')
print('CSV:',csvpath); print('XLSX:',xlsx); print(df.to_string(index=False))
