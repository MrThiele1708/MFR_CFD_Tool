#!/usr/bin/env python3
"""Position-only point-cloud mapping of a complete Assembly STL.

This experimental mapper deliberately ignores triangle normals and existing
fallback labels. It samples each reference surface uniformly by area, builds
one labelled point-cloud KDTree, and assigns every assembly triangle from
multiple interior sample points. It can write a separate test profile.

It does not run OpenFOAM or modify the existing mapped profile unless the
caller explicitly chooses an output directory with --mode apply.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
from collections import Counter
from pathlib import Path

import numpy as np
import trimesh
import yaml
from scipy.spatial import cKDTree


ROOT=Path(__file__).resolve().parents[1]


def triangle_samples(triangles):
 """Return seven position-only samples for every triangle."""
 triangles=np.asarray(triangles,dtype=float)
 a=triangles[:,0]
 b=triangles[:,1]
 c=triangles[:,2]
 bary=np.asarray(
 [
 [1.0/3.0,1.0/3.0,1.0/3.0],
 [0.5,0.5,0.0],
 [0.5,0.0,0.5],
 [0.0,0.5,0.5],
 [0.6,0.2,0.2],
 [0.2,0.6,0.2],
 [0.2,0.2,0.6],
 ],
 dtype=float,
 )
 samples=(
 bary[None, :, 0, None]*a[:,None,:]
 +bary[None, :, 1, None]*b[:,None,:]
 +bary[None, :, 2, None]*c[:,None,:]
 )
 return samples


def load_surface_points(path, spacing, max_points, seed):
 mesh=trimesh.load(
 path,
 force="mesh",
 process=False,
 )
 area=float(mesh.area)
 estimated=max(1000,int(math.ceil(area/(spacing*spacing))))
 count=min(max_points,estimated)
 points,_=trimesh.sample.sample_surface(
 mesh,
 count=count,
 seed=seed,
 )
 return np.asarray(points,dtype=np.float32),area


def assign_chunk(sampled, point_tree, point_labels, part_count):
 flat=sampled.reshape(-1,3)
 distances,nearest=point_tree.query(flat,k=1)
 distances=distances.reshape(len(sampled),-1)
 labels=point_labels[nearest].reshape(len(sampled),-1)

 counts=np.zeros((len(sampled),part_count),dtype=np.int16)
 distance_sums=np.zeros((len(sampled),part_count),dtype=np.float64)

 for part_id in range(part_count):
  mask=(labels==part_id)
  counts[:,part_id]=np.sum(mask,axis=1)
  distance_sums[:,part_id]=np.sum(
   np.where(mask,distances,0.0),
   axis=1,
  )

 best_count=np.max(counts,axis=1)
 best_part=np.argmax(counts,axis=1)
 mean_distance=np.full(len(sampled),np.inf)
 for row in range(len(sampled)):
  part=int(best_part[row])
  if best_count[row] >0:
   mean_distance[row]=(
    distance_sums[row,part]/best_count[row]
   )

 sorted_counts=np.sort(counts,axis=1)
 second_count=sorted_counts[:,-2] if part_count>1 else np.zeros(len(sampled),dtype=np.int16)
 margin=best_count-second_count
 ambiguous=(margin==0)|(best_count<2)

 return best_part, best_count, margin, mean_distance, ambiguous


def main():
 parser=argparse.ArgumentParser()
 parser.add_argument(
  "--config",
  default=str(ROOT/"config/assemblyMappingFast.yaml"),
 )
 parser.add_argument(
  "--mode",
  choices=("report","apply"),
  default="report",
 )
 parser.add_argument(
  "--output-directory",
  default="geometry/production_pointmapped_test",
 )
 parser.add_argument(
  "--spacing",
  type=float,
  default=2.0,
  help="Approximate reference point spacing in input units; default 2 mm.",
 )
 parser.add_argument(
  "--max-points-per-part",
  type=int,
  default=200000,
 )
 parser.add_argument(
  "--chunk-faces",
  type=int,
  default=50000,
 )
 parser.add_argument(
  "--write-point-clouds",
  action="store_true",
 )
 parser.add_argument(
  "--seed",
  type=int,
  default=23,
 )
 parser.add_argument(
  "--results",
  default=None,
 )
 args=parser.parse_args()

 if args.spacing <=0:
  raise SystemExit("--spacing must be positive")

 mapping=yaml.safe_load(
  Path(args.config).read_text(encoding="utf-8")
 )
 input_dir=ROOT/mapping["inputDirectory"]
 assembly_path=input_dir/mapping["assemblyFile"]
 results_dir=Path(
  args.results
  if args.results
  else os.environ.get("CFD_RESULTS",str(ROOT/"results"))
 )
 if not results_dir.is_absolute():
  results_dir=ROOT/results_dir
 results_dir.mkdir(parents=True,exist_ok=True)

 output_dir=ROOT/args.output_directory
 if not output_dir.is_absolute():
  output_dir=ROOT/args.output_directory

 part_names=list(mapping.get("parts",[]))
 if not part_names:
  raise SystemExit("No reference parts configured")

 print("Loading assembly:",assembly_path,flush=True)
 assembly=trimesh.load(
  assembly_path,
  force="mesh",
  process=True,
 )
 triangles=np.asarray(assembly.triangles,dtype=float)

 cloud_parts=[]
 cloud_labels=[]
 metadata=[]

 for part_id,filename in enumerate(part_names):
  path=input_dir/filename
  if not path.exists():
   print("Missing reference part, skipping:",path)
   continue

  points,area=load_surface_points(
   path,
   args.spacing,
   args.max_points_per_part,
   args.seed+part_id,
  )
  cloud_parts.append(points)
  cloud_labels.append(
   np.full(len(points),part_id,dtype=np.int16)
  )
  metadata.append(
   {
    "part":filename,
    "partId":part_id,
    "surfaceAreaInputUnits2":area,
    "samplePoints":int(len(points)),
   }
  )
  print(
   "Sampled:",filename,
   "points=",len(points),
   "area=",area,
   flush=True,
  )

 if not cloud_parts:
  raise SystemExit("No reference surfaces could be sampled")

 cloud=np.vstack(cloud_parts)
 labels=np.concatenate(cloud_labels)
 print("Combined point cloud:",len(cloud),flush=True)
 tree=cKDTree(cloud)

 face_labels=np.full(len(triangles),-1,dtype=np.int32)
 face_counts=np.zeros(len(triangles),dtype=np.int16)
 face_margins=np.zeros(len(triangles),dtype=np.int16)
 face_distances=np.full(len(triangles),np.inf)
 face_ambiguous=np.ones(len(triangles),dtype=bool)

 for start in range(0,len(triangles),args.chunk_faces):
  end=min(len(triangles),start+args.chunk_faces)
  sampled=triangle_samples(triangles[start:end])
  best,count,margin,distance,ambiguous=assign_chunk(
   sampled,
   tree,
   labels,
   len(part_names),
  )
  face_labels[start:end]=best
  face_counts[start:end]=count
  face_margins[start:end]=margin
  face_distances[start:end]=distance
  face_ambiguous[start:end]=ambiguous
  print("Processed faces:",end,"/",len(triangles),flush=True)

 part_counts=Counter(
  part_names[int(label)]
  for label in face_labels
  if label>=0 and int(label)<len(part_names)
 )

 ambiguous_ids=np.flatnonzero(face_ambiguous)
 report={
  "method":"position-only-area-sampled-point-cloud",
  "inputDirectory":str(input_dir),
  "assemblyFile":str(assembly_path),
  "units":mapping.get("units","mm"),
  "assemblyTriangles":int(len(triangles)),
  "sampleSpacingInputUnits":float(args.spacing),
  "maxPointsPerPart":int(args.max_points_per_part),
  "combinedPointCount":int(len(cloud)),
  "ambiguousFaces":int(len(ambiguous_ids)),
  "partFaceCounts":dict(part_counts),
  "referenceParts":metadata,
  "faceCountStatistics":{
   "minWinningSamples":int(face_counts.min()),
   "maxWinningSamples":int(face_counts.max()),
   "meanWinningSamples":float(face_counts.mean()),
   "minWinnerMargin":int(face_margins.min()),
   "maxWinnerMargin":int(face_margins.max()),
   "meanWinnerMeanDistanceInputUnits":float(
    np.mean(face_distances[np.isfinite(face_distances)])
   ),
  },
 }

 report_path=results_dir/"assembly_mapping_position_only_report.json"
 report_path.write_text(
  json.dumps(report,indent=2),
  encoding="utf-8",
 )

 csv_path=results_dir/"assembly_mapping_position_only_faces.csv"
 with csv_path.open("w", newline="", encoding="utf-8") as stream:
  writer=csv.writer(stream)
  writer.writerow([
   "face",
   "assignedPart",
   "winningSamples",
   "winnerMargin",
   "meanDistanceInputUnits",
   "ambiguous",
  ])
  for face,label in enumerate(face_labels):
   writer.writerow([
    face,
    part_names[int(label)] if label>=0 else "",
    int(face_counts[face]),
    int(face_margins[face]),
    float(face_distances[face]),
    bool(face_ambiguous[face]),
   ])

 if args.write_point_clouds:
  cloud_dir=results_dir/"position_reference_pointclouds"
  cloud_dir.mkdir(parents=True,exist_ok=True)
  for part_id,points in enumerate(cloud_parts):
   point_mesh=trimesh.PointCloud(points)
   point_mesh.export(
    cloud_dir/f"points_{part_names[part_id].replace('.stl','')}.ply"
   )
  print("Point clouds:",cloud_dir)

 if args.mode=="apply":
  output_dir.mkdir(parents=True,exist_ok=True)
  shutil.copy2(
   assembly_path,
   output_dir/mapping["assemblyFile"],
  )

  for part_id,filename in enumerate(part_names):
   indices=np.flatnonzero(face_labels==part_id)
   mesh=trimesh.Trimesh(
    vertices=assembly.vertices.copy(),
    faces=assembly.faces[indices],
    process=False,
   )
   mesh.remove_unreferenced_vertices()
   mesh.export(output_dir/filename)
   print("Exported:",output_dir/filename,"faces=",len(indices))

  current_output=ROOT/mapping["outputDirectory"]
  for path in current_output.glob("radiator*.stl"):
   shutil.copy2(path,output_dir/path.name)

 print("Position-only report:",report_path)
 print("Position-only CSV:",csv_path)
 print("Ambiguous faces:",len(ambiguous_ids))
 if args.mode=="apply":
  print("Position-only output profile:",output_dir)


if __name__=="__main__":
 main()
