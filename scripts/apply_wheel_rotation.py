import os
from pathlib import Path
import re
import yaml
import trimesh

ROOT = Path(__file__).resolve().parents[1]

config = yaml.safe_load(
    (ROOT / "config" / "parameters.yaml").read_text(encoding="utf-8")
)
speed = float(config["flow"]["speed"])
diameter = float(config["vehicle"]["tireDiameter"])
radius = diameter / 2.0
slip = float(config["flow"].get("wheelSlip", 0.0))

omega = speed / radius * (1.0 + slip)

u_file = Path(os.environ.get("CFD_CASE", str(ROOT / "case"))) / "0" / "U"
text = u_file.read_text(encoding="utf-8")

wheel_data = {
    "wheelFL": "wheel_FL.stl",
    "wheelFR": "wheel_FR.stl",
    "wheelRL": "wheel_RL.stl",
    "wheelRR": "wheel_RR.stl",
}

for patch, filename in wheel_data.items():
    stl_path = Path(os.environ.get("CFD_CASE", str(ROOT / "case"))) / "constant" / "triSurface" / filename

    if not stl_path.exists():
        print(f"Warning: missing {stl_path}")
        continue

    mesh = trimesh.load(stl_path, force="mesh")
    center = mesh.bounds.mean(axis=0)

    origin = " ".join(f"{float(v):.9g}" for v in center)

    replacement = f"""
    {patch}
    {{
        type rotatingWallVelocity;
        origin ({origin});
        axis (0 1 0);
        omega {omega:.9g};
        value uniform (0 0 0);
    }}"""

    pattern = rf"(?ms)^\s*{patch}\s*\{{.*?\}}"
    text, count = re.subn(pattern, replacement, text)

    if count:
        print(f"Rotating wall applied: {patch}, omega={omega:.6g} rad/s")
    else:
        print(f"Warning: patch not found in U: {patch}")

u_file.write_text(text, encoding="utf-8")
print(f"Wheel angular velocity: {omega:.6g} rad/s")
