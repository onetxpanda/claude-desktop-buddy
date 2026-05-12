"""Inspect STEP assembly: list named shapes (parts) and per-part bbox/volume."""
import sys
from pathlib import Path

from OCP.STEPCAFControl import STEPCAFControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.TDF import TDF_LabelSequence
from OCP.TopoDS import TopoDS_Shape
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp


def name_of(tool, label):
    from OCP.TDataStd import TDataStd_Name
    n = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), n):
        return n.Get().ToExtString()
    return "<unnamed>"


def inspect(step_path: Path):
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), doc)

    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetColorMode(True)
    reader.SetLayerMode(True)
    status = reader.ReadFile(str(step_path))
    print(f"\n=== {step_path.name} ReadFile status={status}")
    reader.Transfer(doc)

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    labels = TDF_LabelSequence()
    shape_tool.GetFreeShapes(labels)
    print(f"Free shapes (top-level): {labels.Length()}")

    # Walk top-level + their components
    for i in range(1, labels.Length() + 1):
        lab = labels.Value(i)
        nm = name_of(shape_tool, lab)
        shp = shape_tool.GetShape_s(lab)
        bbox = Bnd_Box()
        try:
            BRepBndLib.Add_s(shp, bbox)
            xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
            dx, dy, dz = xmax - xmin, ymax - ymin, zmax - zmin
        except Exception as e:
            dx = dy = dz = -1
        print(f"  [{i:3d}] {nm}  bbox(mm)={dx:.1f} x {dy:.1f} x {dz:.1f}  isAssembly={shape_tool.IsAssembly_s(lab)}")
        if shape_tool.IsAssembly_s(lab):
            comps = TDF_LabelSequence()
            shape_tool.GetComponents_s(lab, comps)
            print(f"        components: {comps.Length()}")
            for j in range(1, min(comps.Length(), 50) + 1):
                cl = comps.Value(j)
                cn = name_of(shape_tool, cl)
                print(f"        - [{j:3d}] {cn}")
            if comps.Length() > 50:
                print(f"        ... and {comps.Length() - 50} more")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        inspect(Path(p))
