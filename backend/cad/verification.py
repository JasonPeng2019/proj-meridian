"""Independent exported-solid probes and drawing-callout coverage for remote CI.

No CAD generation is performed here. Analytic cut predicates, STEP point
classification and a direct triangle-ray test independently check the exports.
"""
from __future__ import annotations

import copy
import math
import re


def value(field):
    if isinstance(field, dict):
        if field.get("state") not in (None, "known") or field.get("confidence") == "unsure":
            raise ValueError("Unresolved verification input")
        return field.get("value")
    return field


def number(field):
    result = value(field)
    if type(result) not in (int, float) or not math.isfinite(result):
        raise ValueError("Invalid verification number")
    return float(result)


def angle(field):
    result = value(field)
    if isinstance(result, str) and result.lower() in ("x", "horizontal"):
        return 0.0
    if isinstance(result, str) and result.lower() in ("y", "vertical"):
        return 90.0
    return number(field)


def selected_template(template, selections):
    result = copy.deepcopy(template)
    review = result.get("features_review") or {}
    if review.get("state") == "known" and isinstance(review.get("value"), list):
        result["features"] = copy.deepcopy(review["value"])
    for path, choice in selections.items():
        keys = [int(key) if key.isdigit() else key for key in path.split(".")]
        parent = result
        for key in keys[:-1]:
            parent = parent[key]
        old = parent[keys[-1]]
        parent[keys[-1]] = {**old, "state": "known", "value": choice} if isinstance(old, dict) else choice
    return result


def positions(feature):
    x, y = number(feature["x"]), number(feature["y"])
    pattern = feature.get("pattern")
    if not pattern:
        return [(x, y)]
    count = number(pattern["count"])
    if count < 1 or not count.is_integer():
        raise ValueError("Invalid verification pattern count")
    count = int(count)
    if pattern["type"] == "circle":
        radius, start = number(pattern["radius"]), angle(pattern["start_angle"])
        return [(x + radius * math.cos(math.radians(start + index * 360 / count)),
                 y + radius * math.sin(math.radians(start + index * 360 / count))) for index in range(count)]
    if pattern["type"] == "row":
        spacing, direction = number(pattern["spacing"]), math.radians(angle(pattern["direction"]))
        return [(x + index * spacing * math.cos(direction), y + index * spacing * math.sin(direction)) for index in range(count)]
    raise ValueError("Unsupported verification pattern")


def expanded_cuts(template, thickness):
    cuts = []
    for index, feature in enumerate(template.get("features", [])):
        if feature.get("state") == "unknown":
            raise ValueError("Unresolved feature leaked into supported cuts")
        kind, face, through = feature["kind"], value(feature["face"]), value(feature["through"])
        if kind not in ("hole", "slot") or face not in ("top", "bottom") or type(through) is not bool:
            raise ValueError("Unsupported verification cut")
        depth = thickness if through else number(feature["depth"])
        allow_primary = feature.get("allow_primary_hole_without_unresolved_step", False)
        if type(allow_primary) is not bool or (allow_primary and (kind != "hole" or through is not True or
                not feature.get("fact_ids") or not isinstance(feature.get("step_conflict_reason"), str) or not feature["step_conflict_reason"].strip())):
            raise ValueError("Invalid primary-hole fallback authorization")
        shared = {"index": index, "kind": kind, "face": face, "through": through, "depth": depth,
                  "fact_ids": feature.get("fact_ids", []), "name": feature.get("name", f"Feature {index + 1}"),
                  "coordinate_evidence": {key: copy.deepcopy(feature[key]) for key in ("x", "y", "pattern") if key in feature}}
        if kind == "slot":
            shared.update(width=number(feature["width"]), length=number(feature["length"]),
                          direction=angle(feature.get("direction", feature.get("angle"))))
            shared["radius"] = shared["length"] / 2
        else:
            shared.update(diameter=number(feature["diameter"]), hole_type=value(feature["hole_type"]),
                          thread=value(feature.get("thread")))
            shared["radius"] = shared["diameter"] / 2
            if shared["hole_type"] == "counterbored":
                shared.update(outer=number(feature["counterbore_diameter"]) / 2, step_depth=number(feature["counterbore_depth"]))
            elif shared["hole_type"] == "countersunk":
                shared["outer"] = number(feature["countersink_diameter"]) / 2
                shared["sink_angle"] = number(feature["countersink_angle"])
                if not 0 < shared["sink_angle"] < 180:
                    raise ValueError("Invalid countersink angle")
                shared["step_depth"] = (shared["outer"] - shared["radius"]) / math.tan(math.radians(shared["sink_angle"] / 2))
            shared["radius"] = max(shared["radius"], shared.get("outer", 0))
            if allow_primary and shared["hole_type"] not in ("counterbored", "countersunk"):
                raise ValueError("Primary-hole fallback requires a stepped hole")
            if "step_depth" in shared:
                if shared["outer"] <= shared["diameter"] / 2 or shared["step_depth"] <= 0:
                    raise ValueError("Invalid step radius/depth")
                if shared["step_depth"] > depth:
                    if not allow_primary:
                        raise ValueError("Unresolved step exceeds primary-hole depth without fallback authorization")
                    shared["requested_step"] = {key: shared[key] for key in ("hole_type", "outer", "step_depth", "sink_angle") if key in shared}
                    shared["step_omitted"] = (f"{shared['hole_type']} step depth {shared['step_depth']:g} mm exceeds "
                        f"the {depth:g} mm primary-hole depth for thickness {thickness:g} mm; only the known "
                        f"{shared['diameter']:g} mm through bore is expected. {feature['step_conflict_reason']}")
                    shared["hole_type"], shared["radius"] = "plain", shared["diameter"] / 2
                    for key in ("outer", "step_depth", "sink_angle"):
                        shared.pop(key, None)
        for x, y in positions(feature):
            cuts.append({**shared, "x": x, "y": y})
    return cuts


def in_outline(outline, x, y, margin=0):
    kind = value(outline["type"])
    if kind == "rectangle":
        return abs(x) < number(outline["length"]) / 2 - margin and abs(y) < number(outline["width"]) / 2 - margin
    radius = number(outline.get("outer_diameter", outline.get("diameter"))) / 2
    distance = math.hypot(x, y)
    return distance < radius - margin and (kind != "ring" or distance > number(outline["inner_diameter"]) / 2 + margin)


def in_cut(cut, x, y, z, thickness):
    entry_depth = thickness - z if cut["face"] == "top" else z
    if not 0 < entry_depth < cut["depth"]:
        return False
    dx, dy = x - cut["x"], y - cut["y"]
    if cut["kind"] == "slot":
        direction = math.radians(cut["direction"])
        along = dx * math.cos(direction) + dy * math.sin(direction)
        across = -dx * math.sin(direction) + dy * math.cos(direction)
        half_line = (cut["length"] - cut["width"]) / 2
        return math.hypot(max(abs(along) - half_line, 0), across) < cut["width"] / 2
    radius = cut["diameter"] / 2
    if cut["hole_type"] == "counterbored" and entry_depth < cut["step_depth"]:
        radius = cut["outer"]
    if cut["hole_type"] == "countersunk" and entry_depth < cut["step_depth"]:
        radius = cut["outer"] - (cut["outer"] - radius) * entry_depth / cut["step_depth"]
    return math.hypot(dx, dy) < radius


class TriangleProbe:
    """Ray parity without optional rtree/Embree dependencies; one probe at a time."""
    def __init__(self, mesh):
        import numpy as np
        self.np = np
        triangles = np.asarray(mesh.triangles, dtype=float) * 1000
        self.origin = triangles[:, 0]
        self.edge1, self.edge2 = triangles[:, 1] - self.origin, triangles[:, 2] - self.origin
        self.direction = np.asarray([1.0, .3713906763541037, .5291502622129182])
        self.direction /= np.linalg.norm(self.direction)
        self.cross = np.cross(self.direction, self.edge2)
        determinant = np.einsum("ij,ij->i", self.edge1, self.cross)
        self.valid = np.abs(determinant) > 1e-12
        self.inverse = np.divide(1.0, determinant, out=np.zeros_like(determinant), where=self.valid)

    def contains(self, point):
        np = self.np
        offset = np.asarray(point) - self.origin
        u = np.einsum("ij,ij->i", offset, self.cross) * self.inverse
        cross = np.cross(offset, self.edge1)
        v = np.einsum("ij,j->i", cross, self.direction) * self.inverse
        distance = np.einsum("ij,ij->i", self.edge2, cross) * self.inverse
        hits = np.sort(distance[self.valid & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (distance > 1e-7)])
        distinct = len(hits) and 1 + int(np.count_nonzero(np.diff(hits) > 1e-6))
        return bool(distinct % 2)


def cut_probes(cut, thickness):
    """Core, diameter/width rims, face/depth and stepped-radius probes."""
    x, y, depth = cut["x"], cut["y"], cut["depth"]
    def point(dx=0, dy=0, entry=None):
        q = depth / 2 if entry is None else entry
        return (x + dx, y + dy, thickness - q if cut["face"] == "top" else q)
    probes = [("core", point(entry=depth * q)) for q in (.15, .5, .85)]
    if depth < thickness - 1e-6:
        probes.append(("blind floor", point(entry=(depth + thickness) / 2)))
    if cut["kind"] == "hole":
        radius = cut["diameter"] / 2
        # Use a cylindrical layer below any counterbore/countersink step.
        q = min(depth * .9, (cut.get("step_depth", 0) + depth) / 2)
        for sign in (-1, 1):
            for scale in (.99, 1.01):
                probes.extend([("drill radius", point(sign * radius * scale, 0, q)),
                               ("drill radius", point(0, sign * radius * scale, q))])
        if "outer" in cut:
            annulus = (radius + cut["outer"]) / 2
            for fraction in (.2, .8):
                q = cut["step_depth"] * fraction
                probes.extend([("stepped radius and face", point(annulus, 0, q)),
                               ("stepped radius and face", point(-annulus, 0, q))])
            for fraction in (.25, .75):
                q = cut["step_depth"] * fraction
                local_radius = cut["outer"] if cut["hole_type"] == "counterbored" else cut["outer"] - (cut["outer"] - radius) * fraction
                for scale in (.99, 1.01):
                    probes.extend([("step/cone radius", point(local_radius * scale, 0, q)),
                                   ("step/cone radius", point(-local_radius * scale, 0, q))])
            if cut["step_depth"] < depth:
                probes.append(("step floor", point(annulus, 0, (cut["step_depth"] + depth) / 2)))
                if cut["hole_type"] == "counterbored" and cut["step_depth"] * 1.01 < depth:
                    probes.extend([("counterbore depth", point(annulus, 0, cut["step_depth"] * .99)),
                                   ("counterbore depth", point(annulus, 0, cut["step_depth"] * 1.01))])
    else:
        direction = math.radians(cut["direction"])
        for along, across in ((cut["length"] / 2, 0), (-cut["length"] / 2, 0), (0, cut["width"] / 2), (0, -cut["width"] / 2)):
            for scale in (.99, 1.01):
                dx = scale * (along * math.cos(direction) - across * math.sin(direction))
                dy = scale * (along * math.sin(direction) + across * math.cos(direction))
                probes.append(("slot length/width/direction", point(dx, dy)))
    return probes


def analytic_volume(template, cuts, thickness):
    outline = template["outline"]
    # Disjoint, fully contained cuts have a closed-form volume independent of
    # both the generator's Booleans and the exported B-rep measurements.
    if any(not in_outline(outline, cut["x"], cut["y"], cut["radius"] + 1e-6) for cut in cuts):
        return None
    if any(math.hypot(a["x"] - b["x"], a["y"] - b["y"]) <= a["radius"] + b["radius"] + 1e-6
           for index, a in enumerate(cuts) for b in cuts[index + 1:]):
        return None
    if value(outline["type"]) == "rectangle":
        volume = number(outline["length"]) * number(outline["width"]) * thickness
    else:
        volume = math.pi * (number(outline.get("outer_diameter", outline.get("diameter"))) / 2) ** 2 * thickness
        if value(outline["type"]) == "ring":
            volume -= math.pi * (number(outline["inner_diameter"]) / 2) ** 2 * thickness
    for cut in cuts:
        if cut["kind"] == "slot":
            area = (cut["length"] - cut["width"]) * cut["width"] + math.pi * (cut["width"] / 2) ** 2
            volume -= area * cut["depth"]
        else:
            radius = cut["diameter"] / 2
            volume -= math.pi * radius ** 2 * cut["depth"]
            if cut["hole_type"] == "counterbored":
                volume -= math.pi * (cut["outer"] ** 2 - radius ** 2) * cut["step_depth"]
            elif cut["hole_type"] == "countersunk":
                volume -= math.pi * cut["step_depth"] * ((cut["outer"] ** 2 + cut["outer"] * radius + radius ** 2) / 3 - radius ** 2)
    return volume


def countersink_spec(callout):
    match = re.match(r"\s*(?:(\d+)\s*[xX×]\s*)?(\d+(?:[.,]\d+)?)\s*[xX×]\s*(\d+(?:[.,]\d+)?)\s*°", callout.get("text", ""))
    if not match:
        return None
    count, outer, sink_angle = match.groups()
    if count and type(callout.get("count")) is int and int(count) != callout["count"]:
        raise ValueError("Countersink source count disagrees with its original text")
    explicit = callout.get("count") if type(callout.get("count")) is int else int(count) if count else None
    return {"count": explicit, "outer": float(outer.replace(",", ".")), "angle": float(sink_angle.replace(",", "."))}


def callout_matches_cut(callout, cut):
    sink = countersink_spec(callout)
    if sink:
        step = cut if cut.get("hole_type") == "countersunk" else cut.get("requested_step", {})
        return (step.get("hole_type") == "countersunk" and abs(step["outer"] * 2 - sink["outer"]) < 1e-6 and
                abs(step["sink_angle"] - sink["angle"]) < 1e-6)
    kind = "slot" if callout.get("feature") == "slot" else "hole"
    match = re.match(r"\s*\d+\s*[xX×]\s*(\d+(?:[.,]\d+)?)", callout.get("text", ""))
    diameter = float(match.group(1).replace(",", ".")) if match else None
    if cut["kind"] != kind or (callout.get("through") is True and not cut["through"]):
        return False
    if kind == "slot":
        if any(abs(cut[key] - callout[source]) > 1e-6 for key, source in (("width", "width_mm"), ("length", "length_mm")) if source in callout):
            return False
    elif diameter is not None and abs(cut["diameter"] - diameter) > 1e-6:
        return False
    if callout.get("thread"):
        thread = re.match(r"M\d+(?:[.,]\d+)?", str(cut.get("thread") or "").strip(), re.I)
        if not thread or thread.group().replace(",", ".").upper() != callout["thread"].replace(",", ".").upper():
            return False
    return True


def counted_callout_cuts(callout, cuts, callouts=None):
    """Partition compatible cuts using original source-group IDs, never counts."""
    if callouts is None:
        return [cut for cut in cuts if callout_matches_cut(callout, cut)]
    is_step = countersink_spec(callout) is not None
    groups = [item for item in callouts if (type(item.get("count")) is int or
              (countersink_spec(item) or {}).get("count") is not None) and
              item.get("feature") != "general_note" and (countersink_spec(item) is not None) == is_step]
    sources = {group["name"]: {group["name"]} for group in groups}
    if not is_step:
        for step in callouts:
            if countersink_spec(step):
                parent = countersink_parent(step, callouts)
                if parent and parent["name"] in sources:
                    sources[parent["name"]].add(step["name"])
    candidates = []
    for cut in cuts:
        if not callout_matches_cut(callout, cut):
            continue
        compatible = [group for group in groups if callout_matches_cut(group, cut)]
        cited = [group for group in compatible if sources[group["name"]].intersection(cut.get("fact_ids", []))]
        if len(cited) == 1:
            if cited[0]["name"] == callout["name"]:
                candidates.append(cut)
        elif not cited and len(compatible) == 1 and compatible[0]["name"] == callout["name"]:
            candidates.append(cut)
    return candidates


def countersink_parent(callout, callouts):
    """Associate an uncounted step line with its counted source hole group."""
    if (countersink_spec(callout) or {}).get("count") is not None:
        return callout
    groups = [item for item in callouts if type(item.get("count")) is int and
              item.get("feature") not in ("slot", "general_note") and not countersink_spec(item) and
              (callout.get("page") is None or item.get("page") == callout.get("page"))]
    if len(groups) == 1:
        return groups[0]
    box = callout.get("box")
    if not box:
        return None
    adjacent = []
    for group in groups:
        other = group.get("box")
        if not other or group.get("page") != callout.get("page"):
            continue
        overlap = min(box[0] + box[2], other[0] + other[2]) - max(box[0], other[0])
        gap = box[1] - (other[1] + other[3])
        if overlap > 0 and -max(box[3], other[3]) <= gap <= max(box[3], other[3]) * 1.5:
            adjacent.append((abs(gap), group))
    return min(adjacent, key=lambda item: item[0])[1] if len(adjacent) == 1 else None


def callout_coverage(drawing, template, cuts):
    omissions = value(template.get("features_omitted")) if (template.get("features_omitted") or {}).get("state") == "known" else []
    omissions = omissions if isinstance(omissions, list) else []
    complete = value(template.get("features_complete")) is True if (template.get("features_complete") or {}).get("state") == "known" else False
    rows = []
    for callout in drawing.get("callouts", []):
        count = callout.get("count")
        sink = countersink_spec(callout)
        if sink:
            outer, sink_angle = sink["outer"], sink["angle"]
            matching = [cut for cut in cuts if cut.get("hole_type") == "countersunk" and
                        abs(cut["outer"] * 2 - outer) < 1e-6 and abs(cut["sink_angle"] - sink_angle) < 1e-6]
            variant_cuts = [cut for cut in cuts if (cut.get("requested_step") or {}).get("hole_type") == "countersunk" and
                            abs(cut["requested_step"]["outer"] * 2 - outer) < 1e-6 and abs(cut["requested_step"]["sink_angle"] - sink_angle) < 1e-6]
            parent = countersink_parent(callout, drawing.get("callouts", []))
            expected_count = sink["count"] if sink["count"] is not None else parent["count"] if parent else None
            position = lambda cut: (round(cut["x"], 7), round(cut["y"], 7), cut["face"])
            parent_cuts = counted_callout_cuts(parent, cuts, drawing.get("callouts", [])) if parent else cuts
            matching = [cut for cut in matching if cut in parent_cuts]
            variant_cuts = [cut for cut in variant_cuts if cut in parent_cuts]
            built_positions = {position(cut) for cut in matching}
            variant_positions = {position(cut) for cut in variant_cuts}
            parent_positions = {position(cut) for cut in parent_cuts}
            covered = bool(matching) if parent is None else len(built_positions) == expected_count and built_positions == parent_positions
            variant_covered = bool(variant_cuts) if parent is None else (
                len(built_positions | variant_positions) == expected_count and built_positions | variant_positions == parent_positions)
            variant_omissions = [cut["step_omitted"] for cut in variant_cuts]
            omitted = [item for item in omissions if callout["name"] in item.get("fact_ids", []) or
                       drawing["id"] + "/drawing/source" in item.get("fact_ids", []) or drawing["id"] in item.get("fact_ids", [])]
            status = "covered" if covered else "documented_variant_omission" if variant_omissions and variant_covered else "documented_omission" if omitted and not complete else "unexplained_gap"
            rows.append({"source": callout["name"], "text": callout.get("text"), "kind": "countersink",
                         "parent_source": parent.get("name") if parent else None, "expected_count": expected_count,
                         "count_scope": "explicit_step_count" if sink["count"] is not None else "associated_counted_hole_group" if parent else "uncounted_step_existence_only",
                         "built_count": len(built_positions), "status": status, "omissions": omitted, "variant_step_omissions": variant_omissions})
            assert status != "unexplained_gap", f"{drawing['id']}: countersink callout omitted without explanation: {rows[-1]}"
            continue
        if type(count) is not int or callout.get("feature") == "general_note":
            continue
        candidates = counted_callout_cuts(callout, cuts, drawing.get("callouts", []))
        unique = {(round(cut["x"], 7), round(cut["y"], 7), cut["face"]) for cut in candidates}
        omitted = [item for item in omissions if callout["name"] in item.get("fact_ids", []) or
                   drawing["id"] + "/drawing/source" in item.get("fact_ids", []) or drawing["id"] in item.get("fact_ids", [])]
        covered = len(unique) == count
        status = "covered" if covered else "documented_omission" if omitted and not complete else "unexplained_gap"
        rows.append({"source": callout["name"], "text": callout.get("text"), "expected_count": count,
                     "built_count": len(unique), "positions_mm": sorted(unique), "status": status,
                     "position_evidence": [{"feature_index": cut["index"], "fact_ids": cut["fact_ids"],
                                            "coordinates": cut["coordinate_evidence"]} for cut in candidates],
                     "omissions": omitted})
        assert status != "unexplained_gap", f"{drawing['id']}: drawing callout count not covered or explicitly omitted: {rows[-1]}"
        assert len(unique) <= count, f"{drawing['id']}: model has more matching cuts than drawing callout"
    return rows


def source_inventory_scope(cuts, coverage):
    counterbores = sorted({cut["index"] for cut in cuts if cut.get("hole_type") == "counterbored" or
                          (cut.get("requested_step") or {}).get("hole_type") == "counterbored"})
    return {"scope": "parsed_callouts_only", "independently_proves_all_drawing_features": False,
            "source_to_template_layout_verification": "proposer_verifier",
            "counterbore_step_source_coverage": "not_parsed",
            "counterbore_feature_indices": counterbores,
            "unassociated_countersink_sources": [row["source"] for row in coverage if
                                                 row.get("count_scope") == "uncounted_step_existence_only"]}


def verify_features(template, model, step_shape, mesh, drawing):
    selected = selected_template(template, model.get("selections", {}))
    thickness = number(selected["thickness"])
    cuts = expanded_cuts(selected, thickness)
    variant_omissions = [{"feature_index": cut["index"], "center_mm": [cut["x"], cut["y"]],
                          "reason": cut["step_omitted"], "requested_step": cut["requested_step"]} for cut in cuts if cut.get("step_omitted")]
    if variant_omissions:
        assert model.get("omitted") and model.get("features_all_determined") is not True, "Variant step omission must remain explicit in the shipped model metadata"
    mesh_probe = TriangleProbe(mesh)
    report = []
    for cut in cuts:
        probes = []
        for purpose, point in cut_probes(cut, thickness):
            baseline = 0 < point[2] < thickness and in_outline(selected["outline"], *point[:2])
            expected = baseline and not any(in_cut(other, *point, thickness) for other in cuts)
            actual_step, actual_mesh = bool(step_shape.isInside(point, 1e-6)), mesh_probe.contains(point)
            assert actual_step == expected, f"{drawing['id']}: STEP feature {cut['index']} {purpose} at {point}: material={actual_step}, expected={expected}"
            assert actual_mesh == expected, f"{drawing['id']}: GLB feature {cut['index']} {purpose} at {point}: material={actual_mesh}, expected={expected}"
            probes.append({"purpose": purpose, "point_mm": point, "expected_material": expected,
                           "step_material": actual_step, "glb_material": actual_mesh})
        assert any(not item["expected_material"] and in_outline(selected["outline"], *item["point_mm"][:2]) for item in probes), "Feature has no verified removal inside the base outline"
        report.append({"feature_index": cut["index"], "kind": cut["kind"], "hole_type": cut.get("hole_type"),
                       "center_mm": [cut["x"], cut["y"]], "face": cut["face"], "depth_mm": cut["depth"],
                       "coordinate_evidence": cut["coordinate_evidence"],
                       "probe_count": len(probes), "probes": probes})
    expected_volume = analytic_volume(selected, cuts, thickness)
    if expected_volume is not None:
        assert abs(step_shape.Volume() - expected_volume) < max(.01, expected_volume * 1e-7), "Exported STEP volume disagrees with independent base-minus-cuts calculation"
    coverage = callout_coverage(drawing, selected, cuts)
    return {"cut_instances_checked": len(cuts), "probe_count": sum(item["probe_count"] for item in report),
            "variant_step_omissions": variant_omissions,
            "independent_volume_mm3": expected_volume,
            "volume_scope": "disjoint fully contained analytic cuts" if expected_volume is not None else "clipped/overlapping cuts: point probes and export-volume roundtrip",
            "cuts": report, "drawing_callout_coverage": coverage,
            "source_inventory_scope": source_inventory_scope(cuts, coverage),
            "limitation": "Checks exported geometry against verified template and parsed callout inventory; does not replace review of the original drawing"}
