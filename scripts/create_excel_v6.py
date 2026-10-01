#!/usr/bin/env python3
from pathlib import Path
import os
import json,re,shutil
import xlsxwriter
ROOT=Path(__file__).resolve().parents[1]; CASE=Path(os.environ.get("CFD_CASE", str(ROOT/'case'))); OUT=Path(os.environ.get("CFD_RESULTS", str(ROOT/'results'))); OUT.mkdir(parents=True, exist_ok=True)
ORDER=['total','body','frontWing','rearWing','counterWings','diffuser','underbody','sidepods','suspension','wheels']
num_re=re.compile(r'[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?')

def component_name(path):
 n=path.parent.parent.name
 for prefix in ('forces_','forceCoeffs_'):
  if n.startswith(prefix): n=n[len(prefix):]
 return n

def ordered(files): return sorted(files,key=lambda p:(ORDER.index(component_name(p)) if component_name(p) in ORDER else 999,component_name(p).lower()))
def num(x):
 try:return float(x)
 except:return x

def generic_table(path):
 h=None; rows=[]
 for line in Path(path).read_text(errors='replace').splitlines():
  s=line.strip()
  if not s: continue
  if s.startswith('#'):
   q=s.lstrip('#').strip()
   if q.startswith('Time'): h=q.split()
   continue
  if h:
   v=s.split()
   if len(v)==len(h): rows.append(v)
 return h or [],rows

def force_table(path):
 rows=[]
 for line in Path(path).read_text(errors='replace').splitlines():
  s=line.strip()
  if not s or s.startswith('#'): continue
  v=[float(x) for x in num_re.findall(s)]
  if len(v)>1: rows.append(v)
 if not rows:return [],[]
 n=len(rows[0])-1
 if n==18:
  h=['Time','Fx_pressure','Fy_pressure','Fz_pressure','Fx_viscous','Fy_viscous','Fz_viscous','Fx_porous','Fy_porous','Fz_porous','Mx_pressure','My_pressure','Mz_pressure','Mx_viscous','My_viscous','Mz_viscous','Mx_porous','My_porous','Mz_porous']; fg=[(1,4),(4,7),(7,10)]; mg=[(10,13),(13,16),(16,19)]
 elif n==12:
  h=['Time','Fx_pressure','Fy_pressure','Fz_pressure','Fx_viscous','Fy_viscous','Fz_viscous','Mx_pressure','My_pressure','Mz_pressure','Mx_viscous','My_viscous','Mz_viscous']; fg=[(1,4),(4,7)]; mg=[(7,10),(10,13)]
 else:return ['Time']+[f'value_{i:02d}' for i in range(1,n+1)],rows
 h=['Time','Fx_total','Fy_total','Fz_total','Mx_total','My_total','Mz_total']+h[1:]
 out=[]
 for r in rows:
  f=[sum(r[a+i] for a,b in fg) for i in range(3)]; m=[sum(r[a+i] for a,b in mg) for i in range(3)]
  out.append([r[0]]+f+m+r[1:])
 return h,out

def get_table(p): return force_table(p) if p.name=='forces.dat' else generic_table(p)
def write_table(ws,row,title,path):
 h,rows=get_table(path); ws.write(row,0,title); ws.write(row+1,0,str(path.relative_to(ROOT)))
 for c,x in enumerate(h): ws.write(row+2,c,x)
 for rr,data in enumerate(rows,row+3):
  for c,x in enumerate(data): ws.write(rr,c,num(x))
 return row+len(rows)+5

def derived_coeffs(path,rho,U,A,L):
 h,rows=force_table(path); out={}
 q=.5*rho*U*U*A
 for r in rows:
  if len(r)<7: continue
  t=r[0]; fx,fy,fz,mx,my,mz=r[1:7]
  out[float(t)]={'CY':fy/q,'Cd_from_forces':fx/q,'Cl_from_forces':fz/q,'CmRoll':mx/(q*L),'CmPitch':my/(q*L),'CmYaw':mz/(q*L)}
 return out

def coeff_table(path, force_path, rho, U, A, L):
    h, rows = generic_table(path)

    derived = {}
    if force_path and force_path.exists():
        derived = derived_coeffs(
            force_path,
            rho,
            U,
            A,
            L
        )

    if "Cm" in h:
        cm_index = h.index("Cm")

        h = [
            value
            for i, value in enumerate(h)
            if i != cm_index
        ]

        rows = [
            [
                value
                for i, value in enumerate(row)
                if i != cm_index
            ]
            for row in rows
        ]


    if "Cd" in h:
        cd_index = h.index("Cd")

        for row in rows:
            try:
                row[cd_index] = str(
                    -float(row[cd_index])
                )
            except (ValueError, TypeError):
                pass


    extra = [
        "CY",
        "CmRoll",
        "CmPitch",
        "CmYaw"
    ]

    output_header = h + extra
    output_rows = []

    for row in rows:
        data = derived.get(
            float(row[0]),
            {}
        )

        output_rows.append(
            row + [
                data.get(name, "")
                for name in extra
            ]
        )


    return output_header, output_rows


def mesh_quality(path):
 s=Path(path).read_text(errors='replace') if Path(path).exists() else ''
 pats={'points':r'points:\s+(\d+)','faces':r'faces:\s+(\d+)','cells':r'cells:\s+(\d+)','maxAspectRatio':r'Max aspect ratio\s*=\s*([\deE+.-]+)','minVolume':r'Min volume\s*=\s*([\deE+.-]+)','maxNonOrthogonality':r'Mesh non-orthogonality Max:\s*([\deE+.-]+)','averageNonOrthogonality':r'Mesh non-orthogonality Max:\s*[\deE+.-]+ average:\s*([\deE+.-]+)','maxSkewness':r'Max skewness\s*=\s*([\deE+.-]+)','failedChecks':r'Failed\s+(\d+)\s+mesh checks'}
 return [(k,(re.search(v,s).group(1) if re.search(v,s) else '')) for k,v in pats.items()]

def last_sheet(wb,name,files,head,force_map=None,rho=1.2041,U=13.889,A=1,L=1.56):
 ws=wb.add_worksheet(name); first=True; row=1
 for f in files:
  h,rows=get_table(f)
  if name.startswith('ForceCoeffs'):
   ff=force_map.get(component_name(f)) if force_map else None; h,rows=coeff_table(f,ff,rho,U,A,L)
  if not h or not rows: continue
  if first: ws.write_row(0,0,['Component']+h,head); first=False
  ws.write(row,0,component_name(f))
  for c,x in enumerate(rows[-1],1): ws.write(row,c,num(x))
  row+=1
 if first: ws.write(0,0,'No matching OpenFOAM table found.',head)
 ws.freeze_panes(1,1); ws.set_column(0,0,24)

def flatten(d,p=''):
 for k,v in d.items():
  q=f'{p}.{k}' if p else k
  if isinstance(v,dict): yield from flatten(v,q)
  else: yield q,v
cfg=json.loads((CASE/'effective.json').read_text()) if (CASE/'effective.json').exists() else {}
rho=float(cfg.get('air',{}).get('rho',1.2041)); U=float(cfg.get('flow',{}).get('speed',13.889)); A=float(cfg.get('reference',{}).get('area',1.0)); L=float(cfg.get('reference',{}).get('length',1.56))
post=CASE/'postProcessing'; coeff=ordered(list(post.glob('**/forceCoeffs.dat'))); forces=ordered(list(post.glob('**/forces.dat'))); residuals=ordered(list(post.glob('**/residuals.dat')))
force_map={component_name(f):f for f in forces}
file=OUT/'FormulaStudent_results.xlsx'; wb=xlsxwriter.Workbook(str(file)); title=wb.add_format({'bold':True,'bg_color':'#1F4E78','font_color':'white'}); head=wb.add_format({'bold':True,'bg_color':'#D9EAF7'}); bold=wb.add_format({'bold':True})
ws=wb.add_worksheet('Summary'); ws.write('A1','Formula Student CFD report',title); ws.write('A3','Note',bold); ws.write('B3','Totals are first; summed forces/moments are the leftmost numerical columns in Forces and Forces_Last.')
setup=wb.add_worksheet('Setup'); setup.write_row(0,0,['Parameter','Value'],head); r=1
for k,v in flatten(cfg): setup.write(r,0,k); setup.write(r,1,str(v)); r+=1
setup.set_column(0,0,42); setup.set_column(1,1,60)
for sheet,files in [('Forces',forces),('Residuals',residuals)]:
 ws=wb.add_worksheet(sheet); row=0
 if not files: ws.write(0,0,'No matching OpenFOAM table found.',head)
 for f in files: row=write_table(ws,row,component_name(f),f)
 ws.set_column(0,0,24)
ws=wb.add_worksheet('ForceCoeffs'); row=0
if not coeff: ws.write(0,0,'No matching OpenFOAM table found.',head)
for f in coeff:
 ff=force_map.get(component_name(f)); h,rows=coeff_table(f,ff,rho,U,A,L); ws.write(row,0,component_name(f)); ws.write(row+1,0,str(f.relative_to(ROOT)))
 for c,x in enumerate(h): ws.write(row+2,c,x)
 for rr,data in enumerate(rows,row+3):
  for c,x in enumerate(data): ws.write(rr,c,num(x))
 row+=len(rows)+5
ws.set_column(0,0,24)
last_sheet(wb,'Forces_Last',forces,head,rho=rho,U=U,A=A,L=L); last_sheet(wb,'ForceCoeffs_Last',coeff,head,force_map,rho,U,A,L)
ws=wb.add_worksheet('Mesh_Quality'); ws.write_row(0,0,['Metric','Value'],head)
for r,(k,v) in enumerate(mesh_quality(CASE/'log.checkMesh'),1): ws.write(r,0,k); ws.write(r,1,num(v))
ws=wb.add_worksheet('yPlus'); yp=ordered(list(post.glob('**/yPlus.dat')))
if yp: write_table(ws,0,'yPlus',yp[-1])
else: ws.write(0,0,'No yPlus table found.',head)
for sheet,folder in [('Slice_Pressure','pressure'),('Slice_Velocity','velocity'),('Slice_TotalPressure','totalPressure')]:
 ws=wb.add_worksheet(sheet); ws.write(0,0,sheet,title); imgs=sorted((OUT/'slices_vtk'/folder).glob('*.png')); row=2
 for i,img in enumerate(imgs):
  col=(i%3)*7
  if i and i%3==0: row+=23
  ws.write(row-1,col,img.name,head); ws.insert_image(row,col,str(img),{'x_scale':0.45,'y_scale':0.45})
wb.add_worksheet('Raw_Data').write(0,0,'Original files remain under the active case/postProcessing.',head)
wb.close(); print('Excel report:',file)
try:
 target=cfg.get('project',).get('windowsResults','')
 if target and Path(target).parent.exists(): Path(target).mkdir(parents=True,exist_ok=True); shutil.copy2(file,Path(target)/file.name); print('Windows copy:',Path(target)/file.name)
except Exception as e: print('Windows copy skipped:',e)
