"""Decompose the 4WD-A STEP assembly into per-component STL meshes (mm).

For each top-level component of the assembly, write a single STL into
`meshes/`. Each mesh is in the COMPONENT'S LOCAL FRAME (assembly placement
not baked in), so MuJoCo can position it with body pos/quat. We also write
a JSON sidecar with each component's placement (pos in mm, axis-angle in
chassis frame) and bounding box so the XML generator can build joints.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDF import TDF_LabelSequence, TDF_Label
from OCP.TDataStd import TDataStd_Name
from OCP.TopoDS import TopoDS_Shape
from OCP.TopLoc import TopLoc_Location
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE
from OCP.TopoDS import TopoDS
from OCP.BRep import BRep_Tool
from OCP.TopAbs import TopAbs_Orientation
from OCP.gp import gp_Trsf

import trimesh


def label_name(label: TDF_Label) -> str:
    n = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), n):
        return n.Get().ToExtString()
    return ""


def trsf_to_matrix(trsf: gp_Trsf) -> np.ndarray:
    """4x4 transform matrix from a gp_Trsf."""
    M = np.eye(4)
    for r in range(3):
        for c in range(4):
            M[r, c] = trsf.Value(r + 1, c + 1)
    return M


def tessellate_shape(shape: TopoDS_Shape, linear_deflection_mm: float = 0.3,
                     angular_deflection: float = 0.5) -> trimesh.Trimesh:
    """Tessellate an OCC shape into a trimesh.Trimesh in the shape's local frame."""
    BRepMesh_IncrementalMesh(shape, linear_deflection_mm, False, angular_deflection, True)

    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None:
            trsf = loc.Transformation()
            offset = len(verts)
            nb = tri.NbNodes()
            for i in range(1, nb + 1):
                p = tri.Node(i).Transformed(trsf)
                verts.append((p.X(), p.Y(), p.Z()))
            reversed_ = face.Orientation() == TopAbs_Orientation.TopAbs_REVERSED
            for i in range(1, tri.NbTriangles() + 1):
                t = tri.Triangle(i)
                a, b, c = t.Value(1), t.Value(2), t.Value(3)
                if reversed_:
                    a, c = c, a
                faces.append((offset + a - 1, offset + b - 1, offset + c - 1))
        exp.Next()

    if not verts:
        return trimesh.Trimesh()
    return trimesh.Trimesh(vertices=np.asarray(verts, dtype=np.float64),
                           faces=np.asarray(faces, dtype=np.int64),
                           process=True)


def safe(name: str) -> str:
    """Sanitize a component name into a filename-safe ascii slug."""
    out = []
    for ch in name:
        if ch.isalnum() or ch in "-_":
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out).strip("_")
    return s or "part"


def main(step_path: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    mesh_dir = out_dir / "meshes"
    mesh_dir.mkdir(exist_ok=True)

    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), doc)

    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    print(f"Reading {step_path} ...")
    reader.ReadFile(str(step_path))
    reader.Transfer(doc)

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    free = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free)
    assert free.Length() >= 1
    root = free.Value(1)
    print(f"Root: {label_name(root)} (assembly={shape_tool.IsAssembly_s(root)})")

    comps = TDF_LabelSequence()
    shape_tool.GetComponents_s(root, comps)
    print(f"Top-level components: {comps.Length()}")

    # Cache one tessellated mesh per referred prototype label (mesh is in
    # prototype local frame). Then for each component we copy + transform.
    proto_cache: dict[int, trimesh.Trimesh] = {}

    entries = []
    used_names: dict[str, int] = {}

    for j in range(1, comps.Length() + 1):
        comp = comps.Value(j)
        comp_name = label_name(comp) or f"comp_{j}"

        # Component label refers to a prototype label
        ref = TDF_Label()
        if not shape_tool.GetReferredShape_s(comp, ref):
            ref = comp

        proto_name = label_name(ref) or comp_name
        proto_shape = shape_tool.GetShape_s(ref)

        # Tessellate prototype once
        key = ref.Tag()
        if key not in proto_cache:
            print(f"  Tessellating prototype '{proto_name}' (tag={key}) ...")
            proto_cache[key] = tessellate_shape(proto_shape)
        mesh = proto_cache[key].copy()

        # Get the placement of this component relative to the root assembly
        loc = shape_tool.GetLocation_s(comp)
        trsf = loc.Transformation()
        T = trsf_to_matrix(trsf)
        # OCC STEP units are mm; keep mm here, convert to meters when emitting MuJoCo.

        # Save the mesh in its LOCAL frame (no transform baked in) so MuJoCo
        # body pos/quat handle the placement, which is convenient for joints.
        # We separately record the transform.
        base = safe(comp_name)
        n = used_names.get(base, 0) + 1
        used_names[base] = n
        unique = base if n == 1 else f"{base}_{n}"
        stl_path = mesh_dir / f"{unique}.stl"
        mesh.export(stl_path)

        # Component bbox in component-local frame (mm)
        if len(mesh.vertices):
            lo = mesh.vertices.min(axis=0).tolist()
            hi = mesh.vertices.max(axis=0).tolist()
        else:
            lo = hi = [0.0, 0.0, 0.0]

        entries.append({
            "name": unique,
            "raw_name": comp_name,
            "proto_name": proto_name,
            "stl": str(stl_path.relative_to(out_dir)),
            "transform_mm": T.tolist(),
            "bbox_local_mm": {"min": lo, "max": hi},
        })

    with (out_dir / "assembly.json").open("w") as f:
        json.dump({"source": str(step_path), "components": entries}, f, indent=2)
    print(f"Wrote {len(entries)} STLs and assembly.json to {out_dir}")


if __name__ == "__main__":
    step = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("raw/chassis/DDSM115 4WD-A.step")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(".")
    main(step, out)
