"""B00 export qualification. Every dimension below is invented; no drawings read.

Run with the isolated CadQuery interpreter; outputs default to testing/runs/A13-cad.
This is a capability probe, not the M13 product builder.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import math
import os
from pathlib import Path
import platform
import struct
import subprocess
import sys
import traceback


ROOT = Path(__file__).resolve().parents[3]
LENGTH, WIDTH, THICKNESS = 100.0, 60.0, 5.0  # invented mm
MAIN_DIAMETER, PATTERN_DIAMETER = 10.0, 6.0  # invented mm
PATTERN_CENTRES = [(-25.0, 15.0), (25.0, 15.0)]  # invented mm
EXPECTED_VOLUME = LENGTH * WIDTH * THICKNESS - math.pi * THICKNESS * (
    (MAIN_DIAMETER / 2) ** 2 + 2 * (PATTERN_DIAMETER / 2) ** 2
)
VOLUME_TOL_MM3 = 1e-6
STEP_VOLUME_TOL_MM3 = 1e-5
CAD_BOUNDS_TOL_MM = 1e-6
GLB_BOUNDS_TOL_M = 1e-7
MESH_VOLUME_REL_TOL = 0.001
CAD_BOUNDS = [[-50.0, -30.0, 0.0], [50.0, 30.0, 5.0]]
# OCCT/CadQuery GLTF export changes Z-up (x,y,z) to Y-up (x,z,-y).
GLB_BOUNDS = [[-0.05, 0.0, -0.03], [0.05, 0.005, 0.03]]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def bounds(shape):
    box = shape.BoundingBox()
    return [[box.xmin, box.ymin, box.zmin], [box.xmax, box.ymax, box.zmax]]


def artifact(path):
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def inspect_glb(path, np):
    data = path.read_bytes()
    require(len(data) >= 20, "GLB too short")
    magic, container_version, length = struct.unpack_from("<4sII", data)
    require(magic == b"glTF" and container_version == 2 and length == len(data),
            "GLB magic/version/length mismatch")
    chunks, offset = [], 12
    while offset < length:
        require(offset + 8 <= length, "Truncated chunk header")
        size, kind = struct.unpack_from("<II", data, offset)
        offset += 8
        require(size % 4 == 0 and offset + size <= length, "Invalid chunk size/alignment")
        chunks.append((kind, data[offset:offset + size]))
        offset += size
    require([c[0] for c in chunks] == [0x4E4F534A, 0x004E4942],
            "Expected self-contained JSON then BIN chunks")
    doc = json.loads(chunks[0][1].decode("utf-8"))
    binary = chunks[1][1]
    require(doc["asset"]["version"] == "2.0", "JSON asset version must be 2.0")
    require(bool(doc.get("meshes")) and bool(doc.get("accessors")), "Missing geometry")
    require(len(doc["buffers"]) == 1 and "uri" not in doc["buffers"][0], "External buffer")
    require(0 <= len(binary) - doc["buffers"][0]["byteLength"] <= 3, "Invalid BIN padding")
    require(not doc.get("images") and not doc.get("textures"), "Expected texture-free GLB")
    require(not doc.get("extensionsRequired"), "Unexpected required extension")

    types = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2", 5125: "<u4", 5126: "<f4"}
    widths = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}

    def accessor(index):
        acc = doc["accessors"][index]
        require("sparse" not in acc, "Sparse accessor unavailable in this probe")
        view = doc["bufferViews"][acc["bufferView"]]
        require(view["buffer"] == 0 and acc["count"] > 0, "Bad accessor reference/count")
        dtype, width = np.dtype(types[acc["componentType"]]), widths[acc["type"]]
        stride = view.get("byteStride", dtype.itemsize * width)
        local_start = acc.get("byteOffset", 0)
        local_end = local_start + (acc["count"] - 1) * stride + dtype.itemsize * width
        start = view.get("byteOffset", 0) + local_start
        require(stride >= dtype.itemsize * width and local_end <= view["byteLength"],
                "Accessor exceeds bufferView")
        require(view.get("byteOffset", 0) + view["byteLength"] <= doc["buffers"][0]["byteLength"],
                "bufferView exceeds buffer")
        result = np.ndarray((acc["count"], width), dtype=dtype, buffer=binary,
                            offset=start, strides=(stride, dtype.itemsize)).copy()
        require(bool(np.isfinite(result).all()), "Non-finite accessor values")
        return result

    def matrix(node):
        if "matrix" in node:
            return np.array(node["matrix"]).reshape(4, 4, order="F")
        x, y, z, w = node.get("rotation", [0, 0, 0, 1])
        rotation = np.array([
            [1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
            [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
            [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)],
        ])
        result = np.eye(4)
        result[:3, :3] = rotation @ np.diag(node.get("scale", [1, 1, 1]))
        result[:3, 3] = node.get("translation", [0, 0, 0])
        return result

    points, used_materials, triangles = [], set(), 0
    signed_volume_m3 = 0.0

    def visit(index, parent, ancestors):
        nonlocal triangles, signed_volume_m3
        require(index not in ancestors, "Cycle in scene graph")
        node = doc["nodes"][index]
        world = parent @ matrix(node)
        if "mesh" in node:
            for primitive in doc["meshes"][node["mesh"]]["primitives"]:
                require(primitive.get("mode", 4) == 4, "Expected triangles")
                positions = accessor(primitive["attributes"]["POSITION"]).astype(float)
                position_acc = doc["accessors"][primitive["attributes"]["POSITION"]]
                require(np.allclose(positions.min(axis=0), position_acc["min"], rtol=0, atol=1e-7)
                        and np.allclose(positions.max(axis=0), position_acc["max"], rtol=0, atol=1e-7),
                        "POSITION min/max disagrees with actual binary data")
                transformed = (world @ np.column_stack((positions, np.ones(len(positions)))).T).T[:, :3]
                points.append(transformed)
                indices = accessor(primitive["indices"]).reshape(-1).astype(int)
                require(len(indices) % 3 == 0 and indices.min() >= 0 and indices.max() < len(positions),
                        "Invalid triangle indices")
                faces = transformed[indices.reshape(-1, 3)]
                signed_volume_m3 += float(np.einsum("ij,ij->i", faces[:, 0],
                                         np.cross(faces[:, 1], faces[:, 2])).sum() / 6)
                triangles += len(faces)
                used_materials.add(primitive["material"])
        for child in node.get("children", []):
            visit(child, world, ancestors | {index})

    for index in doc["scenes"][doc.get("scene", 0)]["nodes"]:
        visit(index, np.eye(4), set())
    require(bool(points) and triangles > 0, "No scene geometry")
    positions = np.concatenate(points)
    actual_bounds = np.stack((positions.min(axis=0), positions.max(axis=0)))
    max_bounds_error = float(np.max(np.abs(actual_bounds - np.array(GLB_BOUNDS))))
    colours = [doc["materials"][i]["pbrMetallicRoughness"]["baseColorFactor"]
               for i in sorted(used_materials)]
    require(bool(colours) and all(len(c) == 4 and 0 < c[0] < 1 and
            max(c[:3]) - min(c[:3]) < 1e-7 and abs(c[3] - 1) < 1e-7 for c in colours),
            "Material must be opaque neutral grey")
    mesh_volume_mm3 = abs(signed_volume_m3) * 1e9
    relative_volume_error = abs(mesh_volume_mm3 - EXPECTED_VOLUME) / EXPECTED_VOLUME
    result = {
        **artifact(path), "header": {"magic": magic.decode(), "version": container_version, "length": length},
        "asset": doc["asset"], "chunks": [{"type": k, "bytes": len(v)} for k, v in chunks],
        "meshes": len(doc["meshes"]), "accessors": len(doc["accessors"]),
        "triangles": triangles, "external_resources": False, "base_color_factors": colours,
        "world_bounds_m": actual_bounds.tolist(), "expected_world_bounds_m": GLB_BOUNDS,
        "max_bounds_error_m": max_bounds_error, "bounds_tolerance_m": GLB_BOUNDS_TOL_M,
        "mesh_volume_mm3": mesh_volume_mm3, "mesh_volume_relative_error": relative_volume_error,
        "mesh_volume_relative_tolerance": MESH_VOLUME_REL_TOL,
        "units": "CadQuery mm -> glTF m (0.001); Z-up -> Y-up: (x,y,z) -> (x,z,-y)",
    }
    require(max_bounds_error <= GLB_BOUNDS_TOL_M, f"GLB bounds mismatch: {result}")
    require(relative_volume_error <= MESH_VOLUME_REL_TOL, f"GLB mesh volume mismatch: {result}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "testing/runs/A13-cad")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    require(output.is_relative_to(ROOT / "testing/runs"), "Outputs must stay in this worktree's testing/runs")
    output.mkdir(parents=True, exist_ok=True)
    temp = ROOT / "testing/tmp/A13-cad"
    temp.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = os.environ["TMP"] = str(temp)
    for variable, relative in {
        "MPLCONFIGDIR": "testing/cache/matplotlib",
        "NUMBA_CACHE_DIR": "testing/cache/numba",
        "XDG_CACHE_HOME": "testing/cache",
    }.items():
        os.environ[variable] = str(ROOT / relative)
    sys.dont_write_bytecode = True
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    # Windows' DLL loader rejected the long worktree path even with a short
    # environment name. Use an existing NTFS 8.3 alias to the SAME interpreter.
    # This neither creates an alias nor changes files or configuration elsewhere.
    if os.name == "nt":
        import ctypes

        short = ctypes.create_unicode_buffer(32768)
        size = ctypes.windll.kernel32.GetShortPathNameW(sys.executable, short, len(short))
        if 0 < size < len(short) and short.value.casefold() != sys.executable.casefold():
            require(os.path.samefile(short.value, sys.executable), "Interpreter alias must identify the same file")
            print(f"Using existing Windows short-path interpreter alias: {short.value}", flush=True)
            return subprocess.run([short.value, str(Path(__file__).resolve()), *sys.argv[1:]], cwd=ROOT).returncode
    result = {
        "schema": "a13-cad-qualification/v1", "outcome": "FAIL",
        "completed_at": "", "synthetic": True,
        "source": "All dimensions are invented test values, not taken from any drawing. No source drawings read.",
        "geometry_mm": {"plate": [LENGTH, WIDTH, THICKNESS], "main_hole_diameter": MAIN_DIAMETER,
                        "main_hole_centre": [0, 0], "pattern_hole_diameter": PATTERN_DIAMETER,
                        "pattern_hole_centres": PATTERN_CENTRES},
        "analytic_volume_mm3": EXPECTED_VOLUME,
        "analytic_volume_formula": "100*60*5 - pi*5*(5**2 + 2*3**2)",
        "checks": [],
    }

    def check(name, operation):
        try:
            evidence = operation()
            result[name] = evidence
            result["checks"].append({"name": name, "outcome": "PASS"})
            print(f"PASS {name}: {json.dumps(evidence)}", flush=True)
        except Exception as error:
            result[name] = {"outcome": "FAIL", "error": str(error), "traceback": traceback.format_exc()}
            result["checks"].append({"name": name, "outcome": "FAIL"})
            print(f"FAIL {name}: {traceback.format_exc()}", flush=True)

    try:
        import cadquery as cq
        import numpy as np
        import OCP

        result["environment"] = {
            "python": platform.python_version(), "python_executable": sys.executable,
            "platform": platform.platform(), "cadquery": version("cadquery"),
            "cadquery_ocp": version("cadquery-ocp"), "ocp_module": OCP.__version__,
            "numpy": version("numpy"),
            "windows_path_strategy": "Existing NTFS 8.3 interpreter alias when available; no files relocated",
        }
        # Independent global XY cuts avoid any workplane centre-of-mass relocation.
        plate = cq.Workplane("XY").box(LENGTH, WIDTH, THICKNESS, centered=(True, True, False))
        plate = plate.cut(cq.Workplane("XY").circle(MAIN_DIAMETER / 2).extrude(THICKNESS))
        plate = plate.cut(cq.Workplane("XY").pushPoints(PATTERN_CENTRES)
                          .circle(PATTERN_DIAMETER / 2).extrude(THICKNESS))
        shape = plate.val()

        def solid_check():
            actual_bounds, volume = bounds(shape), shape.Volume()
            require(shape.isValid() and len(shape.Solids()) == 1, "Expected one valid solid")
            require(np.allclose(actual_bounds, CAD_BOUNDS, atol=CAD_BOUNDS_TOL_MM, rtol=0), "CAD bounds mismatch")
            require(abs(volume - EXPECTED_VOLUME) <= VOLUME_TOL_MM3, "CAD volume mismatch")
            return {"valid": True, "solid_count": len(shape.Solids()), "bounds_mm": actual_bounds,
                    "expected_bounds_mm": CAD_BOUNDS, "bounds_tolerance_mm": CAD_BOUNDS_TOL_MM,
                    "volume_mm3": volume, "volume_error_mm3": abs(volume - EXPECTED_VOLUME),
                    "volume_tolerance_mm3": VOLUME_TOL_MM3}

        check("cad_solid", solid_check)

        def glb_check():
            path = output / "synthetic-plate.glb"
            assembly = cq.Assembly(name="invented_B00_test_plate")
            # Qualified exporter retains coordinate numbers: explicitly convert
            # a COPY from mm to m. STEP and the analytic CAD solid stay in mm.
            assembly.add(shape.scale(0.001), name="invented_plate", color=cq.Color(0.6, 0.6, 0.6, 1.0))
            assembly.export(str(path), exportType="GLTF", tolerance=0.00005, angularTolerance=0.1)
            return {"export_api": "Assembly.add(shape.scale(0.001), color=cq.Color(0.6,0.6,0.6,1)); Assembly.export(path.glb, exportType='GLTF', tolerance=0.00005, angularTolerance=0.1)",
                    "export_shape_scale": 0.001, "tessellation_linear_tolerance_m": 0.00005,
                    "tessellation_angular_tolerance_rad": 0.1,
                    "requested_cq_color": [0.6, 0.6, 0.6, 1.0], **inspect_glb(path, np)}

        check("glb", glb_check)

        def step_check():
            path = output / "synthetic-plate.step"
            cq.exporters.export(plate, str(path), exportType="STEP")
            imported = cq.importers.importStep(str(path)).val()
            volume, actual_bounds = imported.Volume(), bounds(imported)
            require(imported.isValid() and len(imported.Solids()) == 1, "STEP must re-import one valid solid")
            require(abs(volume - EXPECTED_VOLUME) <= STEP_VOLUME_TOL_MM3, "STEP analytic volume mismatch")
            require(abs(volume - shape.Volume()) <= STEP_VOLUME_TOL_MM3, "STEP round-trip volume mismatch")
            require(np.allclose(actual_bounds, CAD_BOUNDS, atol=CAD_BOUNDS_TOL_MM, rtol=0), "STEP bounds mismatch")
            return {**artifact(path), "export_api": "cq.exporters.export(plate, path.step, exportType='STEP')",
                    "import_api": "cq.importers.importStep(path.step)", "units": "mm",
                    "valid": True, "solid_count": len(imported.Solids()), "volume_mm3": volume,
                    "analytic_error_mm3": abs(volume - EXPECTED_VOLUME),
                    "round_trip_error_mm3": abs(volume - shape.Volume()),
                    "volume_tolerance_mm3": STEP_VOLUME_TOL_MM3, "bounds_mm": actual_bounds,
                    "bounds_tolerance_mm": CAD_BOUNDS_TOL_MM}

        check("step", step_check)
        result["outcome"] = "PASS" if all(c["outcome"] == "PASS" for c in result["checks"]) else "FAIL"
    except Exception:
        result["diagnostics"] = traceback.format_exc()
        print(result["diagnostics"], flush=True)
    result["completed_at"] = datetime.now(timezone.utc).isoformat()
    (output / "measurements.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{result['outcome']}: {output / 'measurements.json'}", flush=True)
    return 0 if result["outcome"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
