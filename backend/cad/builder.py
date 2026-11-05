"""Flat-part B-reps in mm, GLB meshes in metres, immutable cached exports."""
from __future__ import annotations

import copy
import hashlib
import itertools
import json
import math
import re
import shutil
import struct
from pathlib import Path

from backend.paths import GENERATED, ROOT, inside

VERSION = "flat-part-14"
NOTICE = "Reconstruction from 2D drawing. Not the original CAD model."


def _read(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _write(path, value):
    path = inside(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Unknown(ValueError):
    pass


def _value(field, name, evidence=None):
    if isinstance(field, dict):
        if field.get("state") == "unknown" or field.get("confidence") == "unsure":
            raise Unknown(name)
        if field.get("state") == "options":
            raise Unknown(name + " has unresolved options")
        if "value" not in field or field["value"] is None:
            raise Unknown(name)
        return field["value"]
    if field is None:
        raise Unknown(name)
    if isinstance(field, (int, float)) and not evidence:
        raise Unknown(name + " has no evidence IDs")
    return field


def _num(field, name, evidence=None, positive=False):
    value = _value(field, name, evidence)
    if isinstance(field, dict) and field.get("method") != "human_decision" and not (field.get("fact_ids") or field.get("fact_id") or evidence):
        raise Unknown(name + " has no evidence IDs")
    if isinstance(value, bool):
        raise Unknown(name + " is not numeric")
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise Unknown(name + " is not numeric") from None
    if not math.isfinite(value) or (positive and value <= 0):
        raise Unknown(name + " is invalid")
    return value


def _angle(field, name, evidence=None):
    value = _value(field, name, evidence)
    cardinal = {"x":0, "horizontal":0, "y":90, "vertical":90}
    if str(value).lower() in cardinal:
        return cardinal[str(value).lower()]
    return _num(field, name, evidence)


def _options(template):
    fields = []
    def walk(item, path=()):
        if isinstance(item, dict):
            if item.get("state") == "options":
                values = item.get("options", [])
                if not values:
                    raise Unknown(".".join(map(str, path)) + " has no options")
                fields.append((path, values))
            else:
                for key, val in item.items():
                    if key not in {"readers", "review", "original", "note", "evidence"}:
                        walk(val, path + (key,))
        elif isinstance(item, list):
            for index, val in enumerate(item):
                walk(val, path + (index,))
    for key in ("outline", "thickness", "features"):
        if key in template:
            walk(template[key], (key,))
    total = math.prod(len(options) for _, options in fields)
    if total > 4:
        raise Unknown("Too many possible readings to build in 3D (maximum 4)")
    for choices in itertools.product(*(values for _, values in fields)):
        variant = copy.deepcopy(template)
        selected = {}
        for (path, _), choice in zip(fields, choices):
            parent = variant
            for key in path[:-1]:
                parent = parent[key]
            old = parent[path[-1]]
            value = choice.get("value") if isinstance(choice, dict) else choice
            parent[path[-1]] = {**old, **(choice if isinstance(choice, dict) else {}), "state": "known", "value": value}
            selected[".".join(map(str, path))] = value
        yield variant, selected


def _positions(feature):
    evidence = feature.get("fact_ids") or feature.get("fact_id")
    x = _num(feature.get("x"), "x", evidence)
    y = _num(feature.get("y"), "y", evidence)
    pattern = feature.get("pattern")
    if not pattern:
        return [(x, y)]
    n = _num(pattern.get("count"), "pattern.count", evidence, True)
    if not n.is_integer() or n > 1000:
        raise Unknown("pattern.count is invalid")
    n = int(n)
    if pattern.get("type") == "circle":
        r = _num(pattern.get("radius"), "pattern.radius", evidence, True)
        start = _num(pattern.get("start_angle"), "pattern.start_angle", evidence)
        return [(x + r * math.cos(math.radians(start + 360*i/n)), y + r * math.sin(math.radians(start + 360*i/n))) for i in range(n)]
    if pattern.get("type") == "row":
        spacing = _num(pattern.get("spacing"), "pattern.spacing", evidence, True)
        angle = math.radians(_angle(pattern.get("direction"), "pattern.direction", evidence))
        return [(x+i*spacing*math.cos(angle), y+i*spacing*math.sin(angle)) for i in range(n)]
    raise Unknown("unsupported pattern " + str(pattern.get("type")))


def _validate_essential(template):
    """Reject missing main geometry before a cache hit or optional CAD import."""
    if template.get("cad_ready") is False:
        fields = template.get("blocking_fields") or ["cad_ready"]
        raise Unknown("Essential geometry unresolved: " + ", ".join(map(str, fields)))
    if template.get("blocking_fields"):
        raise Unknown("Essential geometry unresolved: " + ", ".join(map(str, template["blocking_fields"])))
    eligibility = template.get("cad_eligibility")
    if eligibility is not None:
        value = _value(eligibility, "cad_eligibility")
        if (not isinstance(value, dict) or any(value.get(key) is not True for key in
                ("supported", "constant_thickness", "outline_exact")) or value.get("essential_uncertainty")):
            raise Unknown("Main outline or constant thickness is unsupported by the drawing")
    outline = template.get("outline", {})
    if outline.get("state") == "unknown" or outline.get("confidence") == "unsure":
        raise Unknown("outline")
    evidence = outline.get("fact_ids") or outline.get("fact_id")
    kind = _value(outline.get("type"), "outline.type", evidence)
    if kind not in ("rectangle", "circle", "ring"):
        raise Unknown("unsupported outline " + str(kind))
    keys = ["length", "width"] if kind == "rectangle" else ["outer_diameter"] + (["inner_diameter"] if kind == "ring" else [])
    dimensions = {key: _num(outline.get(key, outline.get("diameter") if key == "outer_diameter" else None),
                             "outline." + key, evidence, True) for key in keys}
    if kind == "ring" and dimensions["inner_diameter"] >= dimensions["outer_diameter"]:
        raise Unknown("inner diameter must be smaller than outer diameter")
    _num(template.get("thickness"), "thickness", template.get("fact_ids"), True)


def feature_inventory(template):
    """Use live reviewable wrappers so human edits cannot leave stale claims."""
    if "features_complete" not in template and "features_omitted" not in template:
        return {"status": template.get("features_status", "unknown"),
                "all_determined": bool(template.get("features_all_determined", False)),
                "notes": list(template.get("omitted_feature_notes", []))}
    try:
        complete = _value(template.get("features_complete"), "features_complete")
    except Unknown:
        complete = None
    try:
        omissions = _value(template.get("features_omitted"), "features_omitted")
    except Unknown:
        omissions = None
    review = template.get("features_review") or {}
    supported = (review.get("state") == "known" and isinstance(review.get("value"), list)) or (not review and isinstance(template.get("features"), list))
    all_determined = supported and complete is True and omissions == []
    partial = supported and complete is False and isinstance(omissions, list) and bool(omissions)
    notes = [str(item.get("description", "Feature")) + ": " + str(item.get("reason", "Not determined"))
             for item in (omissions or []) if isinstance(item, dict)] if isinstance(omissions, list) else []
    return {"status": "complete" if all_determined else "partial" if partial else "unknown",
            "all_determined": all_determined, "notes": notes}


def _corner_clips(feature, outline):
    """Exact full-thickness corner clips; never infer setbacks from a picture."""
    evidence = feature.get("fact_ids") or feature.get("fact_id")
    if _value(outline.get("type"), "outline.type") != "rectangle":
        raise Unknown("corner_chamfer requires a rectangular outline")
    corners = _value(feature.get("corners"), "corners", evidence)
    allowed = {"x_min_y_min": (-1, -1), "x_min_y_max": (-1, 1),
               "x_max_y_min": (1, -1), "x_max_y_max": (1, 1)}
    if not isinstance(corners, list) or not corners or any(not isinstance(c, str) or c not in allowed for c in corners) or len(set(corners)) != len(corners):
        raise Unknown("corners must be a nonempty unique list of rectangle corners")
    oe = outline.get("fact_ids") or outline.get("fact_id")
    length, width = (_num(outline.get(key), "outline." + key, oe, True) for key in ("length", "width"))
    sx, sy = (_num(feature.get(key), key, evidence, True) for key in ("x_setback", "y_setback"))
    if sx >= length / 2 or sy >= width / 2:
        raise Unknown("corner setbacks must be smaller than the rectangle half-dimensions")
    return [[(a * length / 2, b * width / 2),
             (a * (length / 2 - sx), b * width / 2),
             (a * length / 2, b * (width / 2 - sy))] for a, b in (allowed[c] for c in corners)]


def _side_hole(cq, feature, outline, thickness, x, y, through):
    """Side bores use global XY and an explicit evidenced Z center."""
    evidence = feature.get("fact_ids") or feature.get("fact_id")
    if _value(outline.get("type"), "outline.type") != "rectangle":
        raise Unknown("side holes require a rectangular outline")
    if feature.get("kind") != "hole" or _value(feature.get("hole_type"), "hole_type", evidence) not in ("plain", "threaded"):
        raise Unknown("side faces support plain or cosmetic-threaded holes")
    oe = outline.get("fact_ids") or outline.get("fact_id")
    length, width = (_num(outline.get(key), "outline." + key, oe, True) for key in ("length", "width"))
    face = _value(feature.get("face"), "face", evidence)
    z = _num(feature.get("z"), "z", evidence)
    diameter = _num(feature.get("diameter"), "diameter", evidence, True)
    if not 0 < z < thickness:
        raise Unknown("side-hole z must be inside the plate thickness")
    if face.startswith("x_"):
        boundary, span = (-length / 2 if face == "x_min" else length / 2), length
        if abs(x - boundary) > 1e-6 or not -width / 2 < y < width / 2:
            raise Unknown("side-hole entry is not on the specified rectangle face")
        normal, xdir = ((1, 0, 0) if face == "x_min" else (-1, 0, 0)), (0, 1, 0)
    else:
        boundary, span = (-width / 2 if face == "y_min" else width / 2), width
        if abs(y - boundary) > 1e-6 or not -length / 2 < x < length / 2:
            raise Unknown("side-hole entry is not on the specified rectangle face")
        normal, xdir = ((0, 1, 0) if face == "y_min" else (0, -1, 0)), (1, 0, 0)
    depth = span if through else _num(feature.get("depth"), "depth", evidence, True)
    if depth > span:
        raise Unknown("side-hole depth exceeds the body span")
    origin = tuple(v - .001 * n for v, n in zip((x, y, z), normal)) if through else (x, y, z)
    return cq.Workplane(cq.Plane(origin=origin, xDir=xdir, normal=normal)).circle(diameter / 2).extrude(depth + (.002 if through else 0))


def build_shape(template):
    """Return (CadQuery solid, waiting names, omitted details, feature labels)."""
    _validate_essential(template)
    import cadquery as cq
    outline = template.get("outline", {})
    if outline.get("state") == "unknown":
        raise Unknown("outline")
    evidence = outline.get("fact_ids") or outline.get("fact_id")
    t = _num(template.get("thickness"), "thickness", template.get("fact_ids"), True)
    kind = _value(outline.get("type"), "outline.type", evidence)
    if kind == "rectangle":
        length = _num(outline.get("length"), "outline.length", evidence, True)
        width = _num(outline.get("width"), "outline.width", evidence, True)
        shape = cq.Workplane("XY").rect(length, width).extrude(t)
    elif kind in ("circle", "ring"):
        diameter = _num(outline.get("outer_diameter", outline.get("diameter")), "outline.outer_diameter", evidence, True)
        profile = cq.Workplane("XY").circle(diameter/2)
        if kind == "ring":
            inner = _num(outline.get("inner_diameter"), "outline.inner_diameter", evidence, True)
            if inner >= diameter:
                raise Unknown("inner diameter must be smaller than outer diameter")
            profile = profile.circle(inner/2)
        shape = profile.extrude(t)
    else:
        raise Unknown("unsupported outline " + str(kind))
    waiting, omitted, labels = [], [], []
    inventory = feature_inventory(template)
    omitted.extend(inventory["notes"])
    if inventory["status"] in ("partial", "unknown") and ("features_complete" in template or "features_status" in template):
        waiting.append("features_complete")
        if not omitted:
            omitted.append("The full feature inventory has not been determined; this model contains only supported cuts")
    feature_review = template.get("features_review") or {}
    if feature_review.get("state") == "unknown":
        waiting.append("features_review")
        omitted.append("Hole and slot details: " + str(feature_review.get("note") or "the readers could not establish the features confidently; waiting for review"))
    for index, feature in enumerate(template.get("features", [])):
        name = feature.get("name") or feature.get("label") or f"Feature {index+1} ({feature.get('kind', 'unknown')})"
        try:
            if feature.get("state") == "unknown":
                raise Unknown("feature is unknown")
            evidence = feature.get("fact_ids") or feature.get("fact_id")
            if feature.get("kind") == "corner_chamfer":
                clips = _corner_clips(feature, outline)
                candidate = shape
                for points in clips:
                    candidate = candidate.cut(cq.Workplane("XY", origin=(0, 0, -.001)).polyline(points).close().extrude(t + .002))
                if not candidate.val().isValid() or candidate.val().Volume() <= 0 or shape.val().Volume() - candidate.val().Volume() < 1e-7:
                    raise Unknown("corner clip produced invalid or empty removal")
                shape = candidate
                setback = feature.get("x_setback")
                labels.append({"name": name, "kind": "corner_chamfer", "count": len(clips), "fact_ids": evidence or [],
                               "method": feature.get("method") or (setback.get("method", "derived") if isinstance(setback, dict) else "derived"), "feature_index": index})
                continue
            face = _value(feature.get("face"), "face", evidence)
            side_face = face in ("x_min", "x_max", "y_min", "y_max")
            if face not in ("top", "bottom") and not side_face:
                raise Unknown("unsupported face " + str(face))
            positions = _positions(feature)
            through = _value(feature.get("through"), "through", evidence)
            if not isinstance(through, bool):
                raise Unknown("through is not boolean")
            allow_primary = feature.get("allow_primary_hole_without_unresolved_step") is True
            if "allow_primary_hole_without_unresolved_step" in feature and type(feature["allow_primary_hole_without_unresolved_step"]) is not bool:
                raise Unknown("primary-hole fallback flag is not boolean")
            if allow_primary and (feature.get("kind") != "hole" or through is not True or
                    not feature.get("fact_ids") or not isinstance(feature.get("step_conflict_reason"), str) or not feature["step_conflict_reason"].strip()):
                raise Unknown("primary-hole fallback requires a sourced step-conflict reason and a known through hole")
            depth = t if through else _num(feature.get("depth"), "depth", evidence, True)
            if not side_face and depth > t + 1e-6:
                raise Unknown("depth exceeds plate thickness")
            z = 0 if face == "bottom" else t-depth
            # Slight overrun only on through cuts prevents coincident-face artifacts.
            cut_z, cut_depth = (-0.001, t+0.002) if through else (z, depth)
            cutters = []
            step_omission = None
            modeled_hole_type = None
            for x, y in positions:
                if side_face:
                    cutters.append(_side_hole(cq, feature, outline, t, x, y, through))
                    modeled_hole_type = _value(feature.get("hole_type"), "hole_type", evidence)
                    continue
                plane = cq.Workplane("XY", origin=(x, y, cut_z))
                if feature.get("kind") == "slot":
                    width = _num(feature.get("width"), "width", evidence, True)
                    length = _num(feature.get("length"), "length", evidence, True)
                    direction = feature.get("direction", feature.get("angle"))
                    angle = _angle(direction, "slot.direction", evidence)
                    if length < width:
                        raise Unknown("slot length is less than width")
                    cutter = plane.slot2D(length, width, angle).extrude(cut_depth)
                elif feature.get("kind") == "hole":
                    diameter = _num(feature.get("diameter"), "diameter", evidence, True)
                    cutter = plane.circle(diameter/2).extrude(cut_depth)
                    hole_type = _value(feature.get("hole_type"), "hole_type", evidence)
                    if allow_primary and hole_type not in ("counterbored", "countersunk"):
                        raise Unknown("primary-hole fallback is only supported for a stepped hole")
                    modeled_hole_type = hole_type
                    if hole_type == "counterbored":
                        outer = _num(feature.get("counterbore_diameter"), "counterbore_diameter", evidence, True)
                        bore_depth = _num(feature.get("counterbore_depth"), "counterbore_depth", evidence, True)
                        if outer <= diameter:
                            raise Unknown("invalid counterbore dimensions")
                        if bore_depth > t or bore_depth > depth:
                            if not allow_primary:
                                raise Unknown("invalid counterbore dimensions")
                            step_omission = f"{name}: counterbore step omitted for {t:g} mm thickness: documented depth {bore_depth:g} mm exceeds primary-hole depth {depth:g} mm. Known {diameter:g} mm primary hole retained; step depth was not clamped. {feature['step_conflict_reason']}"
                            modeled_hole_type = "plain"
                        else:
                            bore_z = 0 if face == "bottom" else t-bore_depth
                            cutter = cutter.union(cq.Workplane("XY", origin=(x,y,bore_z)).circle(outer/2).extrude(bore_depth))
                    elif hole_type == "countersunk":
                        outer = _num(feature.get("countersink_diameter"), "countersink_diameter", evidence, True)
                        angle = _num(feature.get("countersink_angle"), "countersink_angle", evidence, True)
                        if outer <= diameter or angle >= 180:
                            raise Unknown("invalid countersink dimensions")
                        sink_depth = (outer-diameter)/2 / math.tan(math.radians(angle/2))
                        if sink_depth > depth:
                            if not allow_primary:
                                raise Unknown("countersink exceeds hole depth")
                            step_omission = f"{name}: countersink step omitted for {t:g} mm thickness: derived depth {sink_depth:g} mm exceeds primary-hole depth {depth:g} mm. Known {diameter:g} mm primary hole retained; step depth was not clamped. {feature['step_conflict_reason']}"
                            modeled_hole_type = "plain"
                        else:
                            origin = (x,y,0) if face == "bottom" else (x,y,t-sink_depth)
                            r1, r2 = (outer/2, diameter/2) if face == "bottom" else (diameter/2, outer/2)
                            cone = cq.Solid.makeCone(r1, r2, sink_depth, cq.Vector(*origin))
                            cutter = cutter.union(cq.Workplane(obj=cone))
                    elif hole_type not in ("plain", "threaded"):
                        raise Unknown("unsupported hole type " + str(hole_type))
                else:
                    raise Unknown("unsupported feature kind " + str(feature.get("kind")))
                cutters.append(cutter)
            candidate = shape
            for cutter in cutters:
                candidate = candidate.cut(cutter)
            if not candidate.val().isValid() or candidate.val().Volume() <= 0:
                raise Unknown("cut produced invalid geometry")
            if abs(candidate.val().Volume()-shape.val().Volume()) < 1e-7:
                raise Unknown("feature does not intersect the plate")
            shape = candidate
            if step_omission:
                waiting.append(f"features.{index}.step")
                omitted.append(step_omission)
            methods = [value.get("method") for value in feature.values() if isinstance(value, dict) and value.get("method")]
            if not methods:
                provenance = [template.get("features_review"), template.get("thickness"), *outline.values()]
                methods = [value.get("method") for value in provenance if isinstance(value, dict) and value.get("method")]
            method = feature.get("method") or next((candidate for candidate in
                ("human_decision", "ai_verified_after_retry", "ai_verified", "ai_agreed_after_retry", "ai_agreed", "ai_unsure")
                if candidate in methods), "derived")
            labels.append({"name": name, "kind": feature.get("kind"), "count": len(positions), "hole_type": modeled_hole_type, "requested_hole_type": feature.get("hole_type"), "step_omitted": step_omission, "thread": feature.get("thread"), "thread_representation": "Cosmetic thread: supplied drill diameter; no helical thread geometry" if feature.get("hole_type") == "threaded" else None, "fact_ids": evidence or [], "method": method, "feature_index": index})
        except (Unknown, ValueError) as exc:
            reason = f"{name}: {exc}"
            waiting.append(f"features.{index}")
            omitted.append(reason)
    return shape, waiting, omitted, labels


def export_glb(shape, path, name="Reconstruction"):
    """Direct glTF 2.0 export; SI metres are required by glTF, CAD stays in mm."""
    vertices, triangles = shape.val().tessellate(0.03, 0.12)
    positions, normals = [], []
    for triangle in triangles:
        points = [vertices[i] for i in triangle]
        a, b = points[1]-points[0], points[2]-points[0]
        normal = a.cross(b).normalized()
        for point in points:
            positions.extend((point.x/1000, point.y/1000, point.z/1000))
            normals.extend((normal.x, normal.y, normal.z))
    count = len(positions)//3
    pos_bytes = struct.pack("<"+"f"*len(positions), *positions)
    norm_bytes = struct.pack("<"+"f"*len(normals), *normals)
    bounds = [[min(positions[i::3]) for i in range(3)], [max(positions[i::3]) for i in range(3)]]
    content = {"asset": {"version": "2.0", "generator": "Meridian CadQuery reconstruction", "extras": {"notice": NOTICE, "units": "metres", "source_units": "mm"}}, "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": name}], "meshes": [{"name": name, "primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "material": 0}]}], "materials": [{"name": "Neutral grey (does not indicate material)", "pbrMetallicRoughness": {"baseColorFactor": [0.56,0.59,0.63,1], "metallicFactor": 0.12, "roughnessFactor": 0.65}}], "buffers": [{"byteLength": len(pos_bytes)+len(norm_bytes)}], "bufferViews": [{"buffer": 0,"byteOffset": 0,"byteLength": len(pos_bytes),"target":34962},{"buffer":0,"byteOffset":len(pos_bytes),"byteLength":len(norm_bytes),"target":34962}], "accessors": [{"bufferView":0,"componentType":5126,"count":count,"type":"VEC3","min":bounds[0],"max":bounds[1]},{"bufferView":1,"componentType":5126,"count":count,"type":"VEC3"}]}
    js = json.dumps(content, separators=(",", ":")).encode()
    js += b" "*((-len(js))%4)
    binary = pos_bytes+norm_bytes
    binary += b"\0"*((-len(binary))%4)
    data = struct.pack("<4sII",b"glTF",2,12+8+len(js)+8+len(binary))+struct.pack("<I4s",len(js),b"JSON")+js+struct.pack("<I4s",len(binary),b"BIN\0")+binary
    inside(path).write_bytes(data)


def shape_bounds_mm(shape):
    """Measure the B-rep, excluding tessellation's conservative deflection padding."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.val().wrapped, box, False, False)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return {"min":[xmin,ymin,zmin],"max":[xmax,ymax,zmax],"size":[xmax-xmin,ymax-ymin,zmax-zmin]}


def _material_candidates(template):
    densities = _read(Path(__file__).with_name("densities.json"), [])
    material = template.get("material") or {}
    candidates = []
    values = [(material, "drawing")]
    values += [(value, "parts list") for value in template.get("bom_materials", template.get("part_materials", []))]
    for field, source in values:
        try:
            raw = _value(field, "material")
        except Unknown:
            continue
        for name in (raw if isinstance(raw, list) else re.split(r"[,;]", str(raw))):
            name = str(name).strip()
            for density in densities:
                if name.casefold() in [alias.casefold() for alias in density["names"]]:
                    candidates.append({"material": name, "source": source, **density})
                    break
    return candidates


def weight_check(template, models):
    try:
        weight = template.get("weight_on_drawing")
        printed = _num(weight, "weight on drawing", weight.get("name") if isinstance(weight, dict) else None, positive=True)
    except Unknown:
        return {"state":"Skipped", "message":"Weight check skipped: no reliable weight on the drawing", "examples":{}}
    candidates = _material_candidates(template)
    results, matching = {}, []
    for example, model in models.items():
        attempts = []
        for i, candidate in enumerate(candidates):
            calculated = model["volume_mm3"] / 1000 * candidate["density_g_cm3"]
            difference = abs(calculated-printed)/printed
            attempt = {**candidate,"calculated_g":round(calculated,4),"drawing_g":printed,"difference_percent":round(difference*100,2),"matches":difference <= 0.05,"outside_source":True}
            attempts.append(attempt)
            if attempt["matches"]:
                matching.append(i)
        results[example] = {"attempts":attempts,"matches":any(a["matches"] for a in attempts),"drawing_g":printed}
    try:
        trusted_drawing = bool(_value(template.get("material"), "material"))
    except Unknown:
        trusted_drawing = False
    first_source = "drawing" if trusted_drawing else "parts list"
    primary_count = sum(c["source"] == "drawing" for c in candidates) if trusted_drawing else len(candidates)
    if any(i < primary_count for i in matching):
        state, message = "Passed", f"Weight check passed using {first_source} material"
    elif matching:
        state, message = "Flagged", "Weight check flagged: only matches using the parts list's material. The drawing's material, or the model's size, may be wrong."
    else:
        state, message = "FAILED", "FAILED weight check: needs manual approval"
        if not candidates:
            message += " — no trusted material with a sourced density is available"
    return {"state":state,"message":message,"examples":results,"drawing_g":printed,"tolerance_percent":5,"requires_approval":state in ("Flagged","FAILED"),"approval_note_required":state == "FAILED", "limitation":"A matching weight does not verify feature positions. No thickness or material is selected automatically.","density_label":"Outside source, not the dataset"}


def _build_part(part_id, template, old, allow_generation=True):
    template_hash = _hash(template)
    inventory = feature_inventory(template)
    entry = {"examples":[],"models":{},"waiting":[],"omitted":[],"template_sha256":template_hash,"source_sha256":template.get("source_sha256"),"generator_version":VERSION,"notice":NOTICE,"review":template.get("review", {"status":"not_reviewed"}),"label":"Partial AI reconstruction. Not reviewed by a person" if inventory["status"] in ("partial", "unknown") else "AI reconstruction. Not reviewed by a person", "units":"mm", "features_status":inventory["status"], "features_all_determined":inventory["all_determined"], "omitted_feature_notes":inventory["notes"]}
    try:
        effective = copy.deepcopy(template)
        feature_field = effective.get("features_review") or {}
        if feature_field.get("state") == "known" and isinstance(feature_field.get("value"), list):
            effective["features"] = feature_field["value"]
            for feature in effective["features"]:
                feature.setdefault("method", feature_field.get("method", "derived"))
                feature.setdefault("fact_ids", feature_field.get("fact_ids") or ([feature_field["name"]] if feature_field.get("method") == "human_decision" and feature_field.get("name") else []))
        variants = list(_options(effective))
        # Validate essential fields before considering cache or optional CAD imports.
        for variant, _ in variants:
            _validate_essential(variant)
    except Unknown as exc:
        entry["waiting"] = [str(exc)]
        entry["weight_check"] = {"state":"Skipped","message":"No model built; waiting for human input", "examples":{}}
        return entry
    cache = inside(GENERATED / "ai_cache" / "artifacts" / "cad" / _hash({"version":VERSION,"template":template,"densities":_read(Path(__file__).with_name("densities.json"), [])}))
    cached = _read(cache / "manifest.json", None)
    if cached and all(inside(cache / Path(m[k]).name).exists() for m in cached["models"].values() for k in ("glb","step")):
        for model in cached["models"].values():
            for key in ("glb","step"):
                shutil.copyfile(inside(cache / Path(model[key]).name), inside(GENERATED / model[key]))
        cached["cache_hit"] = True
        return cached
    if not allow_generation:
        if old and old.get("models"):
            entry = copy.deepcopy(old)
            entry["stale"] = old.get("template_sha256") != template_hash or old.get("generator_version") != VERSION
            entry["stale_message"] = ("Model out of date: remote reconstruction rebuild needed. Showing the previous version."
                                      if entry["stale"] else "Using shipped reconstruction; local CAD generation is disabled.")
            entry["cache_only"] = True
            return entry
        entry["cache_only"] = True
        entry["waiting"] = ["No cached reconstruction for this template; rebuild on GitHub Actions"]
        entry["weight_check"] = {"state": "Skipped", "message": "Waiting for remote reconstruction", "examples": {}}
        return entry
    try:
        import cadquery as cq
    except ImportError:
        if old and old.get("models"):
            entry = copy.deepcopy(old)
            entry["stale"] = old.get("template_sha256") != template_hash or old.get("generator_version") != VERSION
            entry["stale_message"] = "Model out of date: rebuild needed. Showing the version from before this change." if entry["stale"] else "Using shipped reconstruction; CadQuery is not installed."
            return entry
        entry["waiting"] = ["CadQuery is not installed and no cached reconstruction is available"]
        entry["weight_check"] = {"state":"Skipped","message":"No model available", "examples":{}}
        return entry
    cache.mkdir(parents=True, exist_ok=True)
    for index, (variant, selections) in enumerate(variants):
        example = chr(65+index)
        try:
            shape, waiting, omitted, labels = build_shape(variant)
            glb = f"models/{part_id}_{example}.glb"
            step = f"models/{part_id}_{example}_reconstruction_from_drawing.step"
            export_glb(shape, inside(GENERATED/glb), f"{part_id} Example {example} - reconstruction")
            cq.exporters.export(shape, str(inside(GENERATED/step)), exportType="STEP")
            step_path = inside(GENERATED/step)
            content = step_path.read_text(encoding="utf-8")
            content = re.sub(r"FILE_DESCRIPTION\(\(.*?\)\s*,\s*'[^']*'\s*\)\s*;", "FILE_DESCRIPTION(('" + NOTICE + "'),'2;1');", content, count=1, flags=re.S)
            step_path.write_text(content, encoding="utf-8")
            bounds = shape_bounds_mm(shape)
            model = {"glb":glb,"step":step,"bounds_mm":bounds,"bounds_method":"B-rep optimal bounds; excludes triangulation deflection padding","volume_mm3":shape.val().Volume(),"template_sha256":template_hash,"selections":selections,"labels":labels,"waiting":waiting,"omitted":omitted,"features_all_determined":inventory["all_determined"] and not waiting and not omitted,"glb_units":"metres","cad_units":"mm","glb_to_mm":1000,"glb_sha256":hashlib.sha256(inside(GENERATED/glb).read_bytes()).hexdigest(),"step_sha256":hashlib.sha256(step_path.read_bytes()).hexdigest()}
            entry["models"][example] = model
            entry["examples"].append(example)
            entry["waiting"] = list(dict.fromkeys(entry["waiting"]+waiting))
            entry["omitted"] = list(dict.fromkeys(entry["omitted"]+omitted))
            for path in (glb, step):
                shutil.copyfile(inside(GENERATED/path), inside(cache / Path(path).name))
        except (Unknown, ValueError, RuntimeError) as exc:
            entry["waiting"].append(f"Example {example}: {exc}")
    entry["weight_check"] = weight_check(template, entry["models"])
    if entry["omitted"]:
        entry["features_all_determined"] = False
        if entry["models"]:
            entry["features_status"] = "partial"
    _write(cache / "manifest.json", entry)
    return entry


def build_all(templates: dict | None = None, *, allow_generation: bool = True) -> dict:
    """Build provided templates, or use AI prep output; no paid calls are made."""
    models_dir = inside(GENERATED / "models")
    models_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = models_dir / "manifest.json"
    old = _read(manifest_path, {})
    if templates is None:
        templates = _read(GENERATED / "ai_results.json", {}).get("templates")
        if templates is None:
            return old
    manifest = {}
    for part_id, template in templates.items():
        if not re.fullmatch(r"D-\d{3}", part_id):
            raise ValueError("Unsafe drawing ID in CAD template")
        if not isinstance(template, dict):
            raise ValueError("Template must be an object: " + part_id)
        manifest[part_id] = _build_part(part_id, template, old.get(part_id), allow_generation=allow_generation)
    _write(manifest_path, manifest)
    return manifest


if __name__ == "__main__":
    result = build_all()
    print(json.dumps({key:{"examples":value["examples"],"waiting":value["waiting"],"weight":value["weight_check"]["state"]} for key,value in result.items()}, indent=2))
