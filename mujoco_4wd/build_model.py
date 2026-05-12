"""Build a MuJoCo MJCF model from the extracted DDSM115 4WD-A STEP components.

Reads `assembly.json` produced by `step_to_meshes.py` and writes:
  - `assets/<role>.stl` copies of meshes with ASCII-safe names
  - `ddsm115_4wd.xml` MJCF model with a free-floating chassis and 4 hinge wheels

Convention: STEP units are mm; MuJoCo scene is in meters. Chassis origin
sits at the wheel-hub plane (Z=0 in STEP), so the chassis body is placed
at z = wheel_radius above the floor so the wheels just touch the ground.
"""
from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
ASSEMBLY = json.loads((ROOT / "assembly.json").read_text())

# Assign each top-level STEP component to a role. The STEP component "raw_name"
# field uniquely identifies an instance (suffixed with `:N`), so we map by it.
# Chassis frame after extraction:
#   +Y = forward (long axis of robot; wheels roll along Y)
#   +X = right side (convention chosen so wheel_fr is at +X)
#   +Z = up
# Wheel rotation axes point along each wheel's body-local Y, which lands on
# chassis -X for the right wheels (X=+80) and chassis +X for the left wheels.
ROLE_BY_RAW = {
    # 4 wheels (label = front/back × left/right; pairs are Y=±100 for fore/aft
    #           and X=±80 for left/right)
    "DDSM115 (1):1":  "wheel_fr",   # +X right, +Y front
    "DDSM115 v4:1":   "wheel_br",   # +X right, -Y back
    "DDSM115 (2):1":  "wheel_fl",   # -X left,  +Y front
    "DDSM115:1":      "wheel_bl",   # -X left,  -Y back
    # frame
    "2040 Extrusion v1:1":         "frame_extrusion_1",
    "2040 Extrusion v1 (1):1":     "frame_extrusion_2",
    "2040 Extrusion v1(镜像):1":    "frame_extrusion_3",
    "2040 Extrusion v1 (1):2":     "frame_extrusion_4",
    # CNC corner brackets (4)
    "CNC链接件:1":             "cnc_link_1",
    "CNC链接件(镜像):1":       "cnc_link_2",
    "CNC链接件(镜像) (1):1":   "cnc_link_3",
    "CNC链接件(镜像)(镜像):1": "cnc_link_4",
    # side supports (4)
    "侧支持:1": "side_support_1",
    "侧支持:2": "side_support_2",
    "侧支持:3": "side_support_3",
    "侧支持:4": "side_support_4",
    # top and bottom plates
    "盖板:1":     "top_plate",
    "零部件25:1": "bottom_plate",
}

WHEEL_ROLES = {"wheel_fr", "wheel_fl", "wheel_br", "wheel_bl"}


def mat_to_quat(R: np.ndarray) -> np.ndarray:
    """3x3 rotation matrix -> MuJoCo quaternion (w, x, y, z)."""
    # Shepperd's method
    m00, m01, m02 = R[0]
    m10, m11, m12 = R[1]
    m20, m21, m22 = R[2]
    t = m00 + m11 + m22
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        w = 0.25 * s
        x = (m21 - m12) / s
        y = (m02 - m20) / s
        z = (m10 - m01) / s
    elif m00 > m11 and m00 > m22:
        s = math.sqrt(1.0 + m00 - m11 - m22) * 2
        w = (m21 - m12) / s
        x = 0.25 * s
        y = (m01 + m10) / s
        z = (m02 + m20) / s
    elif m11 > m22:
        s = math.sqrt(1.0 + m11 - m00 - m22) * 2
        w = (m02 - m20) / s
        x = (m01 + m10) / s
        y = 0.25 * s
        z = (m12 + m21) / s
    else:
        s = math.sqrt(1.0 + m22 - m00 - m11) * 2
        w = (m10 - m01) / s
        x = (m02 + m20) / s
        y = (m12 + m21) / s
        z = 0.25 * s
    q = np.array([w, x, y, z])
    return q / np.linalg.norm(q)


def fmt(v) -> str:
    if hasattr(v, "__iter__"):
        return " ".join(f"{x:.6g}" for x in v)
    return f"{v:.6g}"


def main():
    assets_dir = ROOT / "assets"
    assets_dir.mkdir(exist_ok=True)

    # Build role-tagged list of components (mm units preserved).
    parts = []
    for c in ASSEMBLY["components"]:
        role = ROLE_BY_RAW.get(c["raw_name"])
        if role is None:
            raise SystemExit(f"unmapped component: {c['raw_name']!r}")
        T = np.array(c["transform_mm"])
        pos_m = T[:3, 3] / 1000.0
        R = T[:3, :3]
        quat = mat_to_quat(R)
        # Copy STL with ASCII role-name
        src = ROOT / c["stl"]
        dst = assets_dir / f"{role}.stl"
        shutil.copyfile(src, dst)
        parts.append({
            "role": role,
            "is_wheel": role in WHEEL_ROLES,
            "pos_m": pos_m,
            "quat": quat,
            "bbox_local_mm": c["bbox_local_mm"],
        })

    wheels = [p for p in parts if p["is_wheel"]]
    chassis = [p for p in parts if not p["is_wheel"]]

    # Wheel radius (m): from local-frame bbox, the wheel diameter is along
    # local X and Z (both ~101 mm); local Y is the axle width (~65.5 mm).
    wb = wheels[0]["bbox_local_mm"]
    diam_mm = max(wb["max"][0] - wb["min"][0], wb["max"][2] - wb["min"][2])
    wheel_radius = diam_mm / 2.0 / 1000.0
    print(f"wheel radius = {wheel_radius:.4f} m  (diameter {diam_mm:.1f} mm)")

    # Chassis base z so the wheels just touch the ground.
    # Chassis frame Z=0 sits at the wheel-hub plane; ground = -wheel_radius.
    chassis_z = wheel_radius + 0.001  # tiny clearance

    # Emit MJCF.
    asset_lines = ['    <mesh name="{role}" file="assets/{role}.stl" scale="0.001 0.001 0.001"/>'.format(role=p["role"])
                   for p in parts]

    chassis_geoms = []
    for p in chassis:
        chassis_geoms.append(
            f'      <geom type="mesh" mesh="{p["role"]}" pos="{fmt(p["pos_m"])}" '
            f'quat="{fmt(p["quat"])}" class="chassis"/>'
        )

    wheel_blocks = []
    for p in wheels:
        # Body at the wheel's transform; wheel mesh in body-local frame.
        # Hinge axis = wheel-local Y = body-local (0,1,0).
        wheel_blocks.append(f"""      <body name="{p['role']}" pos="{fmt(p['pos_m'])}" quat="{fmt(p['quat'])}">
        <inertial pos="0 0 0" mass="0.8" diaginertia="0.0009 0.0014 0.0009"/>
        <joint name="{p['role']}_joint" type="hinge" axis="0 1 0" damping="0.05" frictionloss="0.01"/>
        <geom type="mesh" mesh="{p['role']}" class="wheel_visual"/>
        <geom name="{p['role']}_tire" type="cylinder" size="{fmt([wheel_radius, 0.0327])}" quat="0.7071068 0.7071068 0 0" class="wheel_collision"/>
      </body>""")

    # Right-side wheels (X=+80) have their hinge axis pointing along chassis
    # -X; left-side wheels (X=-80) along chassis +X. To make every actuator's
    # positive ctrl correspond to "roll the robot forward (+Y)", flip the
    # sign on the left motors via gear=-1.
    actuator_lines = []
    for role in ["wheel_fl", "wheel_fr", "wheel_bl", "wheel_br"]:
        gear = -1 if role.endswith("l") else 1
        actuator_lines.append(
            f'    <motor name="{role}_motor" joint="{role}_joint" ctrlrange="-3 3" gear="{gear}"/>'
        )

    xml = f"""<?xml version="1.0" ?>
<mujoco model="ddsm115_4wd">
  <!-- Generated from Waveshare DDSM115 4WD-A STEP assembly.
       Source: https://www.waveshare.com/wiki/DDSM115
       STEP units are mm; converted to meters via mesh scale=0.001.
       Chassis frame: +X lateral, +Y fore (long axis), +Z up.
       Wheels rotate about each wheel's body-local Y axis. -->

  <compiler angle="radian" autolimits="true" meshdir="." texturedir="."/>
  <option timestep="0.002" integrator="implicitfast" gravity="0 0 -9.81"/>

  <default>
    <default class="chassis">
      <geom contype="1" conaffinity="1" group="2" density="500" rgba="0.7 0.72 0.75 1"/>
    </default>
    <default class="wheel_visual">
      <geom contype="0" conaffinity="0" group="2" density="0" rgba="0.2 0.2 0.22 1"/>
    </default>
    <default class="wheel_collision">
      <!-- Cylinder collider for the tire so contact is robust and cheap.
           Higher friction along the rolling direction. -->
      <geom contype="1" conaffinity="1" group="3" density="800"
            friction="1.2 0.01 0.001" rgba="0 0 0 0"/>
    </default>
  </default>

  <asset>
    <texture name="grid" type="2d" builtin="checker" rgb1="0.25 0.27 0.30" rgb2="0.18 0.20 0.22"
             width="512" height="512"/>
    <material name="grid" texture="grid" texrepeat="20 20" reflectance="0.05"/>
{chr(10).join(asset_lines)}
  </asset>

  <worldbody>
    <light pos="0 0 3" dir="0 0 -1" diffuse="0.8 0.8 0.8"/>
    <geom name="floor" type="plane" size="5 5 0.05" material="grid"
          friction="1.2 0.005 0.0001"/>

    <body name="base_link" pos="0 0 {chassis_z:.5f}">
      <freejoint name="root"/>
      <!-- chassis assembly geometry, transforms baked relative to base_link -->
{chr(10).join(chassis_geoms)}
      <!-- four wheels -->
{chr(10).join(wheel_blocks)}
    </body>
  </worldbody>

  <actuator>
{chr(10).join(actuator_lines)}
  </actuator>

  <sensor>
    <jointvel name="wheel_fl_vel" joint="wheel_fl_joint"/>
    <jointvel name="wheel_fr_vel" joint="wheel_fr_joint"/>
    <jointvel name="wheel_bl_vel" joint="wheel_bl_joint"/>
    <jointvel name="wheel_br_vel" joint="wheel_br_joint"/>
    <framepos name="base_pos" objtype="body" objname="base_link"/>
    <framequat name="base_quat" objtype="body" objname="base_link"/>
  </sensor>
</mujoco>
"""

    out = ROOT / "ddsm115_4wd.xml"
    out.write_text(xml)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
