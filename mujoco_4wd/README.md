# DDSM115 4WD-A MuJoCo model

A MuJoCo model of the Waveshare [DDSM115 4WD-A](https://www.waveshare.com/wiki/DDSM115)
robot platform — four DDSM115 direct-drive hub motors mounted in 2020-extrusion
corner brackets, with top and bottom plates.

The model is reconstructed directly from the manufacturer's open-source STEP
files; no geometry was authored by hand.

## Files

- `ddsm115_4wd.xml` — the MJCF model.
- `assets/*.stl` — 18 tessellated parts (4 wheels, 4 CNC corner brackets,
  4 aluminum extrusions, 4 side supports, top plate, bottom plate). All in
  millimeters; the model scales them to meters via `<mesh scale="0.001 ...">`.
- `assembly.json` — the placement of every component (4x4 transform + bbox)
  extracted from the STEP assembly. Used by `build_model.py`.
- `step_to_meshes.py` — reads the STEP, walks the top-level components, and
  emits one STL per component plus `assembly.json`. Uses `cadquery-ocp`
  (OpenCascade Python bindings) for STEP parsing and tessellation.
- `build_model.py` — reads `assembly.json`, copies meshes to `assets/` with
  ASCII-safe names, and emits the MJCF.
- `inspect_step.py` — diagnostic; lists the components in any STEP file.
- `Makefile` — `make` pulls the STEP zips from Waveshare and runs the
  whole pipeline end to end.

## Model summary

```
nq = 11  (7 free-joint + 4 wheel hinges)
nu = 4   (one motor per wheel)
bodies = 6 (world, base_link, 4 wheels)
total mass ≈ 3.7 kg
wheel radius = 0.0503 m
wheel base   = 0.20 m (Y)
track width  = 0.16 m (X)
```

Convention (chassis frame, MuJoCo `base_link`):

- `+Y` = forward (long axis of the chassis; wheels roll along Y).
- `+X` = right.
- `+Z` = up.

Each motor's positive `ctrl` rolls its wheel forward (+Y in body frame). The
gear sign accounts for the fact that left-side wheels have their hinge axis
along chassis `+X` and right-side wheels along chassis `-X`.

Differential drive:

| desired motion | wheel_fl | wheel_fr | wheel_bl | wheel_br |
|----------------|----------|----------|----------|----------|
| forward        | +        | +        | +        | +        |
| reverse        | -        | -        | -        | -        |
| turn left      | -        | +        | -        | +        |
| turn right     | +        | -        | +        | -        |

## Regenerate from scratch

```
pip install cadquery-ocp trimesh mujoco numpy
make
make test
```

`make raw` downloads two zips (~16 MB) from `files.waveshare.com`. `make meshes`
tessellates the 60 MB chassis STEP assembly (~30 s). `make model` writes the
MJCF.

## Source

- STEP: `DDSM115_4WD-A.zip` from
  <https://files.waveshare.com/upload/2/23/DDSM115_4WD-A.zip>
- Linked from <https://www.waveshare.com/wiki/DDSM115> ("Open Source Structure").

The wheel motor STEP alone is also available as `DDSM115_STEP.zip` from the
same wiki page; the 4WD-A assembly already contains four full DDSM115
instances so we do not need the standalone wheel STEP for this model.
