"""Source-bound flat-part reconstruction; importing this module needs no CAD.

``create_model_rebuilder(output_dir)`` implements the frozen ModelRebuilder.
``build_template(template, output_dir, previous=...)`` accepts an effective,
source-validated template directly. The factory additionally checks the owning
record's drawing/hash and evidence inventory. Neither entry point reads drawings
or invents a template. Synthetic inputs retain their markers in the manifest.

Supported feature faces are top (z=thickness, inward -Z) and bottom (z=0,
inward +Z). Positions use global XY, rectangle lower-left / round-part centre,
x right, y up, mm. A row starts at position; a circle pattern is centred there.
Slot length includes its semicircular ends; direction is counterclockwise from
+X. Side/radial faces lack a frozen coordinate mapping and are unsupported.
Threads are cylindrical drill cuts, never helices: the diameter field name or
feature note must explicitly identify a drill/minor-diameter convention.

Each successful directory contains GLB, mm STEP and a manifest binding the
complete input, selected option evidence, measurements and artifact hashes.
GLB uses the qualified Assembly exporter with an explicit mm-to-m scale and
opaque neutral grey. Examples are possible readings, never an approval.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from importlib import import_module
import itertools
import json
import math
from pathlib import Path
import re
import struct
import tempfile
from typing import Any, Iterator

from backend import contracts as c


__all__ = ["build_template", "create_model_rebuilder"]
WORKSPACE = Path(__file__).resolve().parents[3]
APP_ROOT = WORKSPACE / "development"
BUILDER_VERSION = "flat-cad/v1"
MANIFEST = "manifest.json"
EXAMPLE_IDS = "ABCD"
GREY = (0.6, 0.6, 0.6, 1.0)


class _BuildIssue(ValueError):
    def __init__(self, message: str, names=(), *, state="blocked"):
        super().__init__(message)
        self.names = list(dict.fromkeys(names))
        self.state = state


@dataclass
class _Plan:
    geometry: dict
    alternatives: list[dict]
    omissions: list[c.OmittedDetail]
    disclosures: list[str]
    unresolved: list[str]


def _output_path(path: Path) -> Path:
    path = Path(path).resolve()
    allowed = (APP_ROOT / "generated", WORKSPACE / "testing/tmp", WORKSPACE / "testing/runs")
    if not any(path.is_relative_to(root) for root in allowed):
        raise ValueError("CAD output must be under development/generated/ or testing/tmp/ or testing/runs/.")
    return path


def _fields(node: Any) -> Iterator[dict]:
    """Walk actual fields only, never a provenance candidate or review record."""
    if isinstance(node, dict):
        if {"name", "method", "state"} <= node.keys():
            yield node
            if node["state"] == "known":
                yield from _fields(node["value"])
            elif node["state"] == "options":
                for option in node["options"]:
                    yield from _fields(option["value"])
        else:
            for key, value in node.items():
                if key not in {"provenance", "review", "review_item", "evidence"}:
                    yield from _fields(value)
    elif isinstance(node, list):
        for value in node:
            yield from _fields(value)


def _refs(evidence: dict) -> list[str]:
    refs = [*evidence.get("number_ids", []), *evidence.get("source_ids", [])]
    derivation = evidence.get("derivation")
    if derivation:
        refs.extend(derivation["inputs"])
        if derivation.get("pattern_fact"):
            refs.append(derivation["pattern_fact"])
    return list(dict.fromkeys(refs))


def _sources(node: Any, selected: dict[str, int] | None = None) -> list[str]:
    refs = []
    for field in _fields(node):
        refs.extend(_refs(field.get("evidence", {})))
        if field["state"] == "options":
            options = field["options"]
            if selected is not None and field["name"] in selected:
                options = [options[selected[field["name"]]]]
            for option in options:
                refs.extend(_refs(option["evidence"]))
    return list(dict.fromkeys(refs))


def _omit(field: dict, reason: str, parent: dict | None = None) -> c.OmittedDetail:
    return c.OmittedDetail(name=field["name"], reason=reason,
        source_ids=list(dict.fromkeys([*_refs(field.get("evidence", {})),
                                     *_refs((parent or {}).get("evidence", {}))])),
        review_item=field.get("review_item"))


def _plan(data: dict) -> _Plan:
    names = [field["name"] for field in _fields(data)]
    if len(set(names)) != len(names) or any(not n.startswith(data["part"] + "/template/") for n in names):
        raise _BuildIssue("Template field names must be unique within the drawing's template namespace.")
    geometry = {"outline": data["outline"], "thickness": data["thickness"], "features": []}
    omissions, disclosures, unresolved = [], [], []
    required = [f for f in _fields([data["outline"], data["thickness"]]) if f["state"] == "unknown"]
    if required:
        raise _BuildIssue("Essential outline/thickness is unknown: " + "; ".join(
            f["name"] + ": " + f["message"] for f in required), [f["name"] for f in required])
    for field in data["features"]:
        if field["state"] == "unknown":
            unresolved.append(field["name"])
            if field["essential"]:
                raise _BuildIssue(f"Essential feature is unknown: {field['name']}: {field['message']}", [field["name"]])
            omissions.append(_omit(field, f"Feature omitted; {field['reason']}: {field['message']}"))
            continue
        essential_unknowns = [f for f in _fields(field) if f["state"] == "unknown" and f["essential"]]
        if essential_unknowns:
            raise _BuildIssue("Essential feature fields are unknown: " + "; ".join(
                f["name"] + ": " + f["message"] for f in essential_unknowns), [f["name"] for f in essential_unknowns])
        feature = field["value"]
        if feature["face"] not in {"top", "bottom"}:
            reason = (f"Feature face {feature['face']} is unsupported: only top/bottom have an "
                      "unambiguous XY coordinate and inward direction in this builder.")
            if field["essential"]:
                raise _BuildIssue(reason, [field["name"]], state="unsupported")
            omissions.append(_omit(field, reason))
            unresolved.append(field["name"])
            continue
        # Parent evidence identifies the face, through/blind state and feature
        # kind; child dimension evidence alone cannot supply those decisions.
        if not _refs(field["evidence"]):
            raise _BuildIssue("Feature kind/face/direction needs source evidence.", [field["name"]])
        thread_disclosure, thread_omission = None, None
        used = {"kind", "face", "position", "through", "pattern", "note"}
        if not feature["through"]:
            used.add("depth")
        if feature["kind"] == "slot":
            used.update({"width", "length", "direction_deg"})
        else:
            used.update({"hole_type", "diameter"})
            if feature["hole_type"] == "countersunk":
                used.update({"countersink_diameter", "countersink_angle_deg"})
            elif feature["hole_type"] == "counterbored":
                used.update({"counterbore_diameter", "counterbore_depth"})
            elif feature["hole_type"] == "threaded":
                convention = (feature["note"] or "") + " " + feature["diameter"]["name"]
                if not re.search(r"tap[ -]?drill|drill[ -]?diameter|minor[ -]?diameter", convention, re.I):
                    reason = ("Thread omitted: the supplied diameter is not identified as a tap/drill "
                              "or minor diameter. No nominal-to-drill conversion is inferred.")
                    if field["essential"]:
                        raise _BuildIssue(reason, [field["name"]])
                    omissions.append(_omit(field, reason))
                    unresolved.append(field["name"])
                    continue
                size = feature["thread_size"]
                sizes = ([] if size["state"] == "unknown" else [size["value"]] if size["state"] == "known"
                         else [o["value"] for o in size["options"]])
                if sizes and (not _sources(size) or any(not value.strip() for value in sizes)):
                    raise _BuildIssue("Thread identification needs source evidence.", [size["name"]])
                thread_disclosure = (f"{field['name']}: cosmetic thread {' / '.join(sizes) or 'size undetermined'}; uses the "
                    f"evidenced {feature['diameter']['name']} as cylindrical drill diameter. "
                    f"Convention: {convention.strip()}. No helical geometry; no drill-table lookup.")
                thread_omission = _omit(field, "Cosmetic thread only: helical thread geometry is omitted. "
                    "The identified drill-diameter convention is retained in the model message.")
        active = {key: value for key, value in feature.items() if key in used}
        pattern = active.get("pattern")
        if pattern and pattern["type"] == "circle" and not pattern["evenly_spaced"]:
            # Explicit angles locate every instance. The otherwise-required
            # start-angle annotation is not a geometric choice in this mode.
            active["pattern"] = {key: value for key, value in pattern.items() if key != "start_angle_deg"}
        unknowns = [f for f in _fields(field) if f["state"] == "unknown"]
        geometry_unknowns = [f for f in _fields(active) if f["state"] == "unknown"]
        if any(f["essential"] for f in unknowns) or field["essential"] and geometry_unknowns:
            raise _BuildIssue("Essential feature is unknown: " + "; ".join(
                f["name"] + ": " + f["message"] for f in unknowns), [f["name"] for f in unknowns])
        for unknown in unknowns:
            unresolved.append(unknown["name"])
            action = f"Feature {field['name']} omitted" if geometry_unknowns else "Non-geometric annotation omitted"
            omissions.append(_omit(unknown, f"{action}; {unknown['reason']}: {unknown['message']}", field))
        if geometry_unknowns:
            continue
        if thread_disclosure:
            disclosures.append(thread_disclosure)
            omissions.append(thread_omission)
        # Retain the wrapper's identity/evidence for error and option reporting.
        geometry["features"].append({**field, "value": active})
    if not _refs(data["outline"]["evidence"]):
        raise _BuildIssue("Outline type/frame needs source evidence.", [data["outline"]["name"]])
    alternatives = []
    for field in _fields(geometry):
        if field["state"] == "options":
            if any(isinstance(o["value"], bool) or not isinstance(o["value"], (int, float))
                   for o in field["options"]):
                raise _BuildIssue("Only printed numeric geometry alternatives can be expanded.", [field["name"]])
            alternatives.append(field)
            unresolved.append(field["name"])
        if field["state"] != "unknown" and field["method"] == "unresolved":
            raise _BuildIssue("An unresolved method cannot supply known geometry.", [field["name"]])
    count = math.prod(len(f["options"]) for f in alternatives)
    if count > 4:
        raise _BuildIssue(f"Printed geometry alternatives require {count} examples; limit is 4. "
                          "No alternatives were selected or truncated.", [f["name"] for f in alternatives])
    return _Plan(geometry, alternatives, omissions, disclosures, list(dict.fromkeys(unresolved)))


def _resolve(node: Any, selected: dict[str, int], key: str = "") -> Any:
    if isinstance(node, dict):
        if {"name", "method", "state"} <= node.keys():
            value = node["value"] if node["state"] == "known" else node["options"][selected[node["name"]]]["value"]
            if isinstance(value, (int, float)):
                # FlatTemplate freezes mm. Explicit other units are never converted.
                if key.endswith("_deg"):
                    allowed = {None, "deg", "degree", "degrees", "°"}
                elif key == "count":
                    allowed = {None, "count"}
                else:
                    allowed = {None, "mm"}
                if node.get("unit") not in allowed:
                    raise _BuildIssue(f"Unsupported geometry unit {node.get('unit')!r}.", [node["name"]])
            return _resolve(value, selected, key)
        return {child_key: _resolve(value, selected, child_key) for child_key, value in node.items()}
    if isinstance(node, list):
        return [_resolve(value, selected, key) for value in node]
    return node


def _positive(value: float, label: str, *, zero=False) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise _BuildIssue(f"{label} must be finite numeric geometry.")
    if value < 0 or (value == 0 and not zero):
        raise _BuildIssue(f"{label} must be {'nonnegative' if zero else 'positive'}.")
    return float(value)


def _positive_dimensions(node: Any, key: str = "") -> None:
    """Reject nonpositive dimension inputs even when CadQuery is unavailable."""
    if isinstance(node, dict):
        for child_key, value in node.items():
            _positive_dimensions(value, child_key)
    elif isinstance(node, list):
        for value in node:
            _positive_dimensions(value, key)
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        if key not in {"x", "y"} and not key.endswith("_deg"):
            _positive(node, key)
        if key == "count" and int(node) != node:
            raise _BuildIssue("Pattern count must be a positive integer.")


def _positions(feature: dict) -> list[tuple[float, float]]:
    x, y = feature["position"]["x"], feature["position"]["y"]
    pattern = feature.get("pattern")
    if pattern is None:
        return [(x, y)]
    count = pattern["count"]
    if isinstance(count, bool) or count < 1 or int(count) != count:
        raise _BuildIssue("Pattern count must be a positive integer.")
    if pattern["type"] == "row":
        spacing = _positive(pattern["spacing"], "Row spacing")
        angle = math.radians(pattern["direction_deg"])
        return [(x + i * spacing * math.cos(angle), y + i * spacing * math.sin(angle)) for i in range(count)]
    radius = _positive(pattern["radius"], "Pattern radius")
    if pattern["evenly_spaced"]:
        if pattern.get("angles_deg") is not None:
            raise _BuildIssue("Circle pattern supplies both explicit angles and evenly-spaced mode; no mode is chosen.")
        angles = [pattern["start_angle_deg"] + i * 360 / count for i in range(count)]
    else:
        angles = pattern.get("angles_deg")
        if angles is None or len(angles) != count:
            raise _BuildIssue("An irregular circle pattern needs one evidenced angle per occurrence.")
    return [(x + radius * math.cos(math.radians(a)), y + radius * math.sin(math.radians(a))) for a in angles]


def _fits(outline: dict, x: float, y: float, radius: float) -> bool:
    eps = 1e-8
    if outline["type"] == "rectangle":
        return min(x, y, outline["length"] - x, outline["width"] - y) + eps >= radius
    distance = math.hypot(x, y)
    outer = outline["diameter"] if outline["type"] == "circle" else outline["outer_diameter"]
    return (distance + radius <= outer / 2 + eps and
            (outline["type"] != "ring" or distance - radius + eps >= outline["inner_diameter"] / 2))


def _measure(shape) -> tuple[float, list[list[float]]]:
    if not shape.isValid() or len(shape.Solids()) != 1:
        raise _BuildIssue("Reconstruction must be one valid solid.")
    volume = _positive(shape.Volume(), "Solid volume")
    box = shape.BoundingBox()
    bounds = [[box.xmin, box.ymin, box.zmin], [box.xmax, box.ymax, box.zmax]]
    if not all(math.isfinite(v) for row in bounds for v in row):
        raise _BuildIssue("Solid bounds must be finite.")
    for lo, hi in zip(*bounds):
        _positive(hi - lo, "Solid size")
    return volume, bounds


def _solid(cq, geometry: dict):
    outline, thickness = geometry["outline"], _positive(geometry["thickness"], "Thickness")
    kind = outline["type"]
    if kind == "rectangle":
        shape = cq.Workplane("XY").box(_positive(outline["length"], "Length"),
            _positive(outline["width"], "Width"), thickness, centered=(False, False, False)).val()
    elif kind == "circle":
        shape = cq.Workplane("XY").circle(_positive(outline["diameter"], "Diameter") / 2).extrude(thickness).val()
    else:
        outer = _positive(outline["outer_diameter"], "Outer diameter")
        inner = _positive(outline["inner_diameter"], "Inner diameter")
        if inner >= outer:
            raise _BuildIssue("Ring inner diameter must be smaller than outer diameter.")
        shape = cq.Workplane("XY").circle(outer / 2).circle(inner / 2).extrude(thickness).val()
    volume, _ = _measure(shape)
    for feature in geometry["features"]:
        depth = thickness if feature["through"] else _positive(feature["depth"], "Blind depth")
        if not feature["through"] and depth >= thickness:
            raise _BuildIssue("Blind depth must be less than stock thickness; through is never inferred.")
        sign = -1 if feature["face"] == "top" else 1
        z = thickness if sign == -1 else 0
        direction = cq.Vector(0, 0, sign)
        for x, y in _positions(feature):
            origin = cq.Vector(x, y, z)
            if feature["kind"] == "slot":
                width, length = _positive(feature["width"], "Slot width"), _positive(feature["length"], "Slot length")
                if length < width:
                    raise _BuildIssue("Slot length includes its ends and must be at least its width.")
                angle = math.radians(feature["direction_deg"])
                offset = (length - width) / 2
                ends = [(x + s * offset * math.cos(angle), y + s * offset * math.sin(angle)) for s in (-1, 1)]
                if not all(_fits(outline, ex, ey, width / 2) for ex, ey in ends):
                    raise _BuildIssue("Slot footprint extends beyond the evidenced stock outline.")
                if outline["type"] == "ring":
                    # The closest point of the slot's centre segment, rather
                    # than only its ends, must also clear the central opening.
                    projection = max(-offset, min(offset, -x * math.cos(angle) - y * math.sin(angle)))
                    if not _fits(outline, x + projection * math.cos(angle),
                                 y + projection * math.sin(angle), width / 2):
                        raise _BuildIssue("Slot footprint intersects the ring's central opening.")
                if length == width:
                    tool = cq.Solid.makeCylinder(width / 2, depth, origin, direction)
                else:
                    tool = cq.Workplane("XY", origin=(x, y, z)).slot2D(length, width,
                        angle=feature["direction_deg"]).extrude(sign * depth).val()
                tools = [tool]
            else:
                diameter = _positive(feature["diameter"], "Hole diameter")
                radius = diameter / 2
                tools = [cq.Solid.makeCylinder(radius, depth, origin, direction)]
                hole_type = feature["hole_type"]
                if hole_type in {"countersunk", "counterbored"}:
                    key = "countersink_diameter" if hole_type == "countersunk" else "counterbore_diameter"
                    head = _positive(feature[key], "Head diameter") / 2
                    if head <= radius:
                        raise _BuildIssue("Counterbore/countersink diameter must exceed drill diameter.")
                    if hole_type == "countersunk":
                        angle = feature["countersink_angle_deg"]
                        if not 0 < angle < 180:
                            raise _BuildIssue("Countersink included angle must be between 0 and 180 degrees.")
                        head_depth = (head - radius) / math.tan(math.radians(angle / 2))
                        if head_depth > depth:
                            raise _BuildIssue("Countersink cone exceeds the evidenced hole depth.")
                        tools.append(cq.Solid.makeCone(head, radius, head_depth, origin, direction))
                    else:
                        head_depth = _positive(feature["counterbore_depth"], "Counterbore depth")
                        if head_depth > depth:
                            raise _BuildIssue("Counterbore exceeds the evidenced hole depth.")
                        tools.append(cq.Solid.makeCylinder(head, head_depth, origin, direction))
                    radius = head
                if not _fits(outline, x, y, radius):
                    raise _BuildIssue("Hole footprint extends beyond the evidenced stock outline.")
            for tool in tools:
                shape = shape.cut(tool)
            new_volume, _ = _measure(shape)
            if new_volume >= volume or math.isclose(new_volume, volume, rel_tol=1e-12, abs_tol=0):
                raise _BuildIssue("Feature removes no positive stock volume; check coordinates/pattern overlap.")
            volume = new_volume
    return shape


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _asset(path: Path) -> str:
    return path.relative_to(APP_ROOT).as_posix() if path.is_relative_to(APP_ROOT) else path.as_posix()


def _asset_path(value: str, output: Path) -> Path:
    path = Path(value)
    path = (path if path.is_absolute() else APP_ROOT / path).resolve()
    if not path.is_relative_to(output):
        raise ValueError("Cached asset escapes this builder's output directory.")
    return path


def _check_glb(path: Path) -> None:
    data = path.read_bytes()
    if len(data) < 20 or struct.unpack_from("<4sII", data) != (b"glTF", 2, len(data)):
        raise _BuildIssue("Exporter did not produce a complete binary glTF 2 asset.")
    length, kind = struct.unpack_from("<II", data, 12)
    if kind != 0x4E4F534A or length % 4 or length + 20 > len(data):
        raise _BuildIssue("GLB JSON chunk is invalid.")
    doc = json.loads(data[20:20 + length])
    if not doc.get("meshes") or not doc.get("nodes"):
        raise _BuildIssue("Exported GLB has no mesh/nodes.")
    if not any(c.RECONSTRUCTION_LABEL in n.get("name", "") for n in doc["nodes"]):
        raise _BuildIssue("GLB must retain its reconstruction label.")
    offset = 20 + length
    if offset + 8 > len(data):
        raise _BuildIssue("GLB has no embedded binary geometry.")
    binary_length, binary_kind = struct.unpack_from("<II", data, offset)
    buffers = doc.get("buffers", [])
    if (binary_kind != 0x004E4942 or binary_length % 4 or offset + 8 + binary_length != len(data)
            or len(buffers) != 1 or "uri" in buffers[0] or
            not 0 <= binary_length - buffers[0]["byteLength"] <= 3 or doc.get("images") or doc.get("textures")):
        raise _BuildIssue("GLB must contain self-contained JSON/BIN geometry without textures.")
    materials = doc.get("materials", [])
    used_materials = {p.get("material") for mesh in doc["meshes"] for p in mesh["primitives"]}
    for index in used_materials:
        if index is None or not 0 <= index < len(materials):
            raise _BuildIssue("GLB geometry has no neutral-grey material.")
        colour = materials[index].get("pbrMetallicRoughness", {}).get("baseColorFactor", [])
        if (len(colour) != 4 or not all(math.isfinite(v) for v in colour) or not 0 < colour[0] < 1
                or max(colour[:3]) - min(colour[:3]) > 1e-7 or abs(colour[3] - 1) > 1e-7):
            raise _BuildIssue("GLB material must be opaque neutral grey.")


def _verified_manifest(path: Path, output: Path) -> tuple[dict, c.ModelStatus] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (data["schema"] != BUILDER_VERSION or c.contract_digest(data["template"]) != data["template_sha256"]
                or data["source_sha256"] != data["template"]["source_sha256"]):
            return None
        status = c.ModelStatus.model_validate(data["status"])
        if (status.state != "available" or status.built_at is None or
                status.built_template_sha256 != data["template_sha256"] or
                status.current_template_sha256 != data["template_sha256"] or not status.examples):
            return None
        if (status.review.model_dump(mode="json") != data["template"]["review"] or
                (status.provenance.model_dump(mode="json") if status.provenance else None) != data["template"]["provenance"]):
            return None
        expected = {asset for e in status.examples for asset in (e.glb, e.step) if asset}
        if expected != set(data["artifacts"]):
            return None
        for value, identity in data["artifacts"].items():
            asset = _asset_path(value, output)
            if asset.parent != path.parent.resolve() or asset.stat().st_size != identity["bytes"] or _sha(asset) != identity["sha256"]:
                return None
            if asset.suffix == ".glb":
                _check_glb(asset)
        if any(e.volume_mm3 is None or not math.isfinite(e.volume_mm3) or e.volume_mm3 <= 0 for e in status.examples):
            return None
        return data, status
    except (OSError, ValueError, KeyError, TypeError, struct.error):
        return None


def _failure(template: c.FlatTemplate, output: Path, previous: c.ModelStatus | None,
             issue: _BuildIssue) -> c.ModelStatus:
    digest = c.contract_digest(template)
    if previous and previous.examples:
        try:
            path = _asset_path(previous.examples[0].glb, output).parent / MANIFEST
            verified = _verified_manifest(path, output)
            if (verified and verified[0]["template"]["part"] == template.part and
                    verified[0]["template"]["synthetic"] == template.synthetic and
                    previous.built_template_sha256 == verified[1].built_template_sha256):
                old = verified[1].model_copy(deep=True)
                old.state, old.stale_reason, old.message = "stale", str(issue), str(issue)
                old.current_template_sha256 = digest
                old.unresolved_fields = issue.names
                old.human_input_fields = issue.names
                old.selected_example = previous.selected_example if previous.selected_example in {e.id for e in old.examples} else None
                return old
        except (ValueError, OSError):
            pass
    return c.ModelStatus(state=issue.state, message=str(issue), current_template_sha256=digest,
        review=template.review.model_copy(deep=True), provenance=template.provenance,
        unresolved_fields=issue.names, human_input_fields=issue.names)


def build_template(template: c.FlatTemplate, output_dir: Path, *, previous: c.ModelStatus | None = None) -> c.ModelStatus:
    """Build all supported examples or return an honest unavailable/stale status.

    The caller supplies an effective source-validated FlatTemplate. Files are
    published only after every example succeeds. A cache hit checks the full
    template, builder code and artifact hashes without importing CadQuery.
    """
    output = _output_path(output_dir)
    template = c.FlatTemplate.model_validate(template.model_dump(mode="python"))
    data, digest = template.model_dump(mode="json"), c.contract_digest(template)
    try:
        plan = _plan(data)
        builder_sha = _sha(Path(__file__))
        identity = c.contract_digest({"template_sha256": digest, "builder_sha256": builder_sha})
        destination = (output / ("synthetic" if template.synthetic else "source") / template.part / identity).resolve()
        if not destination.is_relative_to(output):
            raise _BuildIssue("CAD destination escapes the allowed output directory through a symlink.")
        cached = _verified_manifest(destination / MANIFEST, output)
        if cached and cached[0]["builder_sha256"] == builder_sha and cached[0]["template"] == data:
            status = cached[1]
            status.message = "Reused verified cached reconstruction; original build timestamp retained. " + (status.message or "")
            if (previous and previous.built_template_sha256 == digest and
                    previous.selected_example in {e.id for e in status.examples}):
                status.selected_example = previous.selected_example
            return status
        # Expand only active geometry; material, drawing weight and cosmetic
        # thread annotations retain their full source values in the manifest.
        selected_sets = [dict(zip((f["name"] for f in plan.alternatives), indices))
            for indices in itertools.product(*(range(len(f["options"])) for f in plan.alternatives))]
        resolved = [_resolve(plan.geometry, selection) for selection in selected_sets]
        for geometry in resolved:
            _positive_dimensions(geometry)
        try:
            cq = import_module("cadquery")
        except ImportError:
            raise _BuildIssue("CadQuery is unavailable; no reconstruction was built.", state="missing") from None
        output.mkdir(parents=True, exist_ok=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        examples, measurements, artifacts = [], [], {}
        with tempfile.TemporaryDirectory(prefix=".cad-", dir=output) as staging_name:
            staging = Path(staging_name)
            for example_id, selection, geometry in zip(EXAMPLE_IDS, selected_sets, resolved):
                shape = _solid(cq, geometry)
                volume, bounds = _measure(shape)
                stem = f"{template.part}_{example_id}_reconstruction"
                glb, step = staging / (stem + ".glb"), staging / (stem + ".step")
                assembly = cq.Assembly(name=c.RECONSTRUCTION_LABEL)
                assembly.add(shape.scale(0.001), name=stem, color=cq.Color(*GREY))
                assembly.export(str(glb), exportType="GLTF", tolerance=0.00005, angularTolerance=0.1)
                _check_glb(glb)
                cq.exporters.export(shape, str(step), exportType="STEP")
                if not step.is_file() or step.stat().st_size == 0:
                    raise _BuildIssue("STEP export is missing or empty.")
                text = step.read_text(encoding="utf-8")
                if "ISO-10303-21" not in text or "END-ISO-10303-21" not in text:
                    raise _BuildIssue("STEP export has an invalid envelope.")
                # An EXPRESS comment adds the exact disclosure without changing
                # the mm solid or depending on exporter product-name defaults.
                step.write_text(text.replace("HEADER;", "HEADER;\n/* " + c.RECONSTRUCTION_LABEL + " */", 1), encoding="utf-8")
                for asset in (glb, step):
                    artifacts[_asset(destination / asset.name)] = {"sha256": _sha(asset), "bytes": asset.stat().st_size}
                choices = {f["name"]: f["options"][selection[f["name"]]]["value"] for f in plan.alternatives}
                choice_evidence = {f["name"]: f["options"][selection[f["name"]]] for f in plan.alternatives}
                examples.append(c.ModelExample(id=example_id, glb=_asset(destination / glb.name),
                    step=_asset(destination / step.name), choices=choices, possible_reading=True,
                    source_ids=list(dict.fromkeys([*_sources(plan.geometry, selection),
                        *_sources([{key: f["value"].get(key) for key in ("thread_size", "thread_depth")}
                            for f in data["features"] if f["state"] == "known" and
                            f["value"].get("hole_type") == "threaded"])])), volume_mm3=volume))
                measurements.append({"id": example_id, "bounds_mm": bounds, "volume_mm3": volume,
                                     "choice_evidence": choice_evidence})
            sizes = [tuple(hi - lo for lo, hi in zip(*m["bounds_mm"])) for m in measurements]
            message = "Reconstruction built from the supplied effective template; examples are possible readings, not approved choices."
            if template.synthetic:
                message += " SYNTHETIC TEST GEOMETRY: " + (template.fixture_note or "")
            if plan.disclosures:
                message += " " + " ".join(plan.disclosures)
            if len(set(sizes)) > 1:
                message += " Overall size differs by example; per-example bounds are retained in the manifest."
            status = c.ModelStatus(state="available", examples=examples, message=message,
                review=template.review.model_copy(deep=True), provenance=template.provenance,
                human_input_fields=plan.unresolved, unresolved_fields=plan.unresolved, omitted_details=plan.omissions,
                built_at=datetime.now(timezone.utc), built_template_sha256=digest, current_template_sha256=digest,
                overall_size_mm=sizes[0] if len(set(sizes)) == 1 else None)
            manifest = {"schema": BUILDER_VERSION, "builder_sha256": builder_sha, "template_sha256": digest,
                "source_sha256": template.source_sha256, "template": data, "status": status.model_dump(mode="json"),
                "measurements": measurements, "artifacts": artifacts, "glb_units": "m", "step_units": "mm",
                "cad_to_glb": "(x,y,z) mm -> (x,z,-y) * 0.001 m", "colour": list(GREY)}
            (staging / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            # Replacing an invalid/missing cache never rewrites another template's
            # directory. A manifest is committed last; partial outputs cannot hit.
            destination.mkdir(parents=True, exist_ok=True)
            for asset in staging.iterdir():
                if asset.name != MANIFEST:
                    asset.replace(destination / asset.name)
            (staging / MANIFEST).replace(destination / MANIFEST)
        if not _verified_manifest(destination / MANIFEST, output):
            raise _BuildIssue("Published CAD artifacts failed their identity/file checks.")
        return status
    except _BuildIssue as issue:
        return _failure(template, output, previous, issue)
    except Exception as error:
        return _failure(template, output, previous,
            _BuildIssue(f"CAD reconstruction/export failed ({type(error).__name__}): {error}"))


def _record_binding(record: c.PartRecord, template: c.FlatTemplate) -> None:
    drawing = record.drawing
    if (record.id != c.drawing_part_name(template.part) or drawing is None or
            drawing.id != template.part or drawing.source_sha256 != template.source_sha256):
        raise _BuildIssue("Effective template is not bound to this record's current drawing/source hash.")
    if record.synthetic != template.synthetic or record.fixture != template.fixture:
        raise _BuildIssue("Synthetic templates and actual source records cannot share model evidence.")
    fields = list(_fields(template.model_dump(mode="json")))
    numbers = {n.name for n in drawing.numbers}
    sources = numbers | {f.name for f in drawing.fields.values()} | {f"{drawing.id}/source"}
    sources.update(f"{drawing.id}/drawing/page/{p.page}" for p in drawing.page_geometry)
    if template.provenance:
        sources.update(template.provenance.source.source_ids)
    names = {field["name"] for field in fields}
    for field in fields:
        items = [field["evidence"]] if "evidence" in field else []
        items.extend(o["evidence"] for o in field.get("options", []))
        for evidence in items:
            if not set(evidence["number_ids"]) <= numbers or not set(evidence["source_ids"]) <= sources:
                raise _BuildIssue("Template references evidence outside its owning drawing.", [field["name"]])
            derivation = evidence.get("derivation")
            if derivation and (not set(derivation["inputs"]) <= sources | names or
                    derivation.get("pattern_fact") and derivation["pattern_fact"] not in sources | names):
                raise _BuildIssue("Template derivation references missing evidence.", [field["name"]])


def create_model_rebuilder(output_dir: Path) -> c.ModelRebuilder:
    """Return the (record, effective template) callback without writes/CAD imports."""
    output = _output_path(output_dir)

    def rebuild(record: c.PartRecord, template: c.FlatTemplate) -> c.ModelStatus:
        try:
            template = c.FlatTemplate.model_validate(template.model_dump(mode="python"))
            record = c.PartRecord.model_validate(record.model_dump(mode="python"))
        except ValueError:
            # A mutated/inconsistent record is not an effective source input.
            # Do not retain assets or hashes obtained from that invalid record.
            return c.ModelStatus(state="blocked", message="The part or template record is invalid; no reconstruction was built.")
        try:
            _record_binding(record, template)
        except _BuildIssue as issue:
            return _failure(template, output, record.model, issue)
        return build_template(template, output, previous=record.model)

    return rebuild
