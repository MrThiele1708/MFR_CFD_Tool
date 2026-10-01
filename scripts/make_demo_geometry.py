#!/usr/bin/env python3
from pathlib import Path
import argparse, trimesh
def box(o,n,e,c):
 m=trimesh.creation.box(extents=e); m.apply_translation(c); m.export(o/(n+".stl"))
def main():
 a=argparse.ArgumentParser(); a.add_argument("--output",default=None); x=a.parse_args(); r=Path(__file__).resolve().parents[1]; o=Path(x.output) if x.output else r/"geometry"/"demo"; o.mkdir(parents=True,exist_ok=True)
 box(o,"body",(1.8,.95,.35),(0,0,.43)); box(o,"frontWing",(.45,1.55,.06),(1.15,0,.17)); box(o,"rearWing",(.35,1.4,.10),(-1.25,0,.98)); box(o,"counterWing_left",(.28,.22,.05),(.65,.58,.57)); box(o,"counterWing_right",(.28,.22,.05),(.65,-.58,.57)); box(o,"underbody",(1.7,.85,.04),(0,0,.22)); box(o,"diffuser",(.7,.9,.08),(-.65,0,.17)); box(o,"sidepod_left",(.75,.20,.28),(.15,.58,.43)); box(o,"sidepod_right",(.75,.20,.28),(.15,-.58,.43)); box(o,"driver",(.42,.35,.65),(0,0,.82)); box(o,"rollhoop",(.08,.50,.70),(-.25,0,.85))
 for n,x,y in [("wheel_FL",.78,.615),("wheel_FR",.78,-.615),("wheel_RL",-.78,.60),("wheel_RR",-.78,-.60)]:
  m=trimesh.creation.cylinder(radius=.205,height=.225,sections=48); m.apply_transform(trimesh.transformations.rotation_matrix(1.5707963,[1,0,0])); m.apply_translation((x,y,.205)); m.export(o/(n+".stl"))
 for n,x,y in [("suspension_FL",.78,.615),("suspension_FR",.78,-.615),("suspension_RL",-.78,.60),("suspension_RR",-.78,-.60)]: box(o,n,(.55,.05,.05),(x-.3,y,.32))
 box(o,"radiator_left_volume",(.34,.10,.20),(.20,.58,.43)); box(o,"radiator_right_volume",(.34,.10,.20),(.20,-.58,.43)); print("Demo geometry:",o)
if __name__=="__main__": main()
