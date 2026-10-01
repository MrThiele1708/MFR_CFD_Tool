#!/usr/bin/env python3
import os
from pathlib import Path
import json,yaml
r=Path(__file__).resolve().parents[1]; c=yaml.safe_load((Path(os.environ.get("CFD_CONFIG", str(r / "config/parameters.yaml")))).read_text()); case=r/c['project']['case']; m=json.loads((case/'constant/geometryMetrics.json').read_text()); man=yaml.safe_load((Path(os.environ.get("CFD_MANIFEST", str(r / "config/geometryManifest.yaml")))).read_text()); patches=sorted(set(s['patch'] for s in man['parts'].values() if s.get('include',True))); b=m['bbox_m']; xmin,xmax=b[0][0],b[1][0]; ymin,ymax=b[0][1],b[1][1]; zmax=b[1][2]; L=max(m['vehicleLength'],.1); W=max(m['vehicleWidth'],.1); H=max(m['vehicleHeight'],.1); p=c['mesh']['presets'][c['mesh']['domain']]; X0=xmin-p['outlet']*L; X1=xmax+p['inlet']*L; Y0=ymin-p['side']*W; Y1=ymax+p['side']*W; Z1=zmax+p['top']*H
sys=case/'system'; sys.mkdir(exist_ok=True); zero=case/'0.orig'; zero.mkdir(exist_ok=True)
block = f'''FoamFile {{ version 2.0; format ascii; class dictionary; object blockMeshDict; }}
convertToMeters 1;
vertices (({X0} {Y0} 0) ({X1} {Y0} 0) ({X1} {Y1} 0) ({X0} {Y1} 0) ({X0} {Y0} {Z1}) ({X1} {Y0} {Z1}) ({X1} {Y1} {Z1}) ({X0} {Y1} {Z1}));
blocks (hex (0 1 2 3 4 5 6 7) (80 32 32) simpleGrading (1 1 1));
edges ();
boundary (inlet {{type patch; faces ((1 2 6 5));}} outlet {{type patch; faces ((0 4 7 3));}} ground {{type wall; faces ((0 1 2 3));}} top {{type patch; faces ((4 5 6 7));}} sideLeft {{type patch; faces ((3 7 6 2));}} sideRight {{type patch; faces ((0 1 5 4));}});
mergePatchPairs ();
'''
(sys/'blockMeshDict').write_text(block)
entries=[]; refin=[]
for s in man['parts'].values():
 if not s.get('include',True): continue
 entries.append(f'    {s["patch"]} {{ type triSurfaceMesh; file "{s["file"]}"; name {s["patch"]}; }}')
 refin.append(f"        {s['patch']} {{ level (1 2); patchInfo {{ type wall; }} }}")
loc=(0,0,zmax+.5*max(H,.5))
snappy = f'''FoamFile {{ version 2.0; format ascii; class dictionary; object snappyHexMeshDict; }}
castellatedMesh true; snap true; addLayers true;
geometry {{
{chr(10).join(entries)}
}}
castellatedMeshControls {{ maxLocalCells 1000000; maxGlobalCells 3000000; minRefinementCells 10; nCellsBetweenLevels 3; features (); refinementSurfaces {{
{chr(10).join(refin)}
}} refinementRegions (); locationInMesh ({loc[0]} {loc[1]} {loc[2]}); allowFreeStandingZoneFaces true; }}
snapControls {{ nSmoothPatch 3; tolerance 2; nSolveIter 100; nRelaxIter 5; }}
addLayersControls {{ relativeSizes true; layers {{}}; expansionRatio 1.2; finalLayerThickness .3; minThickness .1; nLayerIter 50; }}
meshQualityControls {{ maxNonOrtho 70; maxInternalSkewness 4; maxBoundarySkewness 20; minVol 1e-13; }}
mergeTolerance 1e-6;
'''
(sys/'snappyHexMeshDict').write_text(snappy)
patchU=''.join(f"    {p} {{ type fixedValue; value uniform (0 0 0); }}\n" for p in patches)
patchP=''.join(f"    {p} {{ type zeroGradient; }}\n" for p in patches)
moving_ground = bool(
    c.get("boundaryConditions", {})
    .get("movingGround", True)
)

ground_value = (
    f"(-{c['flow']['speed']} 0 0)"
    if moving_ground
    else "(0 0 0)"
)

ground_condition = c.get(
    "boundaryConditions",
    {}
).get(
    "groundCondition",
    "fixedValue",
)

if ground_condition == "slip":
    ground_entry = "type slip;"
else:
    ground_entry = (
        f"type fixedValue; "
        f"value uniform {ground_value};"
    )

U_body = f'''FoamFile {{ version 2.0; format ascii; class volVectorField; object U; }}
dimensions [0 1 -1 0 0 0 0]; internalField uniform (-{c['flow']['speed']} 0 0);
boundaryField {{ inlet {{type fixedValue; value uniform (-{c['flow']['speed']} 0 0);}} outlet {{type pressureInletOutletVelocity; value uniform (0 0 0);}} ground {{{ground_entry}}} top {{type slip;}} sideLeft {{type slip;}} sideRight {{type slip;}}
{patchU}}}
'''
p_body = f'''FoamFile {{ version 2.0; format ascii; class volScalarField; object p; }}
dimensions [0 2 -2 0 0 0 0]; internalField uniform 0;
boundaryField {{ inlet {{type zeroGradient;}} outlet {{type fixedValue; value uniform 0;}} ground {{type zeroGradient;}} top {{type zeroGradient;}} sideLeft {{type zeroGradient;}} sideRight {{type zeroGradient;}}
{patchP}}}
'''
(zero/'U').write_text(U_body)
(zero/'p').write_text(p_body)
(sys/'fvSchemes').write_text('''FoamFile { version 2.0; format ascii; class dictionary; object fvSchemes; }
ddtSchemes { default steadyState; }
gradSchemes { default cellLimited leastSquares 1; grad(U) cellLimited leastSquares 1; }
divSchemes { default none; div(phi,U) bounded Gauss linearUpwind grad(U); div(phi,k) bounded Gauss upwind; div(phi,omega) bounded Gauss upwind; div((nuEff*dev2(T(grad(U))))) Gauss linear; }
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
wallDist { method meshWave; }''')
(sys/'fvSolution').write_text('''FoamFile { version 2.0; format ascii; class dictionary; object fvSolution; }
solvers { p { solver GAMG; tolerance 1e-7; relTol .05; smoother GaussSeidel; } "(U|k|omega)" { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol .1; } }
SIMPLE { nNonOrthogonalCorrectors 1; residualControl { p 1e-5; U 1e-6; k 1e-6; omega 1e-6; } }
relaxationFactors { fields { p .3; } equations { U .7; k .7; omega .7; } }''')
print('generated OpenFOAM dictionaries')
